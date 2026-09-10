from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
import sys
sys.path.insert(0, str(ROOT / "skills" / "onboarding" / "scripts"))
import church_setup
from tests.helpers import (
    bulletin_input,
    make_church,
    reading_metadata,
    readings_content,
    research_brief,
    research_metadata,
)


class ChurchSetupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.church = Path(self.temp.name) / "sample-church"
        import shutil
        shutil.copytree(ROOT / "scaffold" / "church-folder", self.church)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_status_distinguishes_scaffold_folder_and_workflow_readiness(self) -> None:
        initial = church_setup.status(self.church)
        self.assertTrue(initial["scaffold_ready"])
        self.assertFalse(initial["folder_ready"])
        self.assertEqual(initial["state"], "scaffold_ready")

        church_setup.update_standing(self.church, {
            "church": {"name": "Sample Church", "short_name": "Sample"},
            "worship_profile": {
                "tradition_pack": "episcopal-bcp-rite-ii",
                "status": "confirmed",
                "defaults": {
                    "eucharistic_prayer": "A", "lords_prayer": "traditional", "prayers_of_the_people": "III",
                    "include_creed": True, "include_confession": True,
                    "print_full_eucharistic_prayer": False,
                },
            },
            "sermon": {"selection_mode": "lectionary", "primary_text": "gospel"},
            "lectionary": {"system": "RCL", "track": "Track 2", "translation": "NRSV"},
        })
        pending = church_setup.status(self.church)
        self.assertFalse(pending["bulletin_ready"])
        church_setup.update_standing(self.church, {
            "worship_profile": {"defaults": {"psalm_format": "responsive_half_verse"}},
        })
        import brand_setup
        brand_setup.update(self.church, {"logo_status": "none", "colors_status": "neutral"})
        ready = church_setup.status(self.church)
        self.assertTrue(ready["folder_ready"])
        self.assertTrue(ready["research_ready"])
        self.assertTrue(ready["bulletin_ready"])
        self.assertTrue(ready["workflow_ready"])
        self.assertFalse(ready["actual_first_result"])

    def test_standing_readiness_ignores_an_unselected_but_configured_variant(self) -> None:
        orders_dir = self.church / "worship" / "orders"
        orders_dir.mkdir(parents=True, exist_ok=True)
        (orders_dir / "labor-day.yaml").write_text(
            "replace:\n  - unit: collect-of-day\n    with: [labor-day-collect]\n", encoding="utf-8"
        )
        church_setup.update_standing(self.church, {
            "church": {"name": "Sample Church", "short_name": "Sample"},
            "worship_profile": {
                "tradition_pack": "episcopal-bcp-rite-ii",
                "status": "confirmed",
                "defaults": {
                    "eucharistic_prayer": "A", "lords_prayer": "traditional", "prayers_of_the_people": "III",
                    "include_creed": True, "include_confession": True,
                    "print_full_eucharistic_prayer": False,
                },
                "service_variants": {
                    "labor_day": {
                        "name": "Labor Day",
                        "base_service_plan": "episcopal-rite-ii",
                        "order_file": "worship/orders/labor-day.yaml",
                        "confirmation_policy": "ask_each_week",
                    },
                },
            },
            "sermon": {"selection_mode": "lectionary", "primary_text": "gospel"},
            "lectionary": {"system": "RCL", "track": "Track 2", "translation": "NRSV"},
        })
        church_setup.update_standing(self.church, {
            "worship_profile": {"defaults": {"psalm_format": "responsive_half_verse"}},
        })
        import brand_setup
        brand_setup.update(self.church, {"logo_status": "none", "colors_status": "neutral"})

        ready = church_setup.status(self.church)
        self.assertTrue(ready["bulletin_ready"])
        self.assertEqual(ready["worship"]["status"], "resolved")
        self.assertTrue(ready["worship"]["service_variant_pending"])

        from skills.bulletin.worship_resolution import resolve_worship_profile
        weekly = resolve_worship_profile(self.church)
        self.assertEqual(weekly["status"], "needs_input")
        self.assertEqual(weekly["unresolved"][0]["field"], "service.variant")

    def test_shared_closing_hymn_position_and_leadership_placement_are_validated(self) -> None:
        church_setup.update_standing(self.church, {
            "worship_profile": {"defaults": {"closing_hymn_position": "after_dismissal"}},
            "leadership": {"placement": "body"},
        })
        profile = yaml.safe_load((self.church / "worship" / "profile.yaml").read_text(encoding="utf-8"))
        config = yaml.safe_load((self.church / "church.yaml").read_text(encoding="utf-8"))
        self.assertEqual(profile["defaults"]["closing_hymn_position"], "after_dismissal")
        self.assertEqual(config["leadership"]["placement"], "body")
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"defaults": {"closing_hymn_position": "sometime"}}})
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"leadership": {"placement": "sidebar"}})

    def test_track_alias_is_saved_canonically_and_invalid_track_cannot_be_ready(self) -> None:
        result = church_setup.update_standing(self.church, {
            "church": {"name": "Sample Church"},
            "lectionary": {"system": "RCL", "track": "2"},
        })
        self.assertEqual(yaml.safe_load((self.church / "church.yaml").read_text())["lectionary"]["track"], "Track 2")
        before = (self.church / "church.yaml").read_bytes()
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"lectionary": {"track": "Track 3"}})
        self.assertEqual((self.church / "church.yaml").read_bytes(), before)
        config = yaml.safe_load(before)
        config["lectionary"]["track"] = "2"
        (self.church / "church.yaml").write_text(yaml.safe_dump(config))
        check = church_setup.status(self.church)
        self.assertEqual(check["status"], "needs_input")
        self.assertFalse(check["workflow_ready"])
        self.assertIn("lectionary.track", check["next_action"])

    def test_roster_resolution_requires_unique_role_and_strips_titles(self) -> None:
        church_setup.update_standing(self.church, {
            "leadership": {"clergy_and_staff": [
                {"name": "The Rev. Matthew Green", "role": "Associate Rector"},
                {"name": "Dr. Morgan Gray", "role": "Musician"},
            ]}
        })
        resolved = church_setup.resolve_person(self.church, role="associate rector", name="Matthew")
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["person"]["name"], "The Rev. Matthew Green")
        resolved_full = church_setup.resolve_person(self.church, role="associate rector", name="Matthew Green")
        self.assertEqual(resolved_full["status"], "resolved")

        church_setup.update_standing(self.church, {"leadership": {"clergy_and_staff": [
            {"name": "The Rev. Matthew Green", "role": "Associate Rector"},
            {"name": "The Rev. Matthew Gray", "role": "Associate Rector"},
        ]}})
        ambiguous = church_setup.resolve_person(self.church, role="Associate Rector", name="Matthew")
        self.assertEqual(ambiguous["status"], "needs_input")
        self.assertEqual(len(ambiguous["matches"]), 2)

    def test_invalid_patch_is_rejected_without_changing_files(self) -> None:
        before = (self.church / "church.yaml").read_text(encoding="utf-8")
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"bulletin": {"template": "compact"}})
        self.assertEqual((self.church / "church.yaml").read_text(encoding="utf-8"), before)
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"people": {"celebrant": "One week only"}})
        profile_before = (self.church / "worship" / "profile.yaml").read_text(encoding="utf-8")
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"church": {"name": "Would not save"}, "worship_profile": {"defaults": {"unknown": "bad"}}})
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"tradition_pack": "unknown-pack"}})
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"status": "configured"}})
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"defaults": {"include_creed": "yes"}}})
        self.assertEqual((self.church / "church.yaml").read_text(encoding="utf-8"), before)
        self.assertEqual((self.church / "worship" / "profile.yaml").read_text(encoding="utf-8"), profile_before)

    def test_lutheran_private_source_paths_are_supported_and_bounded(self) -> None:
        source = self.church / "worship" / "liturgy" / "gathering.txt"
        source.parent.mkdir()
        source.write_text("Synthetic private text", encoding="utf-8")
        church_setup.update_standing(self.church, {"worship_profile": {
            "sources": {"gathering": "worship/liturgy/gathering.txt", "lords-prayer": "worship/liturgy/lords-prayer.txt"},
        }})
        profile = yaml.safe_load((self.church / "worship" / "profile.yaml").read_text(encoding="utf-8"))
        self.assertEqual(profile["sources"]["gathering"], "worship/liturgy/gathering.txt")
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"sources": {"sending": "../outside.txt"}}})

    def test_weekly_scope_is_explicitly_refused(self) -> None:
        with self.assertRaises(church_setup.SetupError):
            church_setup.update(self.church, {"church": {"name": "Weekly"}}, scope="weekly")

    def test_saved_worship_preferences_and_doxology_music_do_not_touch_weekly_state(self) -> None:
        weekly = self.church / "bulletins" / "2026-09-20"
        weekly.mkdir(parents=True)
        weekly_input = weekly / "input.json"
        weekly_input.write_text('{"service": {"date": "2026-09-20"}}\n', encoding="utf-8")
        history = self.church / "bulletins" / "history.json"
        history.write_text('{"approved": []}\n', encoding="utf-8")
        before_weekly = weekly_input.read_bytes()
        before_history = history.read_bytes()

        church_setup.update_standing(self.church, {
            "worship_profile": {
                "defaults": {
                    "doxology": "custom",
                    "psalm_format": "responsive_whole_verse",
                    "psalm_response_start": "second",
                    "prayer_presentation": "repeated_labels",
                    "rubric_style": "source",
                },
                "sources": {"doxology": "worship/liturgy/doxology.txt"},
            },
            "bulletin": {
                "doxology_music": {
                    "number": 123,
                    "title": "Synthetic Doxology",
                    "tune": "SYNTHETIC",
                    "image": "music/doxology.png",
                },
            },
        })

        profile = yaml.safe_load((self.church / "worship" / "profile.yaml").read_text(encoding="utf-8"))
        config = yaml.safe_load((self.church / "church.yaml").read_text(encoding="utf-8"))
        self.assertEqual(profile["defaults"]["doxology"], "custom")
        self.assertEqual(profile["defaults"]["psalm_format"], "responsive_whole_verse")
        self.assertEqual(profile["defaults"]["psalm_response_start"], "second")
        self.assertEqual(profile["defaults"]["prayer_presentation"], "repeated_labels")
        self.assertEqual(profile["defaults"]["rubric_style"], "source")
        self.assertEqual(profile["sources"]["doxology"], "worship/liturgy/doxology.txt")
        self.assertEqual(config["bulletin"]["doxology_music"]["title"], "Synthetic Doxology")
        self.assertEqual(weekly_input.read_bytes(), before_weekly)
        self.assertEqual(history.read_bytes(), before_history)

    def test_worship_preferences_and_music_reject_invalid_or_arbitrary_values(self) -> None:
        before_config = (self.church / "church.yaml").read_bytes()
        before_profile = (self.church / "worship" / "profile.yaml").read_bytes()
        invalid = (
            {"doxology": "maybe"},
            {"psalm_format": "one_verse_per_line"},
            {"psalm_response_start": "either"},
            {"prayer_presentation": "short"},
            {"rubric_style": "verbose"},
        )
        for defaults in invalid:
            with self.assertRaises(church_setup.SetupError):
                church_setup.update_standing(self.church, {"worship_profile": {"defaults": defaults}})
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"sources": {"doxology": "../outside.txt"}}})
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"bulletin": {"doxology_music": {"title": "No", "unknown": True}}})
        self.assertEqual((self.church / "church.yaml").read_bytes(), before_config)
        self.assertEqual((self.church / "worship" / "profile.yaml").read_bytes(), before_profile)

    def test_reading_display_preferences_require_booleans(self) -> None:
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"defaults": {"include_first_reading": "yes"}}})
        church_setup.update_standing(self.church, {"worship_profile": {"defaults": {"include_first_reading": False, "include_second_reading": True}}})
        profile = yaml.safe_load((self.church / "worship" / "profile.yaml").read_text())
        self.assertFalse(profile["defaults"]["include_first_reading"])
        self.assertTrue(profile["defaults"]["include_second_reading"])
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {"worship_profile": {"defaults": {"include_second_reading": False}}})

    def test_non_rcl_research_does_not_require_an_inapplicable_track(self) -> None:
        church_setup.update_standing(self.church, {
            "church": {"name": "Synthetic Parish"},
            "sermon": {"selection_mode": "lectionary", "primary_text": "gospel"},
            "lectionary": {"system": "BCP", "track": "", "translation": "Synthetic Translation"},
        })
        self.assertTrue(church_setup.status(self.church)["research_ready"])

    def test_pastor_selected_research_does_not_imply_bulletin_readings_are_configured(self) -> None:
        church_setup.update_standing(self.church, {
            "church": {"name": "Synthetic Parish"},
            "sermon": {"selection_mode": "pastor_selected", "primary_text": "selected"},
            "lectionary": {"translation": "Synthetic Translation"},
        })
        result = church_setup.status(self.church)
        self.assertTrue(result["research_ready"])
        self.assertFalse(result["bulletin_ready"])

    def test_public_repo_and_symlink_roots_are_rejected(self) -> None:
        with self.assertRaises(church_setup.SetupError):
            church_setup.status(ROOT)
        link = Path(self.temp.name) / "church-link"
        link.symlink_to(self.church, target_is_directory=True)
        with self.assertRaises(church_setup.SetupError):
            church_setup.status(link)
        config_target = Path(self.temp.name) / "external-church.yaml"
        config_target.write_text((self.church / "church.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        config = self.church / "church.yaml"
        config.unlink()
        config.symlink_to(config_target)
        with self.assertRaises(church_setup.SetupError):
            church_setup.status(self.church)

    def test_status_recognizes_real_completed_sermon_receipts(self) -> None:
        source_root = Path(self.temp.name) / "real-sermon"
        source_root.mkdir()
        church = make_church(source_root)
        church_setup.update_standing(church, {"worship_profile": {
            "tradition_pack": "episcopal-bcp-rite-ii",
            "status": "confirmed",
            "defaults": {
                "eucharistic_prayer": "A", "lords_prayer": "traditional",
                "include_creed": True, "include_confession": True,
                "print_full_eucharistic_prayer": False,
            },
        }})
        import sys
        sys.path.insert(0, str(ROOT / "skills" / "sermon-research"))
        from sermon_workflow import record
        record(church, "2026-09-20", "readings", readings_content(), reading_metadata())
        record(church, "2026-09-20", "research", research_brief(), research_metadata())
        result = church_setup.status(church)
        self.assertTrue(result["actual_first_result"])
        self.assertTrue(any(item["kind"] == "sermon_research" for item in result["first_results"]))

    def test_status_recognizes_real_bulletin_receipt_and_rejects_tampering(self) -> None:
        from skills.bulletin.bulletin_production import produce
        church = make_church(Path(self.temp.name))
        production = produce(church, bulletin_input())
        self.assertEqual(production["status"], "ready_for_review", production)
        result = church_setup.status(church)
        self.assertTrue(result["actual_first_result"])
        self.assertTrue(any(item["kind"] == "bulletin" for item in result["first_results"]))
        receipt_path = Path(production["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact_path = church / receipt["artifacts"][0]["path"]
        artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")
        after_tamper = church_setup.status(church)
        self.assertFalse(after_tamper["actual_first_result"])


if __name__ == "__main__":
    unittest.main()
