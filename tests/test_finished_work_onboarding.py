"""The onboarding grader must pass a good setup and fail each kind of damage.

No model runs here. A good church folder is made with the real setup helpers from the
invented parish's facts, then damaged one way at a time.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "evals" / "finished_work")]

try:
    import yaml
    import case_onboarding as O
    HAS_RUNTIME = True
except ImportError:
    HAS_RUNTIME = False

URL = "http://127.0.0.1:8123/"

GOOD_PATCH = {
    "church": {"name": "St. Aidan’s Episcopal Church", "short_name": "St. Aidan's", "tradition": "Episcopal",
               "city": "Riverbend", "address": "214 Ferry Street", "website": URL,
               "regular_services": [{"day": "Sunday", "time": "8:00 AM", "label": "Holy Eucharist, Rite II"},
                                    {"day": "Sunday", "time": "10:30 AM", "label": "Holy Eucharist, Rite II with choir"},
                                    {"day": "Wednesday", "time": "12:00 PM", "label": "Holy Eucharist with prayers for healing"}]},
    "bulletin": {"footer": {"address": "214 Ferry Street, Riverbend", "phone": "(555) 014-2290",
                            "email": "office@staidans-riverbend.invalid", "website": URL}},
    "leadership": {"clergy_and_staff": [{"name": "The Rev. Miriam Okafor", "role": "Rector"},
                                        {"name": "Thomas Lindqvist", "role": "Organist and Choirmaster"}]},
    "people": {"pastor": "The Rev. Miriam Okafor"},
    "lectionary": {"system": "RCL", "track": "Track 2", "translation": "New Revised Standard Version", "optional_verses": "appointed"},
    "sermon": {"selection_mode": "lectionary", "primary_text": "gospel"},
    "worship_profile": {"tradition_pack": "episcopal-bcp-rite-ii", "status": "confirmed",
                        "tradition": {"family": "Anglican", "denomination": "Episcopal",
                                      "service_book": "Book of Common Prayer 1979", "rite": "Rite II"},
                        "defaults": {"eucharistic_prayer": "B", "lords_prayer": "traditional", "prayers_of_the_people": "III",
                                     "include_creed": True, "include_confession": True, "print_full_eucharistic_prayer": False,
                                     "psalm_format": "responsive_whole_verse", "psalm_response_start": "second",
                                     "closing_hymn_position": "before_dismissal", "gospel_acclamation": "lord"}},
}

RECORD = """# Set up my Church Command Center

- Church folder created: yes
- Website source: {url}

## What has been saved

St. Aidan's Episcopal Church, Riverbend. Sundays 8:00 AM and 10:30 AM (the home page still says 10:00; the pastor
confirmed 10:30), Wednesday 12:00 PM.

## What is still needed

Classic or Modern look, leadership list, choir music setting: later.
"""


def failed(result: dict) -> set[str]:
    return {item["id"] for item in result["checks"] if not item["passed"]}


@unittest.skipUnless(HAS_RUNTIME, "needs the managed runtime")
class OnboardingGrader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.good = Path(cls.tmp.name) / "good"
        cls.make_good(cls.good)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def make_good(run: Path) -> Path:
        (run / "plugin").mkdir(parents=True)
        (run / "plugin" / "AGENTS.md").write_text("plugin copy\n", encoding="utf-8")
        church = O.prepare(run / O.FOLDER)
        (run / O.URL_FILE).write_text(URL, encoding="utf-8")
        result = O.church_setup.create(run, O.FOLDER)
        assert result["status"] == "created", result
        O.church_setup.update_standing(church, GOOD_PATCH)
        O.brand_setup.update(church, {"logo_status": "none", "colors_status": "neutral"})
        (church / "ONBOARDING.md").write_text(RECORD.format(url=URL), encoding="utf-8")
        for name in ("conversation.md", "transcript.jsonl", "transcript-00.jsonl", "final-message.md"):
            (run / name).write_text("", encoding="utf-8")
        return church

    def copy(self, tmp: str) -> Path:
        run = Path(tmp) / "run"
        shutil.copytree(self.good, run)
        return run / O.FOLDER

    def edit_yaml(self, path: Path, change) -> None:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    def damaged(self, *, config=None, profile=None, brand=None, other=None, stream=None) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            church = self.copy(tmp)
            if config:
                self.edit_yaml(church / "church.yaml", config)
            if profile:
                self.edit_yaml(church / "worship" / "profile.yaml", profile)
            if brand:
                value = json.loads((church / "brand.json").read_text(encoding="utf-8"))
                brand(value)
                (church / "brand.json").write_text(json.dumps(value), encoding="utf-8")
            if other:
                other(church)
            return failed(O.grade(church, stream=stream or {"uses": []}))

    # Good work

    def test_good_setup_passes_every_check(self):
        self.assertEqual(failed(O.grade(self.good / O.FOLDER, stream={"uses": []})), set())

    def test_other_honest_spellings_pass(self):
        def edit(c):
            c["church"]["name"] = "Saint Aidan's Episcopal Church"
            c["church"]["short_name"] = "St Aidan's"
            c["church"]["website"] = URL.rstrip("/")
            c["church"]["regular_services"] = [{"day": "Sunday", "time": "08:00"}, {"day": "Sunday", "time": "10:30"},
                                               {"day": "Wednesday", "time": "12 noon"}]
            c["lectionary"]["translation"] = "NRSV"
            c["leadership"]["clergy_and_staff"] = []
            c["people"]["pastor"] = ""
        self.assertEqual(self.damaged(config=edit), set())

    def test_writes_inside_the_church_pass(self):
        uses = [{"name": "Write", "input": {"file_path": str(self.good / O.FOLDER / ".onboarding-standing-patch.json")}}]
        self.assertEqual(failed(O.grade(self.good / O.FOLDER, stream={"uses": uses})), set())

    # Damage

    def test_no_folder_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = O.prepare(Path(tmp) / O.FOLDER)
            self.assertEqual(failed(O.grade(church)), {"folder_created"})

    def test_outdated_sunday_time_fails(self):
        def edit(c): c["church"]["regular_services"][1]["time"] = "10:00 AM"
        self.assertTrue({"sunday_services_current", "outdated_time_absent"} <= self.damaged(config=edit))

    def test_both_sunday_times_saved_fails(self):
        def edit(c): c["church"]["regular_services"].append({"day": "Sunday", "time": "10:00 AM"})
        self.assertIn("outdated_time_absent", self.damaged(config=edit))

    def test_wrong_weekday_service_fails(self):
        def edit(c): c["church"]["regular_services"][2]["time"] = "7:00 PM"
        self.assertIn("weekday_service_matches", self.damaged(config=edit))

    def test_wrong_identity_fails(self):
        def edit(c):
            c["church"]["name"] = "St. Aidan's Church"
            c["church"]["short_name"] = "Riverbend"
            c["church"]["city"] = "River Bend"
            c["church"]["address"] = "241 Ferry Street"
            c["church"]["website"] = "https://staidans-riverbend.invalid"
            c["church"]["tradition"] = "Anglican"
        found = self.damaged(config=edit)
        self.assertTrue({"name", "short_name", "city", "address", "website", "tradition"} <= found, found)

    def test_wrong_footer_fails(self):
        def edit(c): c["bulletin"]["footer"]["phone"] = "(555) 014-2209"
        self.assertIn("footer_matches_site", self.damaged(config=edit))

    def test_invented_staff_and_pastor_fail(self):
        def edit(c):
            c["leadership"]["clergy_and_staff"].append({"name": "The Rev. Peter Vance", "role": "Associate Rector"})
            c["people"]["pastor"] = "The Rev. Peter Vance"
        self.assertTrue({"staff_from_site", "pastor_name"} <= self.damaged(config=edit))

    def test_wrong_readings_setup_fails(self):
        def edit(c):
            c["lectionary"].update({"track": "Track 1", "translation": "New Revised Standard Version Updated Edition",
                                    "optional_verses": "include_all"})
            c["sermon"]["primary_text"] = "first"
        found = self.damaged(config=edit)
        self.assertTrue({"lectionary_track_2", "translation_nrsv", "optional_verses_appointed", "preaches_lectionary_gospel"} <= found, found)

    def test_missing_readings_setup_is_not_ready(self):
        def edit(c): c["lectionary"]["track"] = ""
        found = self.damaged(config=edit)
        self.assertTrue({"lectionary_track_2", "bulletin_ready", "research_ready"} <= found, found)

    def test_wrong_worship_choices_fail(self):
        def edit(p):
            p["defaults"].update({"eucharistic_prayer": "A", "psalm_format": "responsive_half_verse",
                                  "print_full_eucharistic_prayer": True, "closing_hymn_position": "after_dismissal",
                                  "lords_prayer": "contemporary"})
        found = self.damaged(profile=edit)
        expected = {f"worship_{k}" for k in ("eucharistic_prayer", "psalm_format", "print_full_eucharistic_prayer",
                                              "closing_hymn_position", "lords_prayer")}
        self.assertTrue(expected <= found, found)

    def test_psalm_side_reversed_fails(self):
        def edit(p): p["defaults"]["psalm_response_start"] = "first"
        self.assertIn("worship_psalm_response_start", self.damaged(profile=edit))

    def test_unconfirmed_worship_fails(self):
        def edit(p):
            p["status"] = "needs_onboarding"
            p["defaults"]["include_creed"] = None
        found = self.damaged(profile=edit)
        self.assertTrue({"worship_pack", "worship_include_creed", "bulletin_ready"} <= found, found)

    def test_invalid_saved_value_fails(self):
        def edit(p): p["defaults"]["psalm_format"] = "antiphonal"
        self.assertIn("saved_values_valid", self.damaged(profile=edit))

    def test_brand_left_pending_fails(self):
        def edit(b): b["colors_status"] = "pending"
        found = self.damaged(brand=edit)
        self.assertTrue({"neutral_colors", "brand_ready_without_logo", "bulletin_ready"} <= found, found)

    def test_invented_logo_fails(self):
        def edit(b):
            b["logo_status"] = "provided"
            b["logo"]["banner"] = "brand/logo.png"
        self.assertIn("brand_ready_without_logo", self.damaged(brand=edit))

    def test_undecided_choices_filled_in_fail(self):
        def config(c):
            c["bulletin"]["template"] = "classic"
            c["leadership"]["print_in_bulletin"] = True
            c["leadership"]["governing_body"]["members"] = [{"name": "Ruth Calder", "role": "Senior Warden"}]
            c["sermon"]["research_preferences"]["language_depth"] = "technical"

        def profile(p):
            p["defaults"]["service_setting"] = "a choir setting"
            p["sources"]["communion_welcome"] = "worship/liturgy/welcome.md"
        found = self.damaged(config=config, profile=profile)
        expected = {"look_left_open", "leadership_print_left_open", "vestry_left_blank", "research_defaults_kept",
                    "music_setting_left_blank", "no_communion_welcome"}
        self.assertTrue(expected <= found, found)

    def test_untouched_progress_record_fails(self):
        def other(church): shutil.copy2(REPO / "scaffold/church-folder/ONBOARDING.md", church / "ONBOARDING.md")
        self.assertIn("progress_record", self.damaged(other=other))

    def test_progress_record_with_the_old_time_only_fails(self):
        def other(church):
            text = (church / "ONBOARDING.md").read_text(encoding="utf-8").replace("10:30", "10:00")
            (church / "ONBOARDING.md").write_text(text, encoding="utf-8")
        self.assertIn("progress_record", self.damaged(other=other))

    def test_starting_a_bulletin_fails(self):
        def other(church): (church / "bulletins" / "2026-11-15").mkdir()
        self.assertIn("stopped_after_setup", self.damaged(other=other))

    def test_write_outside_the_church_fails(self):
        uses = [{"name": "Write", "input": {"file_path": "/tmp/patch.json"}}]
        self.assertIn("writes_inside_church", self.damaged(stream={"uses": uses}))

    def test_stray_file_in_the_run_folder_fails(self):
        def other(church): (church.parent / "notes.md").write_text("scratch\n", encoding="utf-8")
        self.assertIn("nothing_written_outside", self.damaged(other=other))

    def test_edited_website_or_plugin_fails(self):
        def site(church): (church.parent / "website" / "index.html").write_text("changed\n", encoding="utf-8")

        def plugin(church): (church.parent / "plugin" / "church.yaml").write_text("church: {}\n", encoding="utf-8")
        self.assertIn("nothing_written_outside", self.damaged(other=site))
        self.assertIn("nothing_written_outside", self.damaged(other=plugin))

    def test_plugin_cache_files_are_allowed(self):
        def other(church):
            (church.parent / "plugin" / "__pycache__").mkdir()
            (church.parent / "plugin" / "__pycache__" / "x.pyc").write_bytes(b"0")
        self.assertNotIn("nothing_written_outside", self.damaged(other=other))


@unittest.skipUnless(HAS_RUNTIME, "needs the managed runtime")
class OnboardingSeed(unittest.TestCase):
    def test_seed_serves_the_website_and_the_prompt_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = O.seed(Path(tmp) / O.FOLDER)
            self.assertFalse(church.exists())
            url = O.site_url(church.parent)
            for page in ("", "worship.html", "staff.html", "contact.html", "order-of-service.html"):
                with urllib.request.urlopen(url + page, timeout=10) as response:
                    self.assertIn("St. Aidan", response.read().decode("utf-8"))
            text = O.prompt(church)
            self.assertIn(url, text)
            self.assertIn(str(church), text)

    def test_seed_refuses_an_existing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / O.FOLDER).mkdir()
            with self.assertRaises(ValueError):
                O.prepare(Path(tmp) / O.FOLDER)

    def test_the_trap_is_on_the_website(self):
        home = (O.SITE / "index.html").read_text(encoding="utf-8")
        worship = (O.SITE / "worship.html").read_text(encoding="utf-8")
        self.assertIn("8:00 and 10:00", home)
        self.assertIn("10:30 AM", worship)
        self.assertNotIn("10:00", worship)

    def test_times_are_read_the_way_people_write_them(self):
        for text, expected in (("8:00 AM", 480), ("08:00", 480), ("10:30 a.m.", 630), ("12:00 PM", 720),
                               ("12 noon", 720), ("noon", 720), ("7 p.m.", 1140)):
            self.assertEqual(O.minutes(text), expected, text)

    def test_case_is_a_conversation_with_unanswerable_questions(self):
        self.assertTrue(O.CASE.persona)
        self.assertIn("haven't decided", O.CASE.persona)
        for rubric in (O.FINAL_MESSAGE, O.CONVERSATION):
            ids = [item["id"] for item in rubric]
            self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
