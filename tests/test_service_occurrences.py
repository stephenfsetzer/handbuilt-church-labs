from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from skills.bulletin.bulletin_production import finalize, orient, produce, revise
from tests.helpers import bulletin_input, make_church
from tests.test_bulletin_saved_worship import _configured_profile


DATE = "2026-09-20"


def _catalog_profile(church: Path) -> None:
    _configured_profile(church)
    profile_path = church / "worship" / "profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["catalog"] = {
        "schema_version": 1,
        "default_service": "sunday",
        "services": {
            "sunday": {"name": "Sunday Eucharist"},
            "family": {"name": "Family Eucharist"},
        },
        "parts": {},
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")


def _request(service_id: str, occurrence_id: str | None = None, marker: str = "Service Marker") -> dict:
    request = copy.deepcopy(bulletin_input())
    request["service"]["service_id"] = service_id
    if occurrence_id is not None:
        request["service"]["occurrence_id"] = occurrence_id
    request["hymns"]["entrance"]["title"] = marker
    request["announcements"] = [{"title": marker, "text": f"{marker} announcement."}]
    return request


def _package_html(result: dict) -> str:
    folder = Path(result["week_folder"])
    return next(folder.glob("*.html")).read_text(encoding="utf-8")


def _approve(result: dict) -> dict:
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    hashes = {item["role"]: item["sha256"] for item in receipt["artifacts"]}
    return finalize(
        receipt_path,
        {
            "production_run_id": receipt["run_id"],
            "approved_by": "Synthetic reviewer",
            "reviewed_artifact_hashes": hashes,
        },
    )


def _history(church: Path) -> dict:
    return json.loads((church / "bulletins" / "bulletin-log.json").read_text(encoding="utf-8"))


class ServiceOccurrencesTest(unittest.TestCase):
    def test_two_services_same_date_have_distinct_rendered_packages_and_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)

            sunday = produce(church, _request("sunday", marker="Sunday Marker"))
            family = produce(church, _request("family", marker="Family Marker"))

            self.assertEqual(sunday["status"], "ready_for_review", sunday)
            self.assertEqual(family["status"], "ready_for_review", family)
            for result, service_id, marker in (
                (sunday, "sunday", "Sunday Marker"),
                (family, "family", "Family Marker"),
            ):
                relative = Path(result["week_folder"]).resolve().relative_to((church / "bulletins").resolve())
                self.assertEqual(relative.parts, ("2026", "09", DATE, service_id, "main"))
                self.assertIn(marker, _package_html(result))

            self.assertEqual(_approve(family)["status"], "approved")
            self.assertEqual(_approve(sunday)["status"], "approved")
            history = _history(church)
            self.assertEqual(
                set(history),
                {f"{DATE}::sunday::main", f"{DATE}::family::main"},
            )
            self.assertEqual(history[f"{DATE}::sunday::main"]["service_id"], "sunday")
            self.assertEqual(history[f"{DATE}::family::main"]["service_id"], "family")

            oriented = orient(church, DATE, service_id="family")
            self.assertEqual(oriented["status"], "ok", oriented)
            self.assertEqual(oriented["service_context"]["service_id"], "family")
            self.assertEqual(oriented["service_context"]["name"], "Family Eucharist")
            self.assertIn("worship_resolution", oriented)
            self.assertIn("saved_services", oriented)
            self.assertIn("family", oriented["saved_services"])
            self.assertIn("saved_parts", oriented)
            self.assertEqual(oriented["last_approved_bulletin"]["service_id"], "family")

    def test_same_service_second_occurrence_has_independent_history_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)

            main = produce(church, _request("sunday", marker="Morning Marker"))
            evening = produce(church, _request("sunday", "evening", "Evening Marker"))

            self.assertEqual(main["status"], "ready_for_review", main)
            self.assertEqual(evening["status"], "ready_for_review", evening)
            main_relative = Path(main["week_folder"]).resolve().relative_to((church / "bulletins").resolve())
            evening_relative = Path(evening["week_folder"]).resolve().relative_to((church / "bulletins").resolve())
            self.assertEqual(main_relative.parts, ("2026", "09", DATE, "sunday", "main"))
            self.assertEqual(evening_relative.parts, ("2026", "09", DATE, "sunday", "evening"))
            self.assertIn("Morning Marker", _package_html(main))
            self.assertIn("Evening Marker", _package_html(evening))

            self.assertEqual(_approve(main)["status"], "approved")
            self.assertEqual(_approve(evening)["status"], "approved")
            self.assertEqual(
                set(_history(church)),
                {f"{DATE}::sunday::main", f"{DATE}::sunday::evening"},
            )

            self.assertEqual(orient(church, DATE, service_id="sunday", occurrence_id="evening")
                             ["last_approved_bulletin"]["occurrence_id"], "evening")
            self.assertEqual(orient(church, DATE, service_id="sunday")
                             ["last_approved_bulletin"]["occurrence_id"], "main")
            self.assertEqual(orient(church, DATE)["existing_work"],
                             [str(Path(main["week_folder"]).resolve().relative_to(church.resolve()))])
            self.assertEqual(orient(church, DATE, occurrence_id="evening")["existing_work"],
                             [str(Path(evening["week_folder"]).resolve().relative_to(church.resolve()))])

    def test_revision_targets_one_occurrence_without_changing_the_other(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)

            main = produce(church, _request("sunday", marker="Original Morning"))
            evening = produce(church, _request("sunday", "evening", "Original Evening"))
            self.assertEqual(main["status"], "ready_for_review", main)
            self.assertEqual(evening["status"], "ready_for_review", evening)
            evening_html_before = _package_html(evening)

            revised = revise(
                church,
                main["receipt_path"],
                {"announcements": [{"title": "Revised Morning", "text": "Revised morning text."}]},
            )
            self.assertEqual(revised["status"], "ready_for_review", revised)
            self.assertEqual(Path(revised["week_folder"]).resolve(), Path(main["week_folder"]).resolve())
            self.assertIn("Revised Morning", _package_html(revised))
            self.assertNotIn("Revised Morning", evening_html_before)
            self.assertEqual(_package_html(evening), evening_html_before)

            self.assertEqual(_approve(revised)["status"], "approved")
            self.assertEqual(_approve(evening)["status"], "approved")
            self.assertEqual(
                set(_history(church)),
                {f"{DATE}::sunday::main", f"{DATE}::sunday::evening"},
            )

    def test_service_label_rename_keeps_stable_identity_and_prior_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)

            first = produce(church, _request("sunday", marker="Before Rename"))
            self.assertEqual(first["status"], "ready_for_review", first)
            self.assertEqual(_approve(first)["status"], "approved")

            profile_path = church / "worship" / "profile.yaml"
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            profile["catalog"]["services"]["sunday"]["name"] = "Principal Eucharist"
            profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

            second_request = _request("sunday", marker="After Rename")
            second_request["service"]["date"] = "2026-09-27"
            second = produce(church, second_request)
            self.assertEqual(second["status"], "ready_for_review", second)
            relative = Path(second["week_folder"]).resolve().relative_to((church / "bulletins").resolve())
            self.assertEqual(relative.parts, ("2026", "09", "2026-09-27", "sunday", "main"))
            self.assertEqual(_approve(second)["status"], "approved")

            history = _history(church)
            self.assertEqual(set(history), {"2026-09-20::sunday::main", "2026-09-27::sunday::main"})
            self.assertEqual(history["2026-09-20::sunday::main"]["service_id"], "sunday")
            oriented = orient(church, "2026-09-27", service_id="sunday")
            self.assertEqual(oriented["service_context"]["name"], "Principal Eucharist")

    def test_explicit_legacy_association_recovers_history_and_protects_approval(self) -> None:
        from skills.onboarding.scripts.church_setup import update_standing
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _configured_profile(church)
            legacy = produce(church, bulletin_input())
            self.assertEqual(legacy["status"], "ready_for_review", legacy)
            self.assertEqual(_approve(legacy)["status"], "approved")
            history_path = church / "bulletins/bulletin-log.json"
            old_history = history_path.read_bytes()
            old_artifacts = {p: p.read_bytes() for p in Path(legacy["week_folder"]).iterdir() if p.is_file()}
            update_standing(church, {"worship_profile": {"catalog": {
                "schema_version": 1, "default_service": "sunday", "legacy_service": "sunday",
                "services": {"sunday": {"name": "Sunday Eucharist"}, "family": {"name": "Family Service"}},
                "parts": {}}}})
            oriented = orient(church, DATE)
            self.assertEqual(oriented["initialization_state"], "returning")
            self.assertEqual(oriented["last_approved_bulletin"]["date"], DATE)
            self.assertIn(str(Path(legacy["week_folder"]).resolve().relative_to(church.resolve())), oriented["existing_work"])
            self.assertEqual(orient(church, DATE, service_id="family")["initialization_state"], "first_run")
            self.assertEqual(orient(church, DATE, service_id="sunday", occurrence_id="evening")["initialization_state"], "first_run")
            self.assertEqual(history_path.read_bytes(), old_history)
            repeated_date = produce(church, _request("sunday"))
            self.assertEqual(repeated_date["status"], "ready_for_review", repeated_date)
            approval = _approve(repeated_date)
            self.assertEqual(approval["status"], "blocked", approval)
            self.assertEqual(approval["errors"][0]["code"], "approved_history_conflict")
            self.assertEqual(history_path.read_bytes(), old_history)
            self.assertEqual(old_artifacts, {p: p.read_bytes() for p in old_artifacts})

    def test_unsafe_service_and_occurrence_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            _catalog_profile(church)

            for service_id, occurrence_id in (("family/../escape", None), ("sunday", "../escape")):
                with self.subTest(service_id=service_id, occurrence_id=occurrence_id):
                    result = produce(church, _request(service_id, occurrence_id))
                    self.assertEqual(result["status"], "blocked", result)
                    self.assertTrue(result.get("errors"))
                    self.assertFalse((church.parent / "escape").exists())

    def test_profile_without_catalog_keeps_legacy_service_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "ready_for_review", result)
            relative = Path(result["week_folder"]).resolve().relative_to((church / "bulletins").resolve())
            self.assertEqual(relative.parts, ("2026", "09", "2026-09-20-a-test-sunday-in-september"))


if __name__ == "__main__":
    unittest.main()
