from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from skills.onboarding.scripts import church_setup
from skills.onboarding.scripts.church_setup import SetupError, update, update_standing
from tests.helpers import make_church, verify_liturgy_source
from tests.test_bulletin_saved_worship import _configured_profile


def _catalog_profile(church: Path) -> None:
    _configured_profile(church)
    catalog = {
        "schema_version": 1,
        "default_service": "sunday",
        "services": {
            "sunday": {"name": "Sunday Eucharist"},
            "family": {"name": "Family Eucharist"},
        },
        "parts": {},
    }
    result = update(
        church,
        {"worship_profile": {"catalog": catalog}},
        scope="standing",
    )
    if not result["verified"]:
        raise AssertionError(result)


def _profile(church: Path) -> dict:
    return yaml.safe_load((church / "worship" / "profile.yaml").read_text(encoding="utf-8"))


def _verified_part(church: Path, filename: str, text: str) -> str:
    path = church / "worship" / "liturgy" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    verify_liturgy_source(church, path)
    return path.relative_to(church).as_posix()


def _shared_part_profile(church: Path, old_file: str) -> None:
    profile_path = church / "worship" / "profile.yaml"
    profile = _profile(church)
    profile["catalog"]["part_selections"] = {
        "communion_welcome": "shared-welcome",
    }
    profile["catalog"]["parts"] = {
        "shared-welcome": {
            "name": "Shared Communion Welcome",
            "unit": "communion_welcome",
            "file": old_file,
        },
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")


class ServiceSettingsTest(unittest.TestCase):
    def test_service_preview_reports_scope_and_does_not_mutate_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            config_path = church / "church.yaml"
            profile_path = church / "worship" / "profile.yaml"
            before_config = config_path.read_bytes()
            before_profile = profile_path.read_bytes()

            result = update(
                church,
                {"defaults": {"include_confession": False}},
                scope="service",
                service_id="family",
                preview=True,
            )

            self.assertEqual(result["status"], "preview")
            self.assertEqual(result["scope"], "service")
            self.assertEqual(result["service_id"], "family")
            self.assertIn("family", result["affected_services"])
            self.assertIn("before_state", result)
            self.assertIn("state", result)
            self.assertFalse(result["verified"])
            self.assertEqual(config_path.read_bytes(), before_config)
            self.assertEqual(profile_path.read_bytes(), before_profile)

    def test_service_update_changes_only_selected_service_and_reports_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)

            result = update(
                church,
                {"defaults": {"include_confession": False}},
                scope="service",
                service_id="family",
            )

            self.assertTrue(result["verified"])
            self.assertEqual(result["scope"], "service")
            self.assertEqual(result["service_id"], "family")
            self.assertIn("worship_profile.catalog.services.family.defaults", result["changed"])
            self.assertIn("family", result["affected_services"])
            self.assertIn("readiness", result)
            saved = _profile(church)["catalog"]["services"]
            self.assertFalse(saved["family"]["defaults"]["include_confession"])
            self.assertNotIn("defaults", saved["sunday"])

    def test_shared_selected_part_change_reports_both_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            old_file = _verified_part(church, "welcome-old.md", "# Welcome\n\nOld synthetic welcome.\n")
            new_file = _verified_part(church, "welcome-new.md", "# Welcome\n\nNew synthetic welcome.\n")
            _shared_part_profile(church, old_file)

            result = update_standing(
                church,
                {"worship_profile": {"catalog": {"parts": {"shared-welcome": {"file": new_file}}}}},
            )

            self.assertTrue(result["verified"])
            self.assertEqual(result["scope"], "standing")
            self.assertIn("worship_profile.catalog.parts.shared-welcome.file", result["changed"])
            self.assertEqual(set(result["affected_services"]), {"sunday", "family"})
            self.assertEqual(_profile(church)["catalog"]["parts"]["shared-welcome"]["file"], new_file)
            self.assertEqual(_profile(church)["catalog"]["part_selections"]["communion_welcome"], "shared-welcome")

    def test_stale_expected_state_rejects_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            proposal = update(
                church,
                {"defaults": {"include_confession": False}},
                scope="service",
                service_id="family",
                preview=True,
            )
            update(
                church,
                {"defaults": {"include_confession": True}},
                scope="service",
                service_id="family",
            )
            before = {
                "church.yaml": (church / "church.yaml").read_bytes(),
                "profile.yaml": (church / "worship" / "profile.yaml").read_bytes(),
            }

            with self.assertRaises(SetupError):
                update(
                    church,
                    {"defaults": {"include_confession": False}},
                    scope="service",
                    service_id="family",
                    expected_state=proposal["before_state"],
                )

            self.assertEqual((church / "church.yaml").read_bytes(), before["church.yaml"])
            self.assertEqual((church / "worship" / "profile.yaml").read_bytes(), before["profile.yaml"])

    def test_invalid_catalog_reference_rejects_mixed_patch_without_mutating_either_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            config_path = church / "church.yaml"
            profile_path = church / "worship" / "profile.yaml"
            before_config = config_path.read_bytes()
            before_profile = profile_path.read_bytes()
            invalid_catalog = {
                "schema_version": 1,
                "default_service": "sunday",
                "services": {
                    "sunday": {"name": "Sunday Eucharist"},
                    "family": {"name": "Family Eucharist"},
                },
                "parts": {},
                "part_selections": {
                    "communion_welcome": "missing-part",
                },
            }

            with self.assertRaises(SetupError):
                update_standing(
                    church,
                    {
                        "church": {"name": "Would Not Save Parish"},
                        "worship_profile": {"catalog": invalid_catalog},
                    },
                )

            self.assertEqual(config_path.read_bytes(), before_config)
            self.assertEqual(profile_path.read_bytes(), before_profile)

    def test_second_file_write_failure_restores_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            config_path = church / "church.yaml"
            profile_path = church / "worship" / "profile.yaml"
            before_config = config_path.read_bytes()
            before_profile = profile_path.read_bytes()
            real_dump = church_setup._dump_yaml
            calls = 0

            def fail_on_second(path: Path, value: dict) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic second-file failure")
                real_dump(path, value)

            with patch.object(church_setup, "_dump_yaml", side_effect=fail_on_second):
                with self.assertRaises((OSError, SetupError)):
                    update_standing(
                        church,
                        {
                            "church": {"name": "Would Roll Back Parish"},
                            "worship_profile": {"defaults": {"include_confession": True}},
                        },
                    )

            self.assertEqual(calls, 2)
            self.assertEqual(config_path.read_bytes(), before_config)
            self.assertEqual(profile_path.read_bytes(), before_profile)

    def test_repeated_noop_service_update_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            patch_value = {"defaults": {"include_confession": False}}
            first = update(church, patch_value, scope="service", service_id="family")
            config_path = church / "church.yaml"
            profile_path = church / "worship" / "profile.yaml"
            before = config_path.read_bytes(), profile_path.read_bytes()

            second = update(church, patch_value, scope="service", service_id="family")

            self.assertTrue(first["verified"])
            self.assertTrue(second["verified"])
            self.assertEqual(second["changed"], [])
            self.assertEqual((config_path.read_bytes(), profile_path.read_bytes()), before)

    def test_weekly_scope_is_rejected_by_scoped_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)
            with self.assertRaises(SetupError):
                update(
                    church,
                    {"defaults": {"include_confession": False}},
                    scope="weekly",
                    service_id="family",
                )


if __name__ == "__main__":
    unittest.main()
