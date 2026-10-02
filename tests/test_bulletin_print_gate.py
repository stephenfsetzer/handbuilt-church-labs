"""Booklet print gate wired into bulletin production and the church check.

Every bulletin here is synthetic. No church data belongs in this file.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT, bulletin_input, make_church

try:
    import weasyprint
    from PIL import Image
    from pypdf import PdfReader
    HAVE_RUNTIME = True
except ImportError:  # pragma: no cover - the managed runtime has all three
    HAVE_RUNTIME = False

from skills.bulletin.bulletin_production import interface
from skills.bulletin.bulletin_production.interface import StageFailure, produce
from skills.bulletin.renderer import print_layout as pl
from skills.bulletin.renderer.render_bulletin import mark_print_units
from tools import church_workflow as bridge

DASHES = (chr(0x2014), chr(0x2013))  # em dash and en dash
FONTS = REPO_ROOT / "skills" / "bulletin" / "renderer" / "fonts"


def one_sentence(text: str) -> bool:
    body = text.strip()
    return body.endswith(".") and ". " not in body[:-1] and not any(d in body for d in DASHES)


def long_gospel(sentences: int) -> str:
    return " ".join(f"Synthetic Gospel sentence {i} for layout testing only."
                    for i in range(sentences))


def fourteen_page_input() -> dict:
    """A synthetic service that renders 14 pages before fitting."""
    bulletin = bulletin_input()
    bulletin["options"]["print_mode"] = "booklet"
    bulletin["announcements"] = [
        {"title": f"Notice {i}", "text": "A synthetic notice for layout testing. " * 6}
        for i in range(1, 4)
    ]
    bulletin["readings"]["gospel"]["text"] = long_gospel(340)
    return bulletin


def strip_print_attributes(html: str) -> str:
    return re.sub(r' data-print-(?:unit|role|id)="[^"]*"', "", html)


def units(report) -> list[tuple]:
    return [(u.kind, u.role, u.id, u.first_page, u.last_page) for u in report.units]


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class BookletProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = make_church(Path(self.temp.name))

    def test_fourteen_page_bulletin_is_fitted_to_sixteen_pages(self):
        result = produce(self.church, fourteen_page_input())
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        self.assertEqual(result["print_mode"], "booklet")
        signature = result["booklet_signature"]
        self.assertEqual(signature["sequential_pages"], 16)
        self.assertEqual(signature["blank_pages"], 0)
        self.assertEqual(signature["booklet_sides"], 8)

        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        adjustments = receipt["fit_adjustments"]
        self.assertTrue(adjustments)
        self.assertEqual(adjustments[0]["step"], "inside_cover")
        self.assertEqual(adjustments[0]["detail"]["pages_before"], 14)
        self.assertEqual(adjustments[0]["detail"]["pages"], 16)
        self.assertTrue(receipt["fit_summary"].startswith("To fold into 16 pages, page 2 is left blank"))
        self.assertTrue(one_sentence(receipt["fit_summary"]))
        self.assertEqual(result["fit_summary"], receipt["fit_summary"])
        self.assertEqual(receipt["print_mode"], "booklet")

        checks = {item["name"]: item for item in receipt["quality_checks"]}
        for name in ("booklet_page_count", "blank_pages_deliberate", "back_cover_last",
                     "music_page_turn", "opening_music_whole", "prayer_page_turn",
                     "assets_resolved", "wording_unchanged"):
            self.assertTrue(checks[name]["passed"], name)
            self.assertEqual(set(checks[name]), {"name", "passed", "blocking", "message", "pages"})
        self.assertEqual(checks["booklet_signature"]["blank_pages"], 0)
        self.assertTrue(checks["body_font_embedded"]["passed"])

        # The fitted HTML and the PDF made from it are what the pastor reviews.
        week = Path(result["week_folder"])
        html = next(week.glob("bulletin-*-classic.html")).read_text(encoding="utf-8")
        self.assertIn('class="inside-cover"', html)
        self.assertIn('data-print-fit="1"', html)
        self.assertNotIn("data-pl-ref", html)
        pdf = next(week.glob("bulletin-*-classic.pdf"))
        self.assertEqual(len(PdfReader(str(pdf)).pages), 16)
        self.assertFalse((week / ".print-fit.html").exists())
        self.assertFalse((self.church / "bulletins" / ".staging").exists())

    def test_bulletin_that_cannot_fit_blocks_with_one_plain_sentence(self):
        bulletin = bulletin_input()
        bulletin["options"]["print_mode"] = "booklet"
        result = produce(self.church, bulletin)
        self.assertEqual(result["status"], "blocked")
        error = result["errors"][0]
        self.assertEqual(error["code"], "booklet_fit_failed")
        self.assertEqual(error["stage"], "print_layout")
        self.assertTrue(one_sentence(error["message"]), error["message"])
        self.assertIn("multiple of 4", error["message"])
        self.assertIn("booklet_page_count", error["diagnostics"]["failing_checks"])
        # Nothing reaches the week folder, and no padded booklet is kept.
        self.assertFalse(list((self.church / "bulletins").glob("2026/09/*/bulletin-*.pdf")))
        self.assertFalse(list((self.church / "bulletins" / ".staging").glob("*")))

    def test_turning_off_the_inside_cover_is_respected(self):
        # Without the inside cover, type and spacing alone cannot reach 16
        # pages, so production blocks instead of padding blank pages.
        bulletin = fourteen_page_input()
        bulletin["options"]["allow_blank_inside_cover"] = False
        result = produce(self.church, bulletin)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["errors"][0]["code"], "booklet_fit_failed")
        self.assertIn("14 pages", result["errors"][0]["message"])
        self.assertTrue(one_sentence(result["errors"][0]["message"]))

    def test_renderer_marks_print_units_the_gate_reads_the_same_way(self):
        result = produce(self.church, bulletin_input())
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        self.assertEqual(result["print_mode"], "duplex")
        self.assertEqual(result["fit_summary"], "")
        week = Path(result["week_folder"])
        html = next(week.glob("bulletin-*-classic.html")).read_text(encoding="utf-8")
        self.assertEqual(html.count('data-print-role="opening"'), 1)
        for kind in ("music", "prayer", "section", "back-cover"):
            self.assertIn(f'data-print-unit="{kind}"', html)
        self.assertIn('data-print-id="The Collect of the Day"', html)
        base_url = str(week) + "/"
        marked = pl.measure(html, base_url=base_url)
        unmarked = pl.measure(strip_print_attributes(html), base_url=base_url)
        self.assertNotIn("data-print-unit", strip_print_attributes(html))
        self.assertEqual(units(marked), units(unmarked))
        self.assertGreater(len(marked.units), 20)
        opening = [u for u in marked.units if u.role == "opening"]
        self.assertEqual([u.id for u in opening], ["Entrance Hymn · Hymn 1"])


class PrintOptionTests(unittest.TestCase):
    def test_invalid_print_options_block_before_rendering(self):
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            bulletin = bulletin_input()
            bulletin["options"]["print_mode"] = "folded"
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["field"], "options.print_mode")
            bulletin = bulletin_input()
            bulletin["options"]["allow_blank_inside_cover"] = "yes"
            result = produce(church, bulletin)
            self.assertEqual(result["errors"][0]["field"], "options.allow_blank_inside_cover")

    def test_print_mode_defaults_to_booklet_and_standing_preference_applies(self):
        self.assertEqual(interface._print_options({"options": {}}), ("booklet", True))
        bulletin = {"options": {}}
        interface._resolve_standing_preferences(
            bulletin, {"bulletin": {"print_mode": "duplex", "allow_blank_inside_cover": False}})
        self.assertEqual(interface._print_options(bulletin), ("duplex", False))
        weekly = {"options": {"print_mode": "single"}}
        interface._resolve_standing_preferences(weekly, {"bulletin": {"print_mode": "duplex"}})
        self.assertEqual(interface._print_options(weekly)[0], "single")

    def test_schema_declares_the_print_options(self):
        schema = json.loads((REPO_ROOT / "skills/bulletin/renderer/bulletin-config-schema.json")
                            .read_text(encoding="utf-8"))
        options = schema["properties"]["options"]["properties"]
        self.assertEqual(options["print_mode"]["enum"], ["booklet", "duplex", "single"])
        self.assertEqual(options["print_mode"]["default"], "booklet")
        self.assertIs(options["allow_blank_inside_cover"]["default"], True)


class RendererMarkingTests(unittest.TestCase):
    def test_every_unit_kind_is_marked_with_its_heading(self):
        content = (
            '<div class="cover"><p>Cover</p></div>'
            '<div class="hymn-page"><h2 class="hymn-head"><span class="sh-label">Entrance'
            ' &middot; Hymn 1</span></h2></div>'
            '<div class="section keep-together"><div class="keep-together">'
            '<h2 class="section-head"><span class="sh-label">The Lord&#x27;s Prayer</span></h2>'
            '</div><div class="dialogue response"><p>Our Father</p></div></div>'
            '<div class="section"><p>No heading here.</p></div>'
            '<div class="section"><h2 class="section-head">Plain Head</h2></div>'
            '<div class="hymn-inline"><p>Sequence</p></div>'
            '<div class="dialogue-group"><p>Not a unit by itself.</p></div>'
            '<div class="backpage"><p>Back</p></div>'
        )
        marked = mark_print_units(content)
        self.assertIn('<div class="hymn-page" data-print-unit="music" data-print-role="opening">', marked)
        self.assertIn('<div class="hymn-inline" data-print-unit="music">', marked)
        self.assertIn('data-print-unit="section" data-print-id="The Lord&#x27;s Prayer"', marked)
        self.assertIn('<div class="section" data-print-unit="section"><p>No heading', marked)
        self.assertIn('data-print-id="Plain Head"', marked)
        self.assertIn('<div class="dialogue response" data-print-unit="prayer">', marked)
        self.assertIn('<div class="dialogue-group">', marked)
        self.assertIn('<div class="backpage" data-print-unit="back-cover">', marked)
        self.assertEqual(mark_print_units(marked), marked)
        self.assertEqual(strip_print_attributes(marked), content)


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class AssetAndFontGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)

    def test_a_missing_picture_blocks_even_in_single_mode(self):
        html_path = self.stage / "bulletin.html"
        html_path.write_text('<html><body><p>Words</p><img src="file:///nowhere/retired/staff.png">'
                             "</body></html>", encoding="utf-8")
        with self.assertRaises(StageFailure) as caught:
            interface._print_gate(self.stage, html_path, self.stage / "bulletin.pdf", {},
                                  "single", True)
        self.assertEqual(caught.exception.code, "quality_gate_failed")
        self.assertIn("staff.png", caught.exception.message)
        self.assertTrue(one_sentence(caught.exception.message))

    def render(self, font_file: Path) -> tuple[Path, Path]:
        html = ("<html><head><style>"
                f'@font-face {{ font-family: "Synthetic Face"; src: url("{font_file.as_uri()}"); }}'
                '/* body text */ body { font-family: "Synthetic Face", Georgia, serif; }'
                "</style></head><body><p>Synthetic words for the font check.</p></body></html>")
        html_path = self.stage / "font.html"
        pdf_path = self.stage / "font.pdf"
        html_path.write_text(html, encoding="utf-8")
        weasyprint.HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        return html_path, pdf_path

    @unittest.skipUnless(shutil.which("pdffonts"), "Poppler pdffonts is required")
    def test_declared_body_font_must_be_the_one_embedded(self):
        html_path, pdf_path = self.render(FONTS / "EBGaramond-Regular.ttf")
        check = interface._font_fidelity_check(html_path, pdf_path)
        self.assertEqual(check, {"name": "body_font_embedded", "passed": True,
                                 "family": "Synthetic Face"})

        broken = self.stage / "Broken-Regular.ttf"
        broken.write_text("not a font", encoding="utf-8")
        html_path, pdf_path = self.render(broken)
        with self.assertRaises(StageFailure) as caught:
            interface._font_fidelity_check(html_path, pdf_path)
        self.assertEqual(caught.exception.code, "quality_gate_failed")
        self.assertIn("designed to print in Synthetic Face", caught.exception.message)
        self.assertTrue(one_sentence(caught.exception.message))

    def test_html_without_a_declared_body_font_is_not_checked(self):
        html_path = self.stage / "plain.html"
        html_path.write_text("<html><body><p>Plain</p></body></html>", encoding="utf-8")
        self.assertIsNone(interface._font_fidelity_check(html_path, self.stage / "missing.pdf"))


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class CheckPrintTests(unittest.TestCase):
    """`handbuilt.py check-print` over a synthetic church's print check list."""

    @classmethod
    def setUpClass(cls):
        from tests.test_print_layout import BACK, COVER, RenderedTests, block, page

        cls.temp = tempfile.TemporaryDirectory()
        cls.church = make_church(Path(cls.temp.name))
        week = cls.church / "bulletins" / "2026" / "10" / "2026-10-04-synthetic-sunday"
        images = week / "hymn-images" / "set-1"
        images.mkdir(parents=True)
        Image.new("RGB", (600, 200), (40, 40, 40)).save(images / "stave.png")
        sections = "".join(block(800, name) for name in
                           ("Opening", "Word", "Prayers", "Table", "Sending"))
        final = page(COVER + '<div class="inside-cover"></div>' + sections + BACK)
        (week / "bulletin-2026-10-04-classic.html").write_text(final, encoding="utf-8")
        draft = week / ".revisions" / "v1"
        draft.mkdir(parents=True)
        (draft / "bulletin-2026-10-04-classic.html").write_text(
            RenderedTests.fourteen_page_service(), encoding="utf-8")
        # An archived copy whose font and picture folders have since moved.
        moved_css = ('@font-face { font-family: "Moved Face"; '
                     'src: url("file:///nowhere/retired-plugin/fonts/EBGaramond-Regular.ttf"); }')
        moved_back = ('<div class="backpage"><p>Closing words.</p>'
                      '<img src="file:///nowhere/old-staging/hymn-images/stave.png" '
                      'style="width:2in; height:0.66in"></div>')
        moved = page(COVER + '<div class="inside-cover"></div>' + sections + moved_back, moved_css)
        archived = week / ".revisions" / "v2"
        archived.mkdir(parents=True)
        (archived / "bulletin-2026-10-04-classic.html").write_text(moved, encoding="utf-8")
        cls.week = week

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def write_manifest(self, cases: list[dict]) -> None:
        relative = "bulletins/2026/10/2026-10-04-synthetic-sunday"
        for case in cases:
            case["html"] = f"{relative}/{case['html']}"
        manifest = {"version": 1, "print_mode": "booklet", "allow_blank_inside_cover": True,
                    "cases": cases}
        (self.church / "bulletins" / "print-regressions.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")

    def test_cases_meet_their_expectations_and_moved_assets_are_found(self):
        self.write_manifest([
            {"name": "final", "html": "bulletin-2026-10-04-classic.html", "expect": "pass"},
            {"name": "fourteen pages", "html": ".revisions/v1/bulletin-2026-10-04-classic.html",
             "expect": "fail", "checks": ["booklet_page_count"]},
            {"name": "archived with moved files",
             "html": ".revisions/v2/bulletin-2026-10-04-classic.html", "expect": "pass"},
            {"name": "archived as saved",
             "html": ".revisions/v2/bulletin-2026-10-04-classic.html", "expect": "fail",
             "checks": ["assets_resolved"], "resolve_assets": False},
        ])
        result, code = bridge.check_print(self.church)
        self.assertEqual(code, 0, json.dumps(result, indent=2))
        self.assertEqual((result["status"], result["met"], result["total"]), ("passed", 4, 4))
        cases = {item["name"]: item for item in result["cases"]}
        self.assertEqual(cases["final"]["pages"], 8)
        self.assertEqual(cases["fourteen pages"]["pages"], 14)
        self.assertIn("booklet_page_count", cases["fourteen pages"]["failed_checks"])
        resolved = {item["name"]: item for item in cases["archived with moved files"]["resolved_assets"]}
        self.assertEqual(set(resolved), {"EBGaramond-Regular.ttf", "stave.png"})
        self.assertEqual(resolved["EBGaramond-Regular.ttf"]["found_in"], "the plugin's fonts")
        self.assertEqual(resolved["stave.png"]["found_in"], "the week's folder")
        self.assertTrue(resolved["stave.png"]["path"].endswith("hymn-images/set-1/stave.png"))
        self.assertEqual(cases["archived as saved"]["resolved_assets"], [])
        self.assertIn("assets_resolved", cases["archived as saved"]["failed_checks"])
        # The saved file is never rewritten.
        saved = (self.week / ".revisions" / "v2" / "bulletin-2026-10-04-classic.html").read_text()
        self.assertIn("file:///nowhere/old-staging/hymn-images/stave.png", saved)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bridge._check_print_command(self.church, "table"), 0)
        table = out.getvalue()
        self.assertIn("Print check: 4 of 4 cases met their expectation.", table)
        self.assertIn("found stave.png in the week's folder", table)
        self.assertIn("found EBGaramond-Regular.ttf in the plugin's fonts", table)
        self.assertFalse(any(d in table for d in DASHES))

    def test_unmet_expectation_exits_one_and_json_is_available(self):
        self.write_manifest([
            {"name": "fourteen pages expected to pass",
             "html": ".revisions/v1/bulletin-2026-10-04-classic.html", "expect": "pass"},
            {"name": "final expected to fail",
             "html": "bulletin-2026-10-04-classic.html", "expect": "fail",
             "checks": ["page_fill"]},
        ])
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "church_workflow.py"),
             "--church-folder", str(self.church), "check-print", "--format", "json"],
            capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual((result["status"], result["met"]), ("failed", 0))
        self.assertTrue(all(not item["met"] for item in result["cases"]))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bridge._check_print_command(self.church, "table"), 1)
        self.assertIn("NOT MET  fourteen pages expected to pass", out.getvalue())
        self.assertIn("multiple of 4", out.getvalue())

    def test_missing_or_invalid_list_is_explained(self):
        (self.church / "bulletins" / "print-regressions.json").unlink(missing_ok=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bridge._check_print_command(self.church, "table"), 2)
        self.assertIn("no print check list yet", out.getvalue())
        self.write_manifest([{"name": "bad", "html": "bulletin-2026-10-04-classic.html",
                              "expect": "fail", "checks": ["not_a_check"]}])
        with self.assertRaises(ValueError):
            bridge.check_print(self.church)


if __name__ == "__main__":
    unittest.main()
