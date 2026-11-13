"""Fitting checks what it changes (PRD-005A decision, 2026-11-12).

Synthetic tests for the second round of booklet fitting rules:

- said_line_wrap: larger body type never wraps a line said together; a said
  text that would wrap stays at the theme's size, and one that still wraps
  prints its speaker label above the text.
- bulletin.body_size and bulletin.music_min_scale in church.yaml.
- stranded_heading: a heading never ends a page; the section-start step
  repairs it.
- Announcement pictures size to the text column, and a featured
  announcement block prints its figure, progress and QR code as real text.
- revise moves only the files production made.

Every bulletin here is synthetic. No church data belongs in this file.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER = REPO_ROOT / "skills" / "bulletin" / "renderer"
if str(RENDERER) not in sys.path:
    sys.path.insert(0, str(RENDERER))

try:
    import weasyprint  # noqa: F401
    from PIL import Image
    HAVE_RUNTIME = True
except ImportError:  # pragma: no cover - the managed runtime has both
    HAVE_RUNTIME = False

import print_layout as pl  # noqa: E402
from tests.test_print_layout import BACK, COVER, block, by_check, hymn, one_sentence, page  # noqa: E402

# Said text set like the bulletin: a speaker column beside the text column.
# The page measure is 7.3in; the speaker column takes 1in, leaving 6.3in.
SAID_CSS = """
.dialogue { display: table; width: 100%; margin: 0; }
.dialogue .speaker { display: table-cell; width: 1in; }
.dialogue .line { display: table-cell; }
.dlg-line { margin: 0; }
.wide { display: inline-block; height: 4pt; }
"""


def said_section(label: str, width_em: float, lines: int = 2) -> str:
    """A said text whose lines are one short word and a box ``width_em`` wide.

    The box is sized in em, so it grows with the type: a line can fit beside
    the speaker label at 12pt and wrap at 13pt, which is the case fitting must
    catch. The box carries no words, so the wording check is unaffected.
    """
    body = "".join(f'<p class="dlg-line lvl0">Amen <span class="wide" style="width:{width_em}em">'
                   f'</span></p>' for _ in range(lines))
    return (f'<div class="section"><h2 class="section-head"><span class="sh-label">{label}'
            f'</span></h2><div class="dialogue response"><span class="speaker">All</span>'
            f'<span class="line">{body}</span></div></div>')


@unittest.skipUnless(HAVE_RUNTIME, "WeasyPrint and Pillow are required")
class FitRoundTwoRenderedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        Image.new("RGB", (600, 200), (40, 40, 40)).save(cls.dir / "stave.png")
        cls.base_url = str(cls.dir) + "/"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # -- said_line_wrap --------------------------------------------------------

    def test_larger_type_keeps_a_said_text_at_the_theme_size(self):
        # 34em fits beside the label at 12pt (about 438pt of 453pt) and wraps at 13pt.
        html = page(COVER + block(600, "Opening") + said_section("The Creed", 34) + BACK, SAID_CSS)
        fitter = pl._Fitter(html, self.base_url, "duplex", True, (), 20)
        base, findings = fitter.render(pl._Params())
        self.assertTrue(by_check(findings)["said_line_wrap"].passed)

        larger, larger_findings = fitter.render(pl._Params(font_pt=13.0))
        failing = by_check(larger_findings)["said_line_wrap"]
        self.assertFalse(failing.passed)
        self.assertTrue(failing.blocking)
        self.assertTrue(failing.message.startswith("In the Creed 2 lines wrap"))
        self.assertTrue(one_sentence(failing.message))

        fixed = fitter.fix_said(pl._Params(font_pt=13.0))
        self.assertEqual(len(fixed.said_hold), 1)
        self.assertEqual(fixed.said_stack, ())
        layout, fixed_findings = fitter.render(fixed)
        self.assertTrue(by_check(fixed_findings)["said_line_wrap"].passed)
        self.assertTrue(by_check(fixed_findings)["wording_unchanged"].passed)

        adjustments = pl._adjustments(fixed, base, layout, "duplex")
        said = [a for a in adjustments if a["step"] == "said_text_size"]
        self.assertEqual(said[0]["summary"], "the Creed stays at 12pt so no line said together wraps")
        self.assertEqual(said[0]["detail"]["ids"], ["The Creed"])

    def test_a_said_text_that_wraps_at_the_theme_size_prints_its_label_above(self):
        # 38em wraps beside the label even at 12pt, and fits the full 7.3in measure.
        html = page(COVER + block(600, "Opening") + said_section("The Creed", 38) + BACK, SAID_CSS)
        before = by_check(pl.check(pl.measure(html, base_url=self.base_url), print_mode="duplex"))
        self.assertFalse(before["said_line_wrap"].passed)

        result = pl.fit(html, base_url=self.base_url, print_mode="duplex")
        self.assertEqual(result.status, "fit", [f.message for f in result.findings if not f.passed])
        findings = by_check(result.findings)
        self.assertTrue(findings["said_line_wrap"].passed)
        self.assertTrue(findings["wording_unchanged"].passed)
        steps = [a["step"] for a in result.adjustments]
        self.assertIn("said_label_above", steps)
        self.assertNotIn("type_size", steps)
        self.assertIn("said-stack", result.html)
        summary = pl.describe_adjustments(result.adjustments)
        self.assertIn("the Creed prints the speaker label above the text", summary)
        self.assertTrue(one_sentence(summary))

    # -- body_size and music_min_scale ------------------------------------------

    def test_church_body_size_caps_the_type_size_step(self):
        html = page(COVER + block(600, "Opening") + BACK)
        capped = pl._Fitter(html, self.base_url, "booklet", True, (), 5, max_body_pt=12.0)
        capped.render(pl._Params())
        self.assertTrue(all(c.font_pt is None for c in capped.candidates()))

        default = pl._Fitter(html, self.base_url, "booklet", True, (), 5)
        default.render(pl._Params())
        sizes = {c.font_pt for c in default.candidates() if c.font_pt is not None}
        self.assertEqual(max(sizes), 13.0)

        between = pl._Fitter(html, self.base_url, "booklet", True, (), 5, max_body_pt=12.5)
        between.render(pl._Params())
        self.assertEqual(max(c.font_pt or 0 for c in between.candidates()), 12.5)

    def test_music_min_scale_is_bounded(self):
        self.assertEqual(pl._music_scales(0.95), (1.0, 0.99, 0.98, 0.97, 0.96, 0.95))
        self.assertEqual(pl._music_scales(0.85)[-1], 0.85)
        with self.assertRaises(ValueError):
            pl.fit(page(COVER + BACK), base_url=self.base_url, music_min_scale=0.5)

    def music_over_two_pages(self) -> str:
        # Page 2: a short entrance hymn (130px), then a four-stave acclamation of
        # 30 + 4 x 220px. Three staves fit on page 2 and the fourth turns to
        # page 3 (facing pages, so no rule fails). Whole on page 2 it needs
        # 88% or less; at 95% it does not fit.
        return page(COVER + hymn("Entrance Hymn", 1, 100) + hymn("Gospel Acclamation", 4, 220)
                    + block(400, "Closing") + BACK)

    def test_music_split_over_two_pages_moves_onto_one_at_the_church_minimum(self):
        html = self.music_over_two_pages()
        before = pl.measure(html, base_url=self.base_url)
        acclamation = [u for u in before.units if u.id == "Gospel Acclamation"][0]
        self.assertEqual((acclamation.first_page, acclamation.last_page), (2, 3))

        default = pl.fit(html, base_url=self.base_url, print_mode="duplex")
        self.assertEqual(default.status, "unchanged")

        result = pl.fit(html, base_url=self.base_url, print_mode="duplex", music_min_scale=0.85)
        self.assertEqual(result.status, "fit")
        music = [a for a in result.adjustments if a["step"] == "music_scale"]
        self.assertEqual(len(music), 1)
        scale = music[0]["detail"]["scale"]
        self.assertGreaterEqual(scale, 0.85)
        self.assertLess(scale, 0.95)
        self.assertEqual(music[0]["detail"]["min_scale"], 0.85)
        self.assertIn(f"prints at {round(scale * 100)}% so it fits on page 2", music[0]["summary"])
        moved = [u for u in result.report.units if u.id == "Gospel Acclamation"][0]
        self.assertEqual((moved.first_page, moved.last_page), (2, 2))
        self.assertTrue(by_check(result.findings)["wording_unchanged"].passed)

    # -- stranded_heading -------------------------------------------------------

    @staticmethod
    def long_section(label: str, lines: int = 25) -> str:
        body = "".join(f"<p>Prayer line {i} for the synthetic test.</p>" for i in range(lines))
        return (f'<div class="section"><h2 class="section-head"><span class="sh-label">{label}'
                f'</span></h2>{body}</div>')

    def test_a_heading_left_at_the_foot_of_a_page_starts_the_next_page(self):
        html = page(COVER + block(800, "Opening") + self.long_section("The Prayers") + BACK)
        before = by_check(pl.check(pl.measure(html, base_url=self.base_url), print_mode="duplex"))
        self.assertFalse(before["stranded_heading"].passed)
        self.assertEqual(before["stranded_heading"].message,
                         "The Prayers sits at the foot of page 2 with its text on page 3.")

        result = pl.fit(html, base_url=self.base_url, print_mode="duplex")
        self.assertEqual(result.status, "fit")
        moved = [a for a in result.adjustments if a["step"] == "section_start"]
        self.assertEqual([a["detail"]["id"] for a in moved], ["The Prayers"])
        self.assertTrue(by_check(result.findings)["stranded_heading"].passed)

        pinned = pl.fit(html, base_url=self.base_url, print_mode="duplex",
                        pinned_section_ids=("The Prayers",))
        self.assertEqual(pinned.status, "failed")

    def test_a_service_title_moves_with_its_first_section(self):
        title = '<h1 class="service-title" style="font-size:20pt; margin:0">The Meal</h1>'
        html = page(COVER + block(780, "Opening") + title + self.long_section("The Thanksgiving")
                    + BACK)
        report = pl.measure(html, base_url=self.base_url)
        stranded = [h for _, h in pl._stranded(report)]
        self.assertEqual([(h.kind, h.id) for h in stranded], [("title", "The Meal")])

        result = pl.fit(html, base_url=self.base_url, print_mode="duplex")
        self.assertEqual(result.status, "fit")
        self.assertIn('<h1 class="service-title" style="font-size:20pt; margin:0; break-before: page"',
                      result.html)
        moved = [a for a in result.adjustments if a["step"] == "section_start"]
        self.assertEqual(moved[0]["summary"], "The Meal starts a new page (page 3)")


class StrandedRuleTests(unittest.TestCase):
    """The stranded_heading rule on hand-built layout reports."""

    @staticmethod
    def report(*headings):
        return pl.LayoutReport(pages=8, fill=[0.9] * 8, blank=[False] * 8,
                               units=[pl.Unit("back-cover", None, "back page", 8, 8)],
                               text="Synthetic words.", headings=list(headings))

    def test_only_a_heading_with_little_below_it_and_text_overleaf_fails(self):
        ok = [pl.Heading("section", "The Peace", 5, 0.05, False),
              pl.Heading("section", "The Creed", 5, 0.40, True),
              pl.Heading("section", "Opening", 1, 0.02, True)]
        self.assertTrue(by_check(pl.check(self.report(*ok)))["stranded_heading"].passed)
        bad = by_check(pl.check(self.report(pl.Heading("section", "The Peace", 5, 0.05, True))))
        self.assertFalse(bad["stranded_heading"].passed)
        self.assertEqual(bad["stranded_heading"].pages, [5])
        self.assertEqual(bad["stranded_heading"].message,
                         "The Peace sits at the foot of page 5 with its text on page 6.")

    def test_said_wrap_message_names_each_text_once(self):
        report = self.report()
        report.said_wraps = [pl.SaidWrap("The Creed", 4, "maker of heaven and earth"),
                             pl.SaidWrap("The Creed", 4, "of all that is"),
                             pl.SaidWrap("The Lord's Prayer", 7, "on earth")]
        finding = by_check(pl.check(report))["said_line_wrap"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.pages, [4, 7])
        self.assertTrue(finding.message.startswith(
            "In the Creed 2 lines wrap (for example \"maker of heaven and earth\") and in the "
            "Lord's Prayer 1 line wraps"))


class AnnouncementColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        if HAVE_RUNTIME:
            # A wide synthetic poster: 2000 x 700 px at 100 dpi is 20in wide.
            Image.new("RGB", (2000, 700), (30, 90, 120)).save(cls.root / "poster.png", dpi=(100, 100))
            Image.new("RGB", (400, 500), (200, 180, 150)).save(cls.root / "photo.jpg")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def cfg(self, **entry):
        return {"announcements": [{"title": "Synthetic Fund", "text": "Synthetic appeal.", **entry}]}

    @unittest.skipUnless(HAVE_RUNTIME, "Pillow is required")
    def test_pictures_size_to_the_text_column(self):
        from skills.bulletin.renderer import render_bulletin as rb
        self.assertEqual(rb.announcement_column_width("modern"), 5.75)
        self.assertEqual(rb.announcement_column_width("classic"), 7.3)
        modern = rb.announcements_section(self.cfg(images=["poster.png"]), self.root, "modern")
        classic = rb.announcements_section(self.cfg(images=["poster.png"]), self.root, "classic")
        self.assertIn("width:5.75in", modern)
        self.assertNotIn("width:7.30in", modern)
        self.assertIn("width:7.30in", classic)

    @unittest.skipUnless(HAVE_RUNTIME, "Pillow is required")
    def test_featured_block_prints_figure_progress_and_code_as_text(self):
        from skills.bulletin.renderer import render_bulletin as rb
        featured = {"photo": "photo.jpg", "figure": "More than $2,400",
                    "figure_note": "given toward our $8,000 goal", "progress": 20,
                    "qr_url": "https://give.example.invalid/fund", "qr_label": "Scan to give"}
        html = rb.announcements_section(self.cfg(featured=featured), self.root, "modern")
        self.assertIn('<div class="announcement featured">', html)
        self.assertIn('<p class="f-figure">More than $2,400</p>', html)
        self.assertIn('<p class="f-note">given toward our $8,000 goal</p>', html)
        self.assertIn('style="width:20%"', html)
        self.assertIn('src="data:image/png;base64,', html)
        self.assertIn('<p class="f-scan">Scan to give</p>', html)
        self.assertIn((self.root / "photo.jpg").resolve().as_uri(), html)
        self.assertIn("Synthetic appeal.", html)

    def test_featured_block_css_keeps_it_whole(self):
        css = (RENDERER / "themes" / "base.css").read_text(encoding="utf-8")
        start = css.index(".announcement.featured {")
        self.assertIn("break-inside: avoid", css[start:css.index("}", start)])


class FeaturedValidationTests(unittest.TestCase):
    def check(self, featured):
        from skills.bulletin.bulletin_production import interface
        interface._validate_featured_announcements(
            {"announcements": [{"title": "Fund", "text": "Text.", "featured": featured}]})

    def test_good_block_passes_and_bad_values_block(self):
        from skills.bulletin.bulletin_production.interface import StageFailure
        self.check({"figure": "More than $2,400", "progress": 40,
                    "qr_url": "https://give.example.invalid/fund"})
        for bad, field in (({"qr_url": "give.example.invalid"}, "qr_url"),
                           ({"progress": 140}, "progress"),
                           ({"progress": True}, "progress"),
                           ({"figure": 5}, "figure"),
                           ({"poster": "x.png"}, "featured"),
                           ({}, "featured")):
            with self.assertRaises(StageFailure) as caught:
                self.check(bad)
            self.assertTrue(caught.exception.field.endswith(field), caught.exception.field)


class PrintSettingsTests(unittest.TestCase):
    def settings(self, **bulletin):
        from skills.bulletin.bulletin_production import interface
        return interface._print_settings({"bulletin": bulletin})

    def test_defaults_and_accepted_forms(self):
        default = self.settings()
        self.assertIsNone(default["body_size_pt"])
        self.assertEqual(default["music_min_scale"], 0.95)
        for value in ("12pt", 12, "12", "12 pt"):
            self.assertEqual(self.settings(body_size=value)["body_size_pt"], 12.0)
        for value in (0.85, "0.85", "85%", 85):
            self.assertEqual(self.settings(music_min_scale=value)["music_min_scale"], 0.85)
        self.assertEqual(self.settings(body_size="12pt")["source"], {"body_size": "church.yaml"})

    def test_out_of_range_values_block(self):
        from skills.bulletin.bulletin_production.interface import StageFailure
        for bulletin in ({"body_size": "9pt"}, {"body_size": "large"}, {"body_size": True},
                         {"music_min_scale": 0.5}, {"music_min_scale": "110%"}):
            with self.assertRaises(StageFailure) as caught:
                self.settings(**bulletin)
            self.assertEqual(caught.exception.code, "invalid_church_setting")

    def test_print_gate_passes_the_settings_to_fitting(self):
        from skills.bulletin.bulletin_production import interface
        seen = {}

        def fake_run(command, capture_output, text, env, **_more):
            seen["command"] = command
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(
                {"status": "unchanged", "pages": 4, "findings": [], "adjustments": [],
                 "summary": ""}), stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            html = stage / "bulletin.html"
            html.write_text("<html><body><p>Synthetic</p></body></html>", encoding="utf-8")
            with patch.object(interface.subprocess, "run", fake_run):
                interface._print_gate(stage, html, stage / "bulletin.pdf", {}, "booklet", True,
                                      {"body_size_pt": 12.0, "music_min_scale": 0.85})
        command = seen["command"]
        self.assertEqual(command[command.index("--max-body-pt") + 1], "12.0")
        self.assertEqual(command[command.index("--music-min-scale") + 1], "0.85")


class ReviseKeepsChurchFilesTests(unittest.TestCase):
    def _patch(self, church_config=None):
        from skills.bulletin.bulletin_production import interface
        from tests.test_bulletin_revision import fake_run
        brand = {"church": {"name": "Public Test Parish"}, "logo": {},
                 "colors": {"rubric_red": "#7f3030"}, "qr": {}}
        return patch.multiple(interface,
                              _load_church_configuration=lambda root: (church_config or {}, brand),
                              _run=fake_run, _quality_gate=lambda *args: [])

    def produce_and_add_church_files(self, church, *, legacy=False):
        from skills.bulletin.bulletin_production import produce
        from tests.helpers import bulletin_input
        with self._patch():
            first = produce(church, bulletin_input())
        receipt_path = Path(first["receipt_path"])
        week = receipt_path.parent
        (week / "README.md").write_text("Sources for this week.\n", encoding="utf-8")
        (week / "announcements").mkdir()
        (week / "announcements" / "photo.jpg").write_bytes(b"synthetic photo")
        if legacy:
            # A receipt written before package_files existed.
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt.pop("package_files", None)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return first, receipt_path, week

    def check_revision(self, legacy):
        from skills.bulletin.bulletin_production import revise
        from tests.helpers import make_church
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            first, receipt_path, week = self.produce_and_add_church_files(church, legacy=legacy)
            produced = set(json.loads(receipt_path.read_text(encoding="utf-8"))["artifacts"][i]["path"]
                           for i in range(4))
            with self._patch():
                revised = revise(church, receipt_path,
                                 {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(revised["status"], "ready_for_review", revised)
            self.assertEqual(revised["preserved_files"], ["README.md", "announcements/photo.jpg"])
            self.assertEqual((week / "README.md").read_text(encoding="utf-8"), "Sources for this week.\n")
            self.assertTrue((week / "announcements" / "photo.jpg").is_file())
            receipt = json.loads((week / "bulletin-production-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["preserved_files"], ["README.md", "announcements/photo.jpg"])
            self.assertIn("bulletin-production-receipt.json", receipt["package_files"])
            self.assertNotIn("README.md", receipt["package_files"])
            archive = church / Path(receipt["revision_of"]["receipt_path"]).parent
            archived = sorted(p.relative_to(archive).as_posix() for p in archive.rglob("*")
                              if p.is_file())
            self.assertNotIn("README.md", archived)
            self.assertNotIn("announcements/photo.jpg", archived)
            self.assertIn("bulletin-production-receipt.json", archived)
            for path in produced:
                self.assertIn(Path(path).name, archived)

    def test_revise_moves_only_files_production_made(self):
        self.check_revision(legacy=False)

    def test_revise_reads_a_receipt_from_before_package_files(self):
        self.check_revision(legacy=True)

    def test_produce_records_print_settings_in_the_receipt(self):
        from skills.bulletin.bulletin_production import produce
        from tests.helpers import bulletin_input, make_church
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            with self._patch({"bulletin": {"body_size": "12pt", "music_min_scale": "85%"}}):
                result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "ready_for_review", result)
            self.assertEqual(result["print_settings"]["body_size_pt"], 12.0)
            self.assertEqual(result["print_settings"]["music_min_scale"], 0.85)
            receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["print_settings"]["source"],
                             {"body_size": "church.yaml", "music_min_scale": "church.yaml"})


class PrintCheckLookupTests(unittest.TestCase):
    def test_saved_drafts_find_their_week_folder(self):
        from tools import church_workflow as cw
        week = Path("/church/bulletins/2026/01/2026-01-04-synthetic")
        for copy in ("revisions/2026-01-02-workflow-draft", ".revisions/run-1"):
            self.assertEqual(cw._week_folder(week / copy / "bulletin.html"), week)
        self.assertEqual(cw._week_folder(week / "bulletin.html"), week)


if __name__ == "__main__":
    unittest.main()
