"""Field regressions: problems real pastors hit, driven through production interfaces.

Each test asserts what a pastor needs, not what the code does today. A failing
test here is a finding. Everything is synthetic (an invented church, invented
prayer text, the shared Riverbend finance fixture); no church data belongs here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tests.helpers import (
    REPO_ROOT, bulletin_input, make_church, readings_content, reading_metadata,
    reading_selection, research_brief, research_metadata, verify_liturgy_source,
)

try:
    import weasyprint  # noqa: F401
    from pypdf import PdfReader
    HAVE_RUNTIME = True
except ImportError:  # pragma: no cover - the managed runtime has these
    HAVE_RUNTIME = False

sys.path.insert(0, str(REPO_ROOT / "skills" / "sermon-research"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "build-my-brand"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "onboarding" / "scripts"))

from skills.bulletin.bulletin_production import finalize, produce, revise  # noqa: E402
from tests.test_bulletin_saved_worship import _configured_profile  # noqa: E402
from tools import church_workflow as bridge  # noqa: E402
from tools import workflow_updates as updates  # noqa: E402

SHIPPED_ACCLAMATION = "Blessed be God: Father, Son, and Holy Spirit"
SHIPPED_PEACE = "The peace of the Lord be always with you"
SHIPPED_DISMISSAL = "Let us go forth in the name of Christ"


def _squash(text: str) -> str:
    return " ".join(text.split())


def _printed_html(folder: Path) -> str:
    """The week's classic HTML with comments, styles and tags removed."""
    html = next(Path(folder).glob("bulletin-*-classic.html")).read_text(encoding="utf-8")
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return _squash(re.sub(r"<[^>]+>", " ", html))


def _pdf_text(folder: Path, template: str = "classic") -> str:
    pdf = next(Path(folder).glob(f"bulletin-*-{template}.pdf"))
    return _squash("\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages))


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class BulletinFieldRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = make_church(Path(self.temp.name))

    # ---- helpers -------------------------------------------------------

    def source(self, name: str, text: str) -> str:
        path = self.church / "worship" / "liturgy" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        verify_liturgy_source(self.church, path)
        return str(path.relative_to(self.church))

    def edit_profile(self, **sections) -> None:
        path = self.church / "worship" / "profile.yaml"
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key, value in sections.items():
            if isinstance(value, dict) and isinstance(profile.get(key), dict):
                profile[key].update(value)
            else:
                profile[key] = value
        path.write_text(yaml.safe_dump(profile), encoding="utf-8")

    def edit_church(self, **sections) -> None:
        path = self.church / "church.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key, value in sections.items():
            config[key] = value
        path.write_text(yaml.safe_dump(config), encoding="utf-8")

    def weekly(self) -> dict:
        request = bulletin_input()
        request["liturgy"] = {}
        return request

    def produce_ready(self, request: dict) -> dict:
        result = produce(self.church, request)
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        return result

    # ---- F01 -----------------------------------------------------------

    def test_f01_standing_opening_peace_and_dismissal_wording_prints_exactly(self):
        """A pastor sees the shipped opening, peace or dismissal wording instead of the church's own saved words."""
        _configured_profile(self.church)
        own = {
            "opening-acclamation": ("Synthetic opening call about lanterns.", "Synthetic opening answer about lanterns."),
            "peace": ("Synthetic peace greeting about rivers.", "Synthetic peace answer about rivers."),
            "dismissal": ("Synthetic sending words about orchards.", "Synthetic sending answer about orchards."),
        }
        files = {}
        for unit, (leader, people) in own.items():
            files[unit] = self.source(f"{unit}.md", f"# {unit.title()}\n\nCelebrant\t{leader}\n\n**People\t{people}**\n")
        self.edit_profile(files=files)
        result = self.produce_ready(self.weekly())
        folder = Path(result["week_folder"])
        for label, text in (("page", _printed_html(folder)), ("PDF", _pdf_text(folder))):
            for leader, people in own.values():
                for sentence in (leader, people):
                    self.assertEqual(text.count(sentence), 1, f"{sentence!r} in the {label}")
            for shipped in (SHIPPED_ACCLAMATION, SHIPPED_PEACE, SHIPPED_DISMISSAL):
                self.assertNotIn(shipped, text, f"the shipped wording still prints in the {label}")

    # ---- F02 -----------------------------------------------------------

    def test_f02_two_custom_units_each_print_once_in_their_own_section(self):
        """A pastor sees one custom prayer repeated, swapped with another, or missing."""
        _configured_profile(self.church, prayers_of_the_people="custom", doxology="custom", blessing="local")
        sentences = {
            "prayers_of_the_people": "Synthetic intercession sentence about harbors.",
            "doxology": "Synthetic doxology sentence about meadows.",
            "blessing": "Synthetic blessing sentence about lanterns.",
        }
        paths = {
            "prayers_of_the_people": self.source("pop.md", f"# Synthetic Prayers\n\nCelebrant\t{sentences['prayers_of_the_people']}\n"),
            "doxology": self.source("dox.md", f"# Synthetic Doxology\n\n**All\t{sentences['doxology']}**\n"),
            "blessing": self.source("blessing.md", f"# Synthetic Blessing\n\nCelebrant\t{sentences['blessing']}\n"),
        }
        self.edit_profile(sources=paths)
        result = self.produce_ready(self.weekly())
        folder = Path(result["week_folder"])
        for label, text in (("page", _printed_html(folder)), ("PDF", _pdf_text(folder))):
            for key, sentence in sentences.items():
                self.assertEqual(text.count(sentence), 1, f"{key} appears {text.count(sentence)} times in the {label}")
            self.assertLess(text.index(sentences["prayers_of_the_people"]), text.index(sentences["doxology"]),
                            f"the prayers belong before the doxology in the {label}")
            self.assertLess(text.index(sentences["doxology"]), text.index(sentences["blessing"]),
                            f"the blessing belongs after the doxology in the {label}")

    # ---- F03 -----------------------------------------------------------

    def test_f03_standing_communion_welcome_prints_without_a_weekly_instruction(self):
        """A pastor must retype the communion welcome every week even though it is saved in the church profile."""
        _configured_profile(self.church)
        welcome = self.source("welcome.md", "# Communion Welcome\n\nSynthetic standing welcome for every visitor.\n")
        self.edit_profile(sources={"communion_welcome": welcome})
        for date in ("2026-09-20", "2026-09-27"):
            request = self.weekly()
            request["service"]["date"] = date
            result = self.produce_ready(request)
            folder = Path(result["week_folder"])
            self.assertIn("Synthetic standing welcome for every visitor.", _printed_html(folder), date)
            self.assertIn("Synthetic standing welcome for every visitor.", _pdf_text(folder), date)

    # ---- F04 -----------------------------------------------------------

    def test_f04_thirteen_and_fourteen_page_services_fold_cleanly_or_say_why_not(self):
        """A pastor gets a booklet that is not a multiple of 4, or a blank page before the back cover."""
        from tests.test_bulletin_print_gate import fourteen_page_input, long_gospel
        for sentences in (250, 280, 340):  # 13 pages, 14 pages, 14 pages before fitting
            with self.subTest(gospel_sentences=sentences):
                self.setUp()
                request = fourteen_page_input()
                request["readings"]["gospel"]["text"] = long_gospel(sentences)
                result = produce(self.church, request)
                if result["status"] == "blocked":
                    # An honest block is acceptable only if it names the page count.
                    self.assertEqual(result["errors"][0]["code"], "booklet_fit_failed", result["errors"])
                    self.assertRegex(result["errors"][0]["message"], r"\d+ pages")
                    continue
                self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
                signature = result.get("booklet_signature") or {}
                self.assertIn("sequential_pages", signature, "the result does not report the page count")
                pdf = next(Path(result["week_folder"]).glob("bulletin-*-classic.pdf"))
                pages = [(page.extract_text() or "").strip() for page in PdfReader(str(pdf)).pages]
                self.assertEqual(len(pages), signature["sequential_pages"])
                self.assertEqual(len(pages) % 4, 0, f"{len(pages)} pages cannot be folded")
                self.assertTrue(pages[-1], "the back cover is blank")
                self.assertTrue(pages[-2], "a blank page sits between the last service page and the back cover")

    # ---- F05 -----------------------------------------------------------

    def test_f05_hymn_with_only_a_title_is_named_before_approval(self):
        """A pastor approves a bulletin without being told which hymn has no music image."""
        from PIL import Image
        (self.church / "music").mkdir(exist_ok=True)
        Image.new("RGB", (600, 300), "white").save(self.church / "music" / "scan.png")
        request = bulletin_input()
        for slot, hymn in request["hymns"].items():
            hymn["images"] = ["music/scan.png"]
        request["hymns"]["gradual"] = {"number": 99, "title": "Unscanned Zephyr Hymn", "tune": "TEST TUNE"}
        result = produce(self.church, request)
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        notes = [n for n in list(result.get("warnings") or []) + list(result.get("open_items") or [])
                 if isinstance(n, dict) and n.get("code") != "page_fill_warning"]
        self.assertTrue(
            any(n.get("field") == "hymns.gradual" and "Unscanned Zephyr Hymn" in n.get("message", "") for n in notes),
            f"no warning or open item names the hymn for the pastor; got {notes}",
        )

    # ---- F06 -----------------------------------------------------------

    def test_f06_variant_name_serving_today_and_source_notes_stay_off_the_page(self):
        """A pastor sees an internal variant name, an unwanted Serving Today block, or a source note printed."""
        _configured_profile(self.church)
        (self.church / "worship" / "orders").mkdir(parents=True, exist_ok=True)
        (self.church / "worship" / "orders" / "principal.yaml").write_text("{}\n", encoding="utf-8")
        self.edit_profile(service_variants={"principal": {
            "name": "Internal Principal Label Quartz", "base_service_plan": "episcopal-rite-ii",
            "order_file": "worship/orders/principal.yaml", "confirmation_policy": "ask_each_week"}})
        self.edit_church(bulletin={"include_serving_today": False})
        request = self.weekly()
        request["service"]["variant"] = "principal"
        request["service"]["serving"] = [{"role": "Lector", "name": "Synthetic Reader Marigold"}]
        self.edit_profile(sources={"prayers_of_the_people": self.source(
            "notes.md",
            "<!--\nSource: Synthetic Prayer Book, page 12.\n# Imported Heading Note Quince\n-->\n\n"
            "# Synthetic Prayers\n\nCelebrant\tSynthetic body line.\n\n"
            "<!-- Source: Second Note Pomegranate -->\n")}, defaults={"prayers_of_the_people": "custom"})
        result = self.produce_ready(request)
        folder = Path(result["week_folder"])
        html = next(folder.glob("bulletin-*-classic.html")).read_text(encoding="utf-8")
        page, pdf = _printed_html(folder), _pdf_text(folder)
        self.assertIn("Synthetic body line.", page, "the custom prayer itself did not print, so the checks below prove nothing")
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual((receipt.get("service_variant") or {}).get("id"), "principal")
        with self.subTest("variant name"):
            self.assertIn(request["service"]["occasion"], re.search(r'<h1 class="cover-occasion">(.*?)</h1>', html, re.S).group(1))
            self.assertNotIn("Internal Principal Label Quartz", page + pdf)
        with self.subTest("serving today is off"):
            self.assertNotIn("Serving Today", page + pdf)
            self.assertNotIn("Synthetic Reader Marigold", page + pdf)
        with self.subTest("source note"):
            for note in ("Imported Heading Note Quince", "Second Note Pomegranate", "Synthetic Prayer Book"):
                self.assertNotIn(note, page + pdf)

    # ---- F07 -----------------------------------------------------------

    def test_f07_unfilled_bracketed_prayer_placeholder_is_an_open_item(self):
        """A pastor receives a bulletin that prints a bracketed blank such as [Name] with no warning."""
        _configured_profile(self.church, prayers_of_the_people="custom")
        self.edit_profile(sources={"prayers_of_the_people": self.source(
            "pop.md", "# Synthetic Prayers\n\nCelebrant\tWe pray for [Name of the person to remember].\n")})
        result = produce(self.church, self.weekly())
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        bracket = "[Name of the person to remember]"
        self.assertEqual([item["text"] for item in result["open_items"]], [bracket])
        self.assertEqual(result["open_items"][0]["field"], "liturgy.sources.prayers_of_the_people")
        self.assertIn(bracket, json.dumps(result["warnings"]), "the pastor is not warned before approval")
        receipt_path = Path(result["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        approval = {"production_run_id": receipt["run_id"], "approved_by": "Test",
                    "reviewed_artifact_hashes": {i["role"]: i["sha256"] for i in receipt["artifacts"]}}
        refused = finalize(receipt_path, approval)
        self.assertEqual(refused["status"], "blocked")
        self.assertEqual(refused["errors"][0]["code"], "open_items_unconfirmed")
        self.assertIn(bracket, refused["errors"][0]["message"])
        self.assertFalse((self.church / "bulletins" / "bulletin-log.json").exists())
        confirmed = finalize(receipt_path, {**approval, "confirmed_open_items": [bracket]})
        self.assertEqual(confirmed["status"], "approved", confirmed.get("errors"))
        stored = json.loads(Path(confirmed["approval_receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(stored["confirmed_open_items"], [bracket])

    # ---- F08 -----------------------------------------------------------

    def test_f08_correction_works_through_the_church_launcher(self):
        """The correction a pastor's agent runs goes through the launcher, not the interface directly."""
        request = bulletin_input()
        request["announcements"] = [{"title": "Notice", "text": "A wording errror in this announcement."}]
        first = self.produce_ready(request)
        receipt_path = Path(first["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        hashes = {item["role"]: item["sha256"] for item in receipt["artifacts"]}
        approved = finalize(receipt_path, {"production_run_id": receipt["run_id"], "approved_by": "Test",
                                           "reviewed_artifact_hashes": hashes})
        self.assertEqual(approved["status"], "approved", approved)
        changed = self.church / ".handbuilt" / "correction.json"
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text(json.dumps({"announcements": [
            {"title": "Notice", "text": "A wording error in this announcement."}]}), encoding="utf-8")
        result, code = bridge.execute(self.church, "bulletin", "revise",
                                      ["--correct-approved", "--prior-run", str(receipt_path),
                                       "--input", str(changed)])
        self.assertEqual((code, result["status"]), (0, "ready_for_review"), result)

    def test_f08_finalized_bulletin_with_a_wording_error_can_be_corrected(self):
        """A pastor who spots a typo after approval has no supported way to get a corrected, re-approved bulletin."""
        request = bulletin_input()
        request["announcements"] = [{"title": "Notice", "text": "A wording errror in this announcement."}]
        first = self.produce_ready(request)
        receipt_path = Path(first["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        hashes = {item["role"]: item["sha256"] for item in receipt["artifacts"]}
        approved = finalize(receipt_path, {"production_run_id": receipt["run_id"], "approved_by": "Test", "reviewed_artifact_hashes": hashes})
        self.assertEqual(approved["status"], "approved")
        correction = {"announcements": [{"title": "Notice", "text": "A wording error in this announcement."}]}
        by_accident = revise(self.church, receipt_path, correction)
        self.assertEqual(by_accident["errors"][0]["code"], "prior_run_approved")
        self.assertIn("--correct-approved", by_accident["errors"][0]["message"], "the pastor is not told how to correct it")
        fixed = revise(self.church, receipt_path, correction, correct_approved=True)
        self.assertEqual(fixed["status"], "ready_for_review",
                         f"no supported correction after approval: {fixed.get('errors')}")
        new_receipt_path = Path(fixed["receipt_path"])
        new_receipt = json.loads(new_receipt_path.read_text(encoding="utf-8"))
        kept = self.church / new_receipt["corrects_approved"]["receipt_path"]
        self.assertTrue((kept.parent / "bulletin-approval-receipt.json").is_file(), "the approved original was not kept")
        self.assertEqual(json.loads(kept.read_text(encoding="utf-8")), receipt, "the approved receipt was changed")
        for item in receipt["artifacts"]:
            self.assertEqual(hashlib.sha256((kept.parent / Path(item["path"]).name).read_bytes()).hexdigest(), item["sha256"],
                             f"the approved {item['role']} was changed")
        self.assertEqual(new_receipt["revision_of"]["run_id"], receipt["run_id"], "the new receipt does not link the old one")
        self.assertEqual(new_receipt["corrects_approved"]["run_id"], receipt["run_id"])
        log = self.church / "bulletins" / "bulletin-log.json"
        history = json.loads(log.read_text(encoding="utf-8"))
        self.assertEqual(history["2026-09-20"]["templates"]["classic"]["production_run_id"], receipt["run_id"],
                         "the correction counted as final before anyone approved it")
        self.assertFalse((new_receipt_path.parent / "bulletin-approval-receipt.json").exists(),
                         "the correction inherited the old approval")
        again = finalize(new_receipt_path, {"production_run_id": new_receipt["run_id"], "approved_by": "Test",
                                            "reviewed_artifact_hashes": {i["role"]: i["sha256"] for i in new_receipt["artifacts"]}})
        self.assertEqual(again["status"], "approved", again.get("errors"))
        entry = json.loads(log.read_text(encoding="utf-8"))["2026-09-20"]
        self.assertEqual(entry["templates"]["classic"]["production_run_id"], new_receipt["run_id"])
        self.assertEqual(entry["corrects"]["run_id"], receipt["run_id"])

    # ---- F09 -----------------------------------------------------------

    def test_f09_italic_standing_keeps_its_letters_in_every_shipped_typeface(self):
        """A pastor sees or copies 'standing' with a joined s-t ligature that reads as a different word."""
        sys.path.insert(0, str(REPO_ROOT / "skills" / "bulletin" / "renderer"))
        import render_bulletin as renderer
        pdftotext = shutil.which("pdftotext")
        self.assertTrue(pdftotext, "pdftotext is needed for this check")
        brand = json.loads((REPO_ROOT / "scaffold" / "church-folder" / "brand.json").read_text(encoding="utf-8"))
        for template in ("classic", "modern"):
            css = renderer.build_css(template, brand)
            disables = re.search(r"font-variant-ligatures\s*:\s*(none|no-)|font-feature-settings[^;]*[\"']hlig[\"']\s*(0|off)", css)
            for family in ("EB Garamond", "Source Serif 4", "Source Sans 3"):
                with self.subTest(template=template, family=family):
                    html = (f'<html><body><p class="rubric" style="font-family:\'{family}\';font-style:italic">'
                            "The people standing, the Celebrant says</p></body></html>")
                    out = Path(self.temp.name) / f"{template}-{family.replace(' ', '')}.pdf"
                    weasyprint.HTML(string=html).write_pdf(str(out), stylesheets=[weasyprint.CSS(string=css)])
                    text = subprocess.run([pdftotext, str(out), "-"], capture_output=True, text=True).stdout
                    self.assertTrue(disables or re.search(r"\bstanding\b", text),
                                    f"extracted text reads {text.split()!r}")

    # ---- F10 -----------------------------------------------------------

    def test_f10_blocked_operation_run_record_carries_the_error_code_and_no_private_text(self):
        """A support person reading a blocked run's record cannot tell why it stopped."""
        private = "PRIVATE-SENTINEL-ANNOUNCEMENT-TEXT"
        request = bulletin_input()
        request["announcements"] = [{"title": "Private", "text": private}]
        request["options"]["merge_back_page"] = True
        request["hymns"]["closing"]["images"] = ["music/missing-closing.png"]
        input_path = self.church / "weekly-input.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        ready = {"status": "ready", "runtime": {"python": sys.executable}}
        with mock.patch.object(bridge, "_doctor", return_value=ready):
            result, code = bridge.execute(self.church, "bulletin", "produce", ["--input", "weekly-input.json"])
        self.assertNotEqual(code, 0)
        self.assertEqual(result.get("status"), "blocked", result)
        self.assertIn("handbuilt_run", result, "a blocked operation wrote no run record")
        record = Path(result["handbuilt_run"]).read_text(encoding="utf-8")
        self.assertIn("back_page_merge_unsafe", record, "the run record does not say why the operation stopped")
        self.assertNotIn(private, record)


@unittest.skipUnless(HAVE_RUNTIME, "the managed runtime is required")
class FinanceFieldRegressions(unittest.TestCase):
    def test_f11_month_with_expenses_and_no_income_is_not_read_as_a_light_month(self):
        """A council reads 'a bad month' when the bookkeeper simply has not posted the income yet."""
        from tests import test_finance_report as finance
        fixture = finance.fixture
        with tempfile.TemporaryDirectory() as tmp:
            church = fixture.main(Path(tmp) / "riverbend")
            board = church / "finance" / "board"
            real = fixture.month_values

            def unposted_august(y, m):
                income, expenses = real(y, m)
                if (y, m) == (2026, 8):
                    return {k: 0.0 for k in income}, {k: round(v * 0.4, 2) for k, v in expenses.items()}
                return income, expenses

            pulls = board / "2026-08" / "pulls"
            with mock.patch.object(fixture, "month_values", unposted_august):
                (pulls / "balance-sheet.json").write_text(json.dumps(fixture.balance_sheet((2026, 8))))
                (pulls / "pl-ytd.json").write_text(json.dumps(fixture.pl(2026, 8)))
            built, code, err = finance.run(
                church, "build", "--month", "2026-08", "--prepared", "2026-09-10",
                "--balance-sheet", str(pulls / "balance-sheet.json"), "--pl-ytd", str(pulls / "pl-ytd.json"),
                "--pl-prior", str(pulls / "pl-prior.json"))
            if code != 0:
                return  # blocked outright is an acceptable answer
            report = json.loads((board / "2026-08" / "report.json").read_text())
            self.assertTrue(report["this_month"].get("unrecorded"), "the month is not flagged as unrecorded")
            self.assertIn("not yet recorded", report["short_answer"])
            self.assertEqual(finance.run(church, "render", str(board / "2026-08" / "report.json"))[1], 0)
            self.assertIn("not yet recorded", finance.page_text(church, "2026-08"))


class SermonResearchFieldRegressions(unittest.TestCase):
    def test_f12_research_with_several_rule_violations_reports_all_of_them_at_once(self):
        """A pastor fixes one research problem, resubmits, and is told about the next one, over and over."""
        from sermon_workflow import record
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            self.assertEqual(record(church, "2026-09-20", "readings", readings_content(), reading_metadata())["status"], "recorded")
            metadata = research_metadata()
            metadata["sources"][0]["access_result"] = "snippet"
            metadata["sources"][1].pop("author")
            metadata["sources"][2]["url_or_citation"] = ""
            brief = "\n".join(research_brief().splitlines()[:40]) + "\n\n## Questions for reflection\n\nWhat matters?"
            result = record(church, "2026-09-20", "research", brief, metadata)
            self.assertEqual(result["status"], "blocked")
            errors = result["errors"]
            self.assertGreaterEqual(len(errors), 3, f"only {len(errors)} of several violations reported: {[e['code'] for e in errors]}")
            for error in errors:
                self.assertTrue(error.get("message", "").strip())
                self.assertTrue(error.get("field"), f"{error.get('code')} does not say what to fix")


class BrandFieldRegressions(unittest.TestCase):
    def setUp(self):
        from tests.test_build_my_brand import BuildMyBrandTest
        self.helper = BuildMyBrandTest("setUp")
        self.helper.setUp()
        self.addCleanup(self.helper.tearDown)
        self.church = self.helper.church
        import brand_workflow as bw
        self.bw = bw

    def through(self, stage: str) -> None:
        self.helper._record_through(stage)

    def test_f13_dark_color_with_or_without_the_hash_is_accepted_or_the_error_shows_one(self):
        """A pastor types a dark color the way a designer writes it and is told only 'six-digit hex'."""
        self.through("direction")
        marks = dict(primary="brand/staging/marks/mark.svg", small="brand/staging/marks/mark-small.svg")
        with_hash = self.bw.check_marks(self.church, dark="#27384a", **marks)
        self.assertEqual(with_hash["status"], "checked")
        without = self.bw.check_marks(self.church, dark="27384a", **marks)
        self.assertEqual(without["status"], "checked", without.get("errors"))
        report = json.loads((self.church / without["report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["dark"], "#27384a", "the color was not normalized")
        wrong = self.bw.check_marks(self.church, dark="27384", **marks)
        self.assertEqual(wrong["status"], "blocked")
        self.assertIn("#", wrong["errors"][0]["message"], f"the error shows no example with the #: {wrong['errors'][0]['message']!r}")

    def _built(self) -> dict:
        self.through("voice")
        patch = self.helper._stage_files()
        self.assertEqual(self.bw.stage_brand(self.church, patch)["status"], "staged")
        built = self.bw.record(self.church, "build", "Built the system.", {"staged_files": ["brand/staging/marks/mark.svg"]})
        self.assertEqual(built["status"], "recorded", built)
        return built

    def test_f14_small_addition_after_build_does_not_archive_earlier_decisions(self):
        """A pastor who wants one more variation after the build is told to start the whole brand over."""
        from PIL import Image
        from brand_workflow import images
        self._built()
        before = self.bw.orient(self.church)
        receipts = self.church / ".handbuilt" / "build-my-brand" / "receipts"
        receipts_before = {path.name for path in receipts.iterdir()}
        scratch = self.church / ".handbuilt" / "build-my-brand" / "scratch"
        (scratch / "briefs").mkdir(parents=True, exist_ok=True)
        (scratch / "briefs" / "extra.md").write_text("A small extra variation of the chosen mark.\n")
        Image.new("RGB", (64, 64), "white").save(scratch / "extra.png")

        def add_image() -> dict:
            return images.import_images(
                self.church, "extra-1", [".handbuilt/build-my-brand/scratch/extra.png"],
                ".handbuilt/build-my-brand/scratch/briefs/extra.md", tool="Synthetic image tool")

        refused = add_image()
        self.assertEqual(refused["status"], "blocked", "an addition must be asked for explicitly")
        self.assertIn("amendment", refused["errors"][0]["message"], "the refusal does not name the supported path")
        opened = self.bw.record(self.church, "amendment", "One more variation of the chosen mark.", {"step": "open", "what": "One more variation of the mark"})
        self.assertEqual(opened["status"], "recorded", opened)
        result = add_image()
        self.assertEqual(result["status"], "imported", f"no supported path for a small addition: {result.get('errors')}")
        after = self.bw.orient(self.church)
        self.assertEqual(before["stages"], after["stages"], "earlier decisions changed")
        self.assertTrue(after["stages"][0]["recorded"])
        self.assertFalse(list((self.church / "brand" / "archive").glob("run-*")), "earlier decisions were archived")
        self.assertLessEqual(receipts_before, {path.name for path in receipts.iterdir()}, "earlier receipts were lost")
        guide = (self.church / "brand" / "guide.md").read_text(encoding="utf-8")
        self.assertIn("## Amendment 1: One more variation of the mark", guide)
        self.assertIn("**This is an amendment.**", guide)

    def test_f14_amendment_works_through_the_church_launcher(self):
        """The amendment a pastor's agent runs goes through the launcher, not the script directly."""
        self._built()
        content = self.church / ".handbuilt" / "amendment.md"
        content.write_text("One more variation of the chosen mark.\n", encoding="utf-8")
        metadata = self.church / ".handbuilt" / "amendment.json"
        metadata.write_text(json.dumps({"step": "open", "what": "One more variation of the mark"}), encoding="utf-8")
        result, code = bridge.execute(self.church, "build-my-brand", "record",
                                      ["--stage", "amendment", "--content-file", str(content),
                                       "--metadata-file", str(metadata)])
        self.assertEqual((code, result["status"]), (0, "recorded"), result)

    def test_f14_an_amendment_after_approval_needs_fresh_approval(self):
        """An addition to an approved brand must not go live, or stay unapproved, without the pastor knowing."""
        self.helper._ready_to_approve()
        self.assertEqual(self.bw.approve(self.church, approved_by="The Rev. Test Pastor")["status"], "approved")
        live = self.church / "brand" / "marks"
        addition = "brand/staging/marks/mark-youth.svg"
        opened = self.bw.record(self.church, "amendment", "A youth lockup.", {"step": "open", "what": "A youth lockup"})
        self.assertEqual(opened["status"], "recorded", opened)
        (self.church / addition).write_text((live / "mark.svg").read_text())
        self.assertEqual(self.bw.approve(self.church)["errors"][0]["code"], "amendment_open")
        finished = self.bw.record(self.church, "amendment", "The pastor kept the lockup.", {"step": "finish", "added": [addition]})
        self.assertEqual(finished["status"], "recorded", finished)
        self.assertTrue(finished["needs_approval"])
        self.assertFalse((live / "mark-youth.svg").exists(), "the live brand changed before fresh approval")
        waiting = self.bw.orient(self.church)
        self.assertEqual(waiting["amendments_awaiting_approval"], [1])
        self.assertIn("fresh approval", waiting["next_action"])
        self.assertIn("Waiting for fresh approval", (self.church / "brand" / "guide.md").read_text(encoding="utf-8"))
        listing = self.bw.approve(self.church, dry_run=True)
        self.assertEqual(listing["status"], "ready_to_approve", listing)
        self.assertEqual(listing["amendments"][0]["added"], [addition])
        self.assertEqual(self.bw.approve(self.church, approved_by="The Rev. Test Pastor")["status"], "approved")
        self.assertTrue((live / "mark-youth.svg").is_file(), "the addition did not go in at approval")
        self.assertEqual(self.bw.orient(self.church)["amendments_awaiting_approval"], [])
        self.assertIn("Approved by the pastor", (self.church / "brand" / "guide.md").read_text(encoding="utf-8"))
        self.assertTrue(json.loads((self.church / "brand.json").read_text())["brand_system"]["marks"]["primary"].startswith("brand/marks/"))

    def test_f15_interview_answers_stay_out_of_a_document_for_the_governing_body(self):
        """A pastor shares the brand document with the vestry and it repeats private interview answers."""
        from brand_workflow import IMPLEMENTATION_VERSION
        from tests.test_build_my_brand import _metadata
        interview = "PRIVATE-INTERVIEW-SENTINEL-Wombat"
        brief = "PRIVATE-BRIEF-SENTINEL-Quokka"
        chat = "CHAT-QUOTE-SENTINEL-Numbat"
        rationale = "CHAT-RATIONALE-SENTINEL-Dingo"
        note = "INTERNAL-NOTE-SENTINEL-Bilby"
        leaders_reason = "One identity keeps every ministry recognizable as part of this church."
        for stage in self.bw.STAGES:
            metadata = _metadata(stage)
            content = f"Lesson text for {stage}. The pastor said: {chat}."
            if stage == "interview":
                metadata["answers"]["prompt"] = f"We want this because {interview}."
                content = f"# Brief\n\nThe pastor said: {interview}. {brief}.\n"
            if stage in self.bw.DECISION_STAGES:
                metadata["rationale"] = f"The pastor said {rationale}."
                metadata["handoff"] = f"Senior designer next. {note}"
            if stage == "identity":
                metadata["reason_for_leaders"] = leaders_reason
            self.assertEqual(self.bw.record(self.church, stage, content, metadata)["status"], "recorded", stage)
            if stage == "direction":
                break
        self.assertEqual(self.bw.redirect(self.church, "sketches-1", f"Too generic. {note}")["status"], "redirected")
        self.assertEqual(self.bw.book(self.church)["status"], "written")
        pattern = re.compile(r"vestry|council|governing|board|trustees|leadership team", re.I)
        candidates = [path for path in (self.church / "brand").rglob("*")
                      if path.is_file() and path.suffix in {".md", ".html", ".txt"}
                      and (pattern.search(path.name) or pattern.search("\n".join(path.read_text(errors="ignore").splitlines()[:30])))]
        if not candidates:
            self.fail("No document intended for the governing body exists; the only generated documents (guide, brand book, "
                      "brief) are written for the pastor and carry the interview answers.")
        for path in candidates:
            text = path.read_text(errors="ignore")
            for planted in (interview, brief, chat, rationale, note):
                self.assertNotIn(planted, text, path.name)
        edition = (self.church / "brand" / "governing-body-edition.md").read_text(encoding="utf-8")
        self.assertIn("identity choice", edition, "the edition does not carry the decisions")
        self.assertIn(leaders_reason, edition, "the edition does not carry the reasoning")
        for detail in (IMPLEMENTATION_VERSION, "Handbuilt", "plugin", "receipt", "recorded_at", ".handbuilt", "<!--", "2026-"):
            self.assertNotIn(detail, edition, f"run detail in the edition: {detail}")
        # The working guide keeps everything and says it is the pastor's own.
        guide = (self.church / "brand" / "guide.md").read_text(encoding="utf-8")
        self.assertIn(interview, guide)
        self.assertIn("**Your own working record.**", guide)
        # Quoted words cannot be written into the field the edition reads.
        quoted = _metadata("develop")
        quoted["reason_for_leaders"] = 'The pastor said "we love it".'
        self.assertEqual(self.bw.record(self.church, "develop", "Lesson.", quoted)["errors"][0]["code"], "not_for_sharing")
        lifted = _metadata("develop")
        lifted["reason_for_leaders"] = f"It works. We want this because {interview}."
        self.assertEqual(self.bw.record(self.church, "develop", "Lesson.", lifted)["errors"][0]["code"], "not_for_sharing")

    def test_f17_a_decision_that_quotes_the_pastor_still_reaches_the_vestry(self):
        """The edition read 'Left out of this edition' where the brand's central idea belonged."""
        from tests.test_build_my_brand import _metadata
        self.through("direction")
        quoted = _metadata("develop")
        quoted["decision"] = 'Calm and plain, "letters you can read from the road".'
        refused = self.bw.record(self.church, "develop", "Lesson.", quoted)
        self.assertEqual(refused["errors"][0]["code"], "decision_for_leaders_required")
        quoted["decision_for_leaders"] = 'Calm, plain lettering, "readable" from the road.'
        self.assertEqual(self.bw.record(self.church, "develop", "Lesson.", quoted)["errors"][0]["code"], "not_for_sharing")
        quoted["decision_for_leaders"] = "Calm, plain lettering that can be read from a passing car."
        self.assertEqual(self.bw.record(self.church, "develop", "Lesson.", quoted)["status"], "recorded")
        edition = (self.church / "brand" / "governing-body-edition.md").read_text(encoding="utf-8")
        self.assertIn("Calm, plain lettering that can be read from a passing car.", edition)
        self.assertNotIn("Left out of this edition", edition)
        guide = (self.church / "brand" / "guide.md").read_text(encoding="utf-8")
        self.assertIn("letters you can read from the road", guide, "the pastor's own record keeps their words")

    def test_f16_a_choice_the_pastor_has_not_made_is_not_shown_as_decided(self):
        """A pastor reads 'Decision' in the guide beside an option nobody had yet chosen."""
        from tests.test_build_my_brand import _metadata
        self.through("direction")
        metadata = {"options": ["Option A", "Option B"], "recommendation": "Option A, because it suits the sign.",
                    "follows": "The direction pick.", "speaker": "creative director",
                    "applications": ["bulletin_cover", "test_announcement", "social_post", "sign", "social_avatar"],
                    "boards": ["brand/staging/explorations/board.png"]}
        # Nobody can leave it unsaid, and a filled-in decision cannot pose as a proposal.
        unmarked = self.bw.record(self.church, "develop", "A proposal shown to the pastor.", {**metadata, "decision": "Option A", "rationale": "It suits."})
        self.assertEqual(unmarked["errors"][0]["code"], "standing_required")
        self.assertNotIn("<!-- stage:develop -->", (self.church / "brand" / "guide.md").read_text(encoding="utf-8"), "a refused record still left text in the guide")
        posing = self.bw.record(self.church, "develop", "A proposal.", {**metadata, "standing": "proposed", "decision": "Option A"})
        self.assertEqual(posing["errors"][0]["code"], "proposal_has_decision")
        result = self.bw.record(self.church, "develop", "A proposal shown to the pastor.", {**metadata, "standing": "proposed"})
        self.assertEqual(result["status"], "recorded", result)
        guide = (self.church / "brand" / "guide.md").read_text(encoding="utf-8")
        develop = guide[guide.find("<!-- stage:develop -->"):]
        self.assertNotIn("**Decision:**", develop, "a proposal with no pastor choice is shown as a decision")
        self.assertIn("**Proposed by the studio, not yet decided:** Option A, because it suits the sign.", develop)
        decided_part, proposed_part = guide[:guide.find("<!-- /standing -->")].split("### Proposed by the studio, not yet decided")
        self.assertIn("Your direction: direction choice", decided_part)
        self.assertNotIn("Option A, because", decided_part)
        self.assertIn("Your direction, developed: Option A, because", proposed_part)
        edition = (self.church / "brand" / "governing-body-edition.md").read_text(encoding="utf-8")
        decided_part, proposed_part = edition.split("## Proposed by the studio, not yet decided")
        self.assertIn("## Decided by the pastor", decided_part)
        self.assertIn("direction choice", decided_part)
        self.assertNotIn("Option A, because", decided_part)
        self.assertIn("Option A, because", proposed_part)
        state = self.bw.orient(self.church)
        self.assertEqual([p["stage"] for p in state["open_proposals"]], ["develop"])
        self.assertTrue(any("not decided" in warning for warning in state["warnings"]))
        # Work can continue past an open proposal, but approval lists it and refuses.
        for stage in ("refine-1", "refine-2", "color", "type", "voice"):
            self.assertEqual(self.bw.record(self.church, stage, "Lesson.", _metadata(stage))["status"], "recorded", stage)
        self.assertEqual(self.bw.stage_brand(self.church, self.helper._stage_files())["status"], "staged")
        self.assertEqual(self.bw.record(self.church, "build", "Built.", {"staged_files": ["brand/staging/marks/mark.svg"]})["status"], "recorded")
        (self.church / "before.pdf").write_bytes(b"%PDF-1.4 before")
        (self.church / "after.pdf").write_bytes(b"%PDF-1.4 after")
        (self.church / "announcement.pdf").write_bytes(b"%PDF-1.4 announcement")
        self.assertEqual(self.bw.record(self.church, "prove", "Proof.", {"before": "before.pdf", "after": "after.pdf", "announcement": "announcement.pdf"})["status"], "recorded")
        for dry_run in (True, False):
            refused = self.bw.approve(self.church, dry_run=dry_run)
            self.assertEqual(refused["errors"][0]["code"], "open_proposals", refused)
            self.assertIn("Your direction, developed", refused["errors"][0]["message"])
            self.assertEqual(refused["errors"][0]["detail"]["open_proposals"][0]["stage"], "develop")
        self.assertFalse((self.church / "brand" / "marks").exists(), "a refused approval changed the live brand")
        # The pastor says yes to the proposal as it stood: later work stays good.
        decided = self.bw.record(self.church, "develop", "The pastor chose it.",
                                 {**metadata, "standing": "decided", "decision": "Option A", "rationale": "It suits the sign.", "accepts_proposal": True}, replace=True)
        self.assertEqual(decided["status"], "recorded", decided)
        state = self.bw.orient(self.church)
        self.assertEqual(state["open_proposals"], [])
        self.assertFalse([stage["stage"] for stage in state["stages"] if stage["stale"]], "accepting a proposal should not undo later work")
        self.assertIn("**Decided by:** the pastor", (self.church / "brand" / "guide.md").read_text(encoding="utf-8"))
        self.assertEqual(self.bw.approve(self.church)["status"], "approved")

    def test_f16_a_run_recorded_before_the_marking_still_loads_and_says_so(self):
        """A pastor mid-run updates the plugin; earlier records have no marking and must not break or be relabeled."""
        self.helper._ready_to_approve()
        path = self.church / ".handbuilt" / "build-my-brand" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        for entry in state["stages"].values():
            entry.pop("standing", None)
        path.write_text(json.dumps(state), encoding="utf-8")
        oriented = self.bw.orient(self.church)
        self.assertEqual(oriented["status"], "ok")
        self.assertEqual(oriented["open_proposals"], [])
        self.assertIn("identity", oriented["unmarked_decisions"])
        self.assertTrue(any("kept as recorded" in warning for warning in oriented["warnings"]), oriented["warnings"])
        self.assertEqual(next(s for s in oriented["stages"] if s["stage"] == "identity")["decision"], "identity choice")
        self.assertEqual(self.bw.book(self.church)["status"], "written")
        for name in ("guide.md", "governing-body-edition.md"):
            text = (self.church / "brand" / name).read_text(encoding="utf-8")
            self.assertIn("Recorded before decisions and proposals were marked apart", text, name)
        approved = self.bw.approve(self.church)
        self.assertEqual(approved["status"], "approved", approved)
        self.assertTrue(any("kept as recorded" in warning for warning in approved["warnings"]))

    def test_f18_absolute_path_inside_the_church_folder_is_accepted_or_the_fix_is_shown(self):
        """A pastor pastes a full file path and is told only that it must be relative."""
        absolute = str(self.church / "brand" / "staging" / "explorations" / "board.png")
        from tests.test_build_my_brand import _metadata
        # Walk to the direction stage, then record it with an absolute board path.
        self.helper._record_through("identity")
        metadata = _metadata("direction")
        metadata["boards"] = [absolute]
        result = self.bw.record(self.church, "direction", "Directions.", metadata)
        self.assertEqual(result["status"], "recorded", result.get("errors"))
        recorded = json.loads((self.church / ".handbuilt" / "build-my-brand" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["stages"]["direction"]["boards"], ["brand/staging/explorations/board.png"], "the path was not normalized")
        outside = self.church.parent / "elsewhere.png"
        outside.write_bytes(b"x")
        metadata["boards"] = [str(outside)]
        refused = self.bw.record(self.church, "direction", "Directions.", metadata, replace=True)
        self.assertEqual(refused["status"], "blocked")
        self.assertEqual(refused["errors"][0]["code"], "invalid_path")
        self.assertIn("inside the church folder", refused["errors"][0]["message"])
        metadata["boards"] = [str(self.church / "brand" / ".." / ".." / "elsewhere.png")]
        self.assertEqual(self.bw.record(self.church, "direction", "Directions.", metadata, replace=True)["errors"][0]["code"], "invalid_path")


class WorkspaceFieldRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.church = make_church(self.base)

    def test_f17_pastors_custom_instructions_survive_reconnect_and_update_byte_for_byte(self):
        """A pastor's own rules in the church folder's CLAUDE.md are changed or lost by a reconnect or an update."""
        custom = "\n## My own rules\n\nAlways greet the sexton first.  \tTrailing tab kept.\né café\n".encode("utf-8")
        for name in ("CLAUDE.md", "AGENTS.md"):
            path = self.church / name
            path.write_bytes(path.read_bytes() + custom)
        expected = {name: (self.church / name).read_bytes() for name in ("CLAUDE.md", "AGENTS.md")}
        setup = bridge._load_setup()
        steps = {
            "connect": lambda: bridge.connect(self.church),
            "reconnect, stable": lambda: bridge.connect(self.church, update_policy="stable"),
            "return to the folder": lambda: setup.create(self.base, "public-test-parish"),
            "standing update": lambda: setup.update(self.church, {"bulletin": {"include_serving_today": False}}, scope="standing"),
        }
        for label, step in steps.items():
            with self.subTest(step=label):
                step()
                for name, original in expected.items():
                    self.assertEqual((self.church / name).read_bytes(), original, f"{name} changed after {label}")
        with mock.patch.object(bridge, "_doctor", return_value={"status": "ready", "runtime": {"python": sys.executable}}):
            bridge._start(self.church, "onboarding", skip_update=True)
        for name, original in expected.items():
            self.assertEqual((self.church / name).read_bytes(), original, f"{name} changed after workflow start")


class UpdateFieldRegressions(unittest.TestCase):
    def test_f19_stale_release_record_without_assets_does_not_report_current(self):
        """A pastor is told the church is up to date for a day after a newer release exists."""
        from tests.test_workflow_updates import install_fixture, release_bytes
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            current = install_fixture(base / "host", "0.5.0")
            store = base / "managed"
            store.mkdir()
            (store / "latest-check.json").write_text(json.dumps({
                "checked_at": 100000,
                "latest": {"name": "handbuilt-church-labs", "version": "0.5.0", "tag": "v0.5.0", "assets": {},
                           "url": f"https://github.com/{updates.REPOSITORY}/releases/tag/v0.5.0"}}))
            archive = release_bytes("0.6.0")
            digest = hashlib.sha256(archive).hexdigest()
            urls = {name: f"https://github.com/{updates.REPOSITORY}/releases/download/v0.6.0/{name}"
                    for name in (updates.PACKAGE, updates.CHECKSUM)}
            metadata = {"tag_name": "v0.6.0", "draft": False, "prerelease": False,
                        "assets": [{"name": name, "browser_download_url": url} for name, url in urls.items()]}
            calls = []

            def download(url, limit):
                calls.append(url)
                if url == updates.LATEST_URL:
                    return json.dumps(metadata).encode()
                if url == urls[updates.CHECKSUM]:
                    return (digest + "  " + updates.PACKAGE).encode()
                if url == urls[updates.PACKAGE]:
                    return archive
                raise AssertionError(url)

            ordinary = updates.select_release(current, store, lambda root: None, download=download, now=lambda: 100010)
            self.assertFalse(ordinary["status"] == "current" and ordinary["freshness"] == "cached",
                             "reported current from an incomplete cached record when a live check was possible")
            forced = updates.select_release(current, store, lambda root: None, download=download, now=lambda: 100020, force=True)
            self.assertEqual(forced["status"], "updated")
            self.assertEqual(forced["latest"]["version"], "0.6.0")
            self.assertTrue(calls, "an incomplete cached record did not trigger a live check")

            # With the live check unavailable, an incomplete record must say deferred, never current.
            (store / "latest-check.json").write_text(json.dumps({
                "checked_at": 100000,
                "latest": {"name": "handbuilt-church-labs", "version": "0.5.0", "tag": "v0.5.0", "assets": {},
                           "url": f"https://github.com/{updates.REPOSITORY}/releases/tag/v0.5.0"}}))

            def offline(url, limit):
                raise OSError("offline")

            down = updates.select_release(current, store, lambda root: None, download=offline, now=lambda: 100030)
            self.assertEqual(down["status"], "deferred", down)
            self.assertNotEqual(down["status"], "current")

            # The launcher's own update command reads the same state and must not report current either.
            import time
            launcher_store = base / "launcher" / "workflows"
            launcher_store.mkdir(parents=True)
            (launcher_store / "latest-check.json").write_text(json.dumps({
                "checked_at": time.time(),
                "latest": {"name": "handbuilt-church-labs", "version": updates.package_version(bridge.ROOT),
                           "tag": "v" + updates.package_version(bridge.ROOT), "assets": {},
                           "url": f"https://github.com/{updates.REPOSITORY}/releases/tag/v{updates.package_version(bridge.ROOT)}"}}))
            church = base / "church"
            church.mkdir()
            real_select = updates.select_release
            with mock.patch.object(updates, "select_release",
                                   lambda *a, **k: real_select(*a, download=offline, **k)), \
                 mock.patch("tools.plugin_identity.is_development_root", return_value=False), \
                 mock.patch("tools.workflow_updates.is_development_root", return_value=False), \
                 mock.patch("tools.handbuilt_runtime.default_runtime_root", return_value=base / "launcher" / "runtime"), \
                 mock.patch.object(bridge, "connect", return_value={"installation": {}}):
                result, code = bridge._ensure_latest(church)
            self.assertEqual(result["updates"]["status"], "deferred", result)
            self.assertNotEqual(code, 0)


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class ImportFieldRegressions(unittest.TestCase):
    def test_f20_oversized_embedded_image_fails_cleanly_and_does_not_block_production(self):
        """A pastor's failed bulletin import leaves a half-made folder that blocks every later bulletin."""
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
        from skills.onboarding.bulletin_import import BulletinImportError, import_bulletin
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            church = make_church(base)
            pdf = base / "supplied.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)
            image = DecodedStreamObject()
            image.set_data(b"\x00")
            image[NameObject("/Type")] = NameObject("/XObject")
            image[NameObject("/Subtype")] = NameObject("/Image")
            image[NameObject("/Width")] = NumberObject(5001)
            image[NameObject("/Height")] = NumberObject(5000)
            image[NameObject("/BitsPerComponent")] = NumberObject(1)
            image[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
            image_ref = writer._add_object(image)
            content = DecodedStreamObject()
            content.set_data(b"q /Im0 Do Q")
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})})
            page[NameObject("/Contents")] = writer._add_object(content)
            with pdf.open("wb") as handle:
                writer.write(handle)
            with self.assertRaises(BulletinImportError):
                import_bulletin(church, pdf)
            leftovers = [p for p in (church / "onboarding" / "imports").glob("*") if not (p / "manifest.json").is_file()]
            self.assertEqual(leftovers, [], "a failed import left a partial import folder behind")
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "ready_for_review", result.get("errors"))


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class LectionaryTrackFieldRegressions(unittest.TestCase):
    def test_f21_bulletin_and_sermon_research_use_the_same_track_for_one_date(self):
        """A pastor hand-edits the track, and the sermon brief follows it while the bulletin prints the old one."""
        from sermon_workflow import record
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config = church / "church.yaml"
            config.write_text(config.read_text().replace("track: Track 2", "track: Track 1"), encoding="utf-8")
            selection = reading_selection()
            selection["track"] = "Track 1"
            sermon = record(church, "2026-09-20", "readings", readings_content(selection=selection), reading_metadata(selection))
            self.assertEqual(sermon["status"], "recorded", sermon)
            bulletin = bulletin_input()  # carries the old track
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked",
                             "the bulletin printed a different track than the church's setting and the sermon research, with no warning")
            error = result["errors"][0]
            self.assertEqual(error["code"], "lectionary_track_mismatch")
            self.assertEqual(error["field"], "service.lectionary_track")
            self.assertIn("Track 1", error["message"])
            self.assertIn("Track 2", error["message"])
            bulletin["service"]["lectionary_track"] = "track 1"
            self.assertEqual(produce(church, bulletin)["status"], "ready_for_review")


if __name__ == "__main__":
    unittest.main()
