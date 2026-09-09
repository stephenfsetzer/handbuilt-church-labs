from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml
from pypdf import PdfReader

from skills.bulletin.bulletin_production import orient, produce
from tests.helpers import bulletin_input, make_church


class BulletinOrientationContextTest(unittest.TestCase):
    def test_new_task_recovers_confirmed_roster_and_layout_without_weekly_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            config_path = church / "church.yaml"
            config = yaml.safe_load(config_path.read_text())
            roster = [
                {"name": "The Rev. Morgan Example", "role": "Rector"},
                {"name": "The Rev. Avery Example", "role": "Associate Rector"},
            ]
            config["leadership"] = {"clergy_and_staff": roster, "print_in_bulletin": False}
            config["bulletin"] = {"template": "modern", "serving_roles": ["Reader"]}
            config["people"]["celebrant"] = "A past standing value"
            config_path.write_text(yaml.safe_dump(config, sort_keys=False))
            before = {path: path.read_bytes() for path in church.rglob("*") if path.is_file()}

            result = orient(church, "2026-09-20")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["known_people"], roster)
            self.assertEqual(result["default_template"], "modern")
            self.assertEqual(result["church_context"]["lectionary"]["track"], "Track 2")
            self.assertIsNone(result["carry_forward_candidates"]["celebrant"])
            self.assertIsNone(result["carry_forward_candidates"]["preacher"])
            self.assertIn("celebrant", result["requires_weekly_confirmation"])
            self.assertEqual(before, {path: path.read_bytes() for path in church.rglob("*") if path.is_file()})

    def test_explicit_standing_layout_supersedes_old_approved_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            path = church / "church.yaml"
            config = yaml.safe_load(path.read_text())
            config["bulletin"] = {"template": "modern"}
            config["church"]["name"] = "Synthetic Harbor Parish"
            config["church"]["regular_services"] = [{"day": "Sunday", "time": "10:30 am"}]
            path.write_text(yaml.safe_dump(config))
            old = {"2026-09-13": {"templates": {"classic": {}}, "preacher": "A previous preacher"}}
            (church / "bulletins" / "bulletin-log.json").write_text(json.dumps(copy.deepcopy(old)))

            result = orient(church, "2026-09-20")

            self.assertEqual(result["default_template"], "modern")
            self.assertEqual(result["last_approved_bulletin"], old["2026-09-13"])
            self.assertIn("preacher", result["requires_weekly_confirmation"])

    def test_orientation_rejects_profile_pointer_outside_church(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            path = church / "church.yaml"
            config = yaml.safe_load(path.read_text())
            config["worship_profile"] = "../outside-profile.yaml"
            path.write_text(yaml.safe_dump(config))
            result = orient(church, "2026-09-20")
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["code"], "unsafe_path")

    def test_production_uses_saved_layout_and_keeps_weekly_override_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            path = church / "church.yaml"
            config = yaml.safe_load(path.read_text())
            config["bulletin"] = {"template": "modern"}
            config["church"]["name"] = "Synthetic Harbor Parish"
            config["church"]["regular_services"] = [{"day": "Sunday", "time": "10:30 am"}]
            path.write_text(yaml.safe_dump(config))
            before = path.read_bytes()
            weekly = bulletin_input()
            del weekly["template"]

            result = produce(church, weekly)

            self.assertEqual(result["status"], "ready_for_review", result)
            self.assertTrue((Path(result["week_folder"]) / "bulletin-2026-09-20-modern.pdf").is_file())
            pdf = Path(result["week_folder"]) / "bulletin-2026-09-20-modern.pdf"
            cover = PdfReader(pdf).pages[0].extract_text()
            self.assertIn("Synthetic Harbor Parish", cover)
            self.assertIn("10:30 am", cover)
            weekly["template"] = "classic"
            weekly["service"]["date"] = "2026-09-27"
            weekly["service"]["time"] = "11:15 am"
            second = produce(church, weekly)
            self.assertEqual(second["status"], "ready_for_review", second)
            self.assertTrue((Path(second["week_folder"]) / "bulletin-2026-09-27-classic.pdf").is_file())
            cover = PdfReader(Path(second["week_folder"]) / "bulletin-2026-09-27-classic.pdf").pages[0].extract_text()
            self.assertIn("11:15 am", cover)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
