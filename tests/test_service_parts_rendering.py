from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from skills.bulletin.bulletin_production import produce, revise
from tests.helpers import bulletin_input, make_church, verify_liturgy_source
from tests.test_bulletin_saved_worship import _configured_profile


class ServicePartsRenderingTest(unittest.TestCase):
    def _part(self, church: Path, filename: str, text: str) -> str:
        path = church / "worship" / "liturgy" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        verify_liturgy_source(church, path)
        return path.relative_to(church).as_posix()

    def _configure_catalog(self, church: Path) -> None:
        _configured_profile(church)
        profile_path = church / "worship" / "profile.yaml"
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile["sources"] = {}
        shared_prayers = self._part(
            church, "shared-prayers.md",
            "# Shared Prayers\n\nCelebrant\tShared prayer rendering marker.\n",
        )
        family_prayers = self._part(
            church, "family-prayers.md",
            "# Family Prayers\n\nCelebrant\tFamily prayer rendering marker.\n",
        )
        dated_prayers = self._part(
            church, "dated-prayers.md",
            "# Dated Prayers\n\nCelebrant\tDated prayer rendering marker.\n",
        )
        welcome = self._part(
            church, "welcome.md",
            "# Communion Welcome\n\nAll visitors may receive the reusable welcome marker.\n",
        )
        profile["catalog"] = {
            "schema_version": 1,
            "default_service": "sunday",
            "parts": {
                "shared-prayers": {"name": "Shared Prayers", "unit": "prayers-of-the-people", "file": shared_prayers},
                "family-prayers": {"name": "Family Prayers", "unit": "prayers-of-the-people", "file": family_prayers},
                "dated-prayers": {"name": "Dated Prayers", "unit": "prayers-of-the-people", "file": dated_prayers},
                "welcome": {"name": "Reusable Welcome", "unit": "communion_welcome", "file": welcome},
            },
            "part_selections": {
                "prayers-of-the-people": "shared-prayers",
                "communion_welcome": "welcome",
            },
            "services": {
                "sunday": {"name": "Sunday Eucharist"},
                "family": {
                    "name": "Family Eucharist",
                    "part_selections": {"prayers-of-the-people": "family-prayers"},
                },
            },
        }
        profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    @staticmethod
    def _html(result: dict) -> str:
        return next(Path(result["week_folder"]).glob("*.html")).read_text(encoding="utf-8")

    def test_catalog_part_sources_print_for_default_service_service_override_and_dated_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            self._configure_catalog(church)

            sunday = bulletin_input()
            sunday["service"]["service_id"] = "sunday"
            sunday["liturgy"] = {}
            sunday_result = produce(church, sunday)
            self.assertEqual(sunday_result["status"], "ready_for_review", sunday_result)
            sunday_html = self._html(sunday_result)
            self.assertIn("Shared prayer rendering marker.", sunday_html)

            family = copy.deepcopy(sunday)
            family["service"].update(service_id="family", date="2026-09-27")
            family_result = produce(church, family)
            self.assertEqual(family_result["status"], "ready_for_review", family_result)
            family_html = self._html(family_result)
            self.assertIn("Family prayer rendering marker.", family_html)
            self.assertNotIn("Shared prayer rendering marker.", family_html)

            dated = copy.deepcopy(family)
            dated["service"]["date"] = "2026-10-04"
            dated["liturgy"] = {"part_selections": {"prayers-of-the-people": "dated-prayers"}}
            dated_result = produce(church, dated)
            self.assertEqual(dated_result["status"], "ready_for_review", dated_result)
            dated_html = self._html(dated_result)
            self.assertIn("Dated prayer rendering marker.", dated_html)
            self.assertNotIn("Family prayer rendering marker.", dated_html)
            for rendered in (sunday_html, family_html, dated_html):
                self.assertIn("reusable welcome marker.", rendered)

    def test_shared_part_update_preserves_approved_artifacts_and_changes_next_occurrence(self) -> None:
        from tests.test_service_occurrences import _approve
        from skills.onboarding.scripts.church_setup import update_standing
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            self._configure_catalog(church)
            request = bulletin_input()
            request["liturgy"] = {}
            first = produce(church, request)
            self.assertEqual(first["status"], "ready_for_review", first)
            self.assertEqual(_approve(first)["status"], "approved")
            package = Path(first["week_folder"])
            before = {path: path.read_bytes() for path in package.iterdir() if path.is_file()}
            replacement = self._part(church, "welcome-updated.md", "# Communion Welcome\n\nUpdated shared welcome marker.\n")
            saved = update_standing(church, {"worship_profile": {"catalog": {"parts": {"welcome": {"file": replacement}}}}})
            self.assertEqual(saved["affected_services"], ["family", "sunday"])
            self.assertEqual(before, {path: path.read_bytes() for path in before})
            request["service"]["date"] = "2026-09-27"
            second = produce(church, request)
            self.assertEqual(second["status"], "ready_for_review", second)
            self.assertIn("Updated shared welcome marker.", self._html(second))
            self.assertNotIn("reusable welcome marker.", self._html(second))

    def test_lutheran_catalog_parts_render_the_required_units(self) -> None:
        from tests.test_first_time_flow import local_lutheran_sources
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            files = local_lutheran_sources(church)
            profile = {"status": "confirmed", "tradition_pack": "lutheran-elca-elw",
                       "defaults": {"eucharistic_prayer": "local", "lords_prayer": "custom", "blessing": "omit"},
                       "catalog": {"schema_version": 1, "default_service": "sunday",
                                   "services": {"sunday": {"name": "Sunday Communion"}},
                                   "parts": {key: {"name": key, "unit": key, "file": value} for key, value in files.items()},
                                   "part_selections": {key: key for key in files}}}
            (church / "worship/profile.yaml").write_text(yaml.safe_dump(profile))
            request = bulletin_input()
            request["liturgy"] = {}
            result = produce(church, request)
            self.assertEqual(result["status"], "ready_for_review", result)
            html = self._html(result)
            self.assertIn("Local Lutheran Great Thanksgiving text.", html)
            self.assertIn("Local Holy Communion invitation", html)

    def test_dated_omission_survives_revision_then_can_restore_the_part(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            self._configure_catalog(church)
            request = bulletin_input()
            request["liturgy"] = {"part_selections": {"communion_welcome": "omit"}}
            first = produce(church, request)
            self.assertEqual(first["status"], "ready_for_review", first)
            self.assertNotIn("reusable welcome marker.", self._html(first))
            second = revise(church, first["receipt_path"], {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(second["status"], "ready_for_review", second)
            self.assertNotIn("reusable welcome marker.", self._html(second))
            third = revise(church, second["receipt_path"], {"liturgy": {"part_selections": {"communion_welcome": "welcome"}}})
            self.assertEqual(third["status"], "ready_for_review", third)
            self.assertIn("reusable welcome marker.", self._html(third))

    def test_dated_part_survives_revision_and_can_be_changed_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            self._configure_catalog(church)
            request = bulletin_input()
            request["service"]["service_id"] = "family"
            request["liturgy"] = {"part_selections": {"prayers-of-the-people": "dated-prayers"}}
            first = produce(church, request)
            self.assertEqual(first["status"], "ready_for_review", first)
            second = revise(church, first["receipt_path"], {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(second["status"], "ready_for_review", second)
            self.assertIn("Dated prayer rendering marker.", self._html(second))
            third = revise(church, second["receipt_path"], {"liturgy": {"part_selections": {"prayers-of-the-people": "shared-prayers"}}})
            self.assertEqual(third["status"], "ready_for_review", third)
            self.assertIn("Shared prayer rendering marker.", self._html(third))
            self.assertNotIn("Dated prayer rendering marker.", self._html(third))

    def test_catalog_prayer_file_uses_hyphenated_unit_key_in_episcopal_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            self._configure_catalog(church)
            request = bulletin_input()
            request["service"]["service_id"] = "sunday"
            request["liturgy"] = {}

            result = produce(church, request)
            self.assertEqual(result["status"], "ready_for_review", result)
            html = self._html(result)
            self.assertEqual(html.count("Shared prayer rendering marker."), 1)


if __name__ == "__main__":
    unittest.main()
