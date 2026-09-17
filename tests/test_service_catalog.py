from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from skills.bulletin.service_catalog import ServiceCatalogError, validate_catalog
from skills.bulletin.worship_resolution import WorshipResolutionError, resolve_worship_profile
from tests.helpers import make_church, verify_liturgy_source


class ServiceCatalogTest(unittest.TestCase):
    def _church(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        church = make_church(Path(temporary.name))
        for name in ("ordinary-creed", "family-creed"):
            path = church / "worship" / "liturgy" / f"{name}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Synthetic {name}.\n", encoding="utf-8")
            verify_liturgy_source(church, path)
        return temporary, church

    def _profile(self) -> dict:
        return {
            "schema_version": 1,
            "status": "confirmed",
            "tradition_pack": "episcopal-bcp-rite-ii",
            "defaults": {"eucharistic_prayer": "A", "lords_prayer": "traditional", "prayers_of_the_people": "III", "blessing": "omit"},
            "catalog": {
                "schema_version": 1,
                "default_service": "ordinary",
                "parts": {
                    "ordinary-creed": {"name": "Ordinary Creed", "unit": "nicene-creed", "file": "worship/liturgy/ordinary-creed.md"},
                    "family-creed": {"name": "Family Creed", "unit": "nicene-creed", "file": "worship/liturgy/family-creed.md"},
                },
                "part_selections": {"nicene-creed": "ordinary-creed"},
                "services": {
                    "ordinary": {"name": "Sunday Eucharist", "time": "10:00", "part_selections": {}},
                    "family": {"name": "Family Eucharist", "display_name": "Family service", "part_selections": {"nicene-creed": "family-creed"}},
                },
            },
        }

    def _write_profile(self, church: Path, profile: dict) -> None:
        import yaml
        (church / "worship" / "profile.yaml").write_text(yaml.safe_dump(profile), encoding="utf-8")

    def test_shared_parts_resolve_per_service_and_weekly_reversion(self) -> None:
        temporary, church = self._church()
        with temporary:
            self._write_profile(church, self._profile())
            ordinary = resolve_worship_profile(church)
            family = resolve_worship_profile(church, {"service": {"service_id": "family"}})
            weekly = resolve_worship_profile(church, {"service": {"service_id": "family"}, "liturgy": {"part_selections": {"nicene-creed": "ordinary-creed"}}})
            reverted = resolve_worship_profile(church, {"service": {"service_id": "family"}})
        self.assertEqual(ordinary["parts"]["nicene-creed"]["id"], "ordinary-creed")
        self.assertEqual(family["parts"]["nicene-creed"]["id"], "family-creed")
        self.assertEqual(weekly["parts"]["nicene-creed"]["id"], "ordinary-creed")
        self.assertEqual(reverted["parts"]["nicene-creed"]["id"], "family-creed")
        self.assertEqual(family["choice_origins"]["liturgy.part_selections.nicene-creed"], "service")
        self.assertEqual(family["service_context"]["display_name"], "Family service")

    def test_rename_preserves_part_identity(self) -> None:
        profile = self._profile()
        profile["catalog"]["parts"]["ordinary-creed"]["name"] = "Creed used at Sunday Eucharist"
        normalized = validate_catalog(profile)
        self.assertIn("ordinary-creed", normalized["parts"])
        self.assertEqual(normalized["parts"]["ordinary-creed"]["name"], "Creed used at Sunday Eucharist")

    def test_missing_service_selection_is_needs_input_but_standing_checks_catalog(self) -> None:
        temporary, church = self._church()
        with temporary:
            profile = self._profile()
            profile["catalog"].pop("default_service")
            self._write_profile(church, profile)
            weekly = resolve_worship_profile(church)
            standing = resolve_worship_profile(church, standing_only=True)
        self.assertEqual(weekly["status"], "needs_input")
        self.assertEqual(weekly["unresolved"][-1]["field"], "service.service_id")
        self.assertEqual(standing["status"], "resolved")

    def test_missing_refs_wrong_unit_unsafe_path_and_stale_source_are_rejected(self) -> None:
        profile = self._profile()
        invalid = copy.deepcopy(profile)
        invalid["catalog"]["services"]["ordinary"]["part_selections"] = {"nicene-creed": "missing"}
        with self.assertRaises(ServiceCatalogError) as caught:
            validate_catalog(invalid)
        self.assertEqual(caught.exception.code, "catalog_unknown_part")
        invalid = copy.deepcopy(profile)
        invalid["catalog"]["services"]["ordinary"]["part_selections"] = {"confession-of-sin": "ordinary-creed"}
        with self.assertRaises(ServiceCatalogError) as caught:
            validate_catalog(invalid)
        self.assertEqual(caught.exception.code, "catalog_part_unit_mismatch")
        invalid = copy.deepcopy(profile)
        invalid["catalog"]["parts"]["ordinary-creed"]["file"] = "../outside.md"
        with self.assertRaises(ServiceCatalogError) as caught:
            validate_catalog(invalid)
        self.assertEqual(caught.exception.code, "unsafe_path")
        temporary, church = self._church()
        with temporary:
            path = church / "worship" / "liturgy" / "ordinary-creed.md"
            path.write_text("Changed after verification.\n", encoding="utf-8")
            with self.assertRaises(ServiceCatalogError) as caught:
                validate_catalog(profile, church_root=church)
        self.assertEqual(caught.exception.code, "catalog_unverified_source")

    def test_explicit_optional_omission_and_legacy_compatibility(self) -> None:
        temporary, church = self._church()
        with temporary:
            profile = self._profile()
            self._write_profile(church, profile)
            omitted = resolve_worship_profile(church, {"liturgy": {"part_selections": {"nicene-creed": "omit", "communion_welcome": "omit"}}})
            legacy = copy.deepcopy(profile)
            legacy.pop("catalog")
            self._write_profile(church, legacy)
            old = resolve_worship_profile(church)
        self.assertIn("nicene-creed", omitted["liturgy"]["omitted_units"])
        self.assertEqual(omitted["liturgy"]["communion_welcome"], "")
        self.assertEqual(old["service_context"], {"service_id": "ordinary", "name": "Ordinary service", "occurrence_id": "main", "catalog_version": None, "legacy": True})

    def test_required_unit_cannot_be_omitted(self) -> None:
        profile = self._profile()
        profile["catalog"]["part_selections"] = {"opening-acclamation": "omit"}
        with self.assertRaises(ServiceCatalogError) as caught:
            validate_catalog(profile)
        self.assertEqual(caught.exception.code, "catalog_required_unit")

    def test_blank_legacy_sources_remain_valid_with_a_catalog(self) -> None:
        profile = self._profile()
        profile["sources"] = {"eucharistic_prayer": "", "blessing": ""}
        self.assertIsNotNone(validate_catalog(profile))

    def test_none_default_variant_and_strict_identifiers(self) -> None:
        temporary, church = self._church()
        with temporary:
            profile = self._profile()
            profile["catalog"]["services"]["ordinary"]["default_variant"] = "none"
            self._write_profile(church, profile)
            resolved = resolve_worship_profile(church)
        self.assertEqual(resolved["liturgy"]["service_variant"]["id"], "none")
        for changed in (
            lambda item: item["catalog"].update(default_service=" ordinary "),
            lambda item: item["catalog"]["services"].__setitem__(1, item["catalog"]["services"].pop("ordinary")),
            lambda item: item["catalog"]["part_selections"].update({"nicene-creed": " ordinary-creed "}),
        ):
            with self.subTest(changed=changed):
                invalid = copy.deepcopy(self._profile())
                changed(invalid)
                with self.assertRaises(ServiceCatalogError) as caught:
                    validate_catalog(invalid)
                self.assertEqual(caught.exception.code, "catalog_invalid_id")

    def test_service_fields_are_typed_and_legacy_named_service_is_rejected(self) -> None:
        profile = self._profile()
        cases = {
            "defaults": {"eucharistic_prayer": ["A"]},
            "service_plan": ["episcopal-rite-ii"],
            "time": 1000,
            "display_name": "   ",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                invalid = copy.deepcopy(profile)
                invalid["catalog"]["services"]["ordinary"][field] = value
                with self.assertRaises(ServiceCatalogError):
                    validate_catalog(invalid)
        temporary, church = self._church()
        with temporary:
            legacy = self._profile()
            legacy.pop("catalog")
            self._write_profile(church, legacy)
            with self.assertRaisesRegex(Exception, "Legacy worship profiles support only"):
                resolve_worship_profile(church, {"service": {"service_id": "family"}})
            ordinary = resolve_worship_profile(church)
        self.assertTrue(ordinary["service_context"]["legacy"])

    def test_source_alias_conflict_and_parts_for_both_plans(self) -> None:
        invalid = self._profile()
        invalid["sources"] = {"prayers_of_the_people": "private-prayers"}
        invalid["catalog"]["parts"]["prayers"] = {
            "name": "Local prayers", "unit": "prayers-of-the-people", "file": "worship/liturgy/prayers.md",
        }
        invalid["catalog"]["part_selections"] = {"prayers-of-the-people": "prayers"}
        with self.assertRaises(ServiceCatalogError) as caught:
            validate_catalog(invalid)
        self.assertEqual(caught.exception.code, "catalog_layer_conflict")
        mixed = self._profile()
        mixed["catalog"]["parts"]["lutheran-gathering"] = {
            "name": "Lutheran Gathering", "unit": "gathering", "file": "worship/liturgy/gathering.md",
        }
        self.assertIsNotNone(validate_catalog(mixed))

    def test_higher_direct_source_beats_part_null_stops_omission_and_doxology_part_is_custom(self) -> None:
        temporary, church = self._church()
        with temporary:
            for name in ("part-prayer", "weekly-prayer", "doxology", "communion-welcome"):
                path = church / "worship" / "liturgy" / f"{name}.md"
                path.write_text(f"Synthetic {name}.\n", encoding="utf-8")
                verify_liturgy_source(church, path)
            profile = self._profile()
            profile["catalog"]["parts"].update({
                "part-prayer": {"name": "Part Prayer", "unit": "eucharistic-prayer", "file": "worship/liturgy/part-prayer.md"},
                "local-doxology": {"name": "Local Doxology", "unit": "doxology", "file": "worship/liturgy/doxology.md"},
                "local-communion-welcome": {"name": "Local Communion Welcome", "unit": "communion_welcome", "file": "worship/liturgy/communion-welcome.md"},
            })
            profile["catalog"]["part_selections"] = {"eucharistic-prayer": "part-prayer", "nicene-creed": "omit", "doxology": "local-doxology", "communion_welcome": "local-communion-welcome"}
            self._write_profile(church, profile)
            part_only = resolve_worship_profile(church)
            direct = resolve_worship_profile(church, {"liturgy": {"sources": {"eucharistic_prayer": "worship/liturgy/weekly-prayer.md"}}})
            unresolved = resolve_worship_profile(church, {"liturgy": {"part_selections": {"nicene-creed": None}}})
        self.assertEqual(part_only["status"], "resolved")
        self.assertEqual(part_only["liturgy"]["sources"]["eucharistic_prayer"], "worship/liturgy/part-prayer.md")
        self.assertNotIn("eucharistic-prayer", direct["parts"])
        self.assertEqual(direct["liturgy"]["sources"]["eucharistic_prayer"], "worship/liturgy/weekly-prayer.md")
        self.assertEqual(direct["liturgy"]["doxology"], "custom")
        self.assertEqual(direct["liturgy"]["files"]["doxology"], "worship/liturgy/doxology.md")
        self.assertEqual(direct["liturgy"]["communion_welcome"], "church-communion-welcome")
        self.assertEqual(direct["liturgy"]["files"]["communion_welcome"], "worship/liturgy/communion-welcome.md")
        self.assertNotIn("nicene-creed", unresolved["liturgy"].get("omitted_units", []))
        self.assertTrue(any(row["field"] == "liturgy.part_selections.nicene-creed" for row in unresolved["unresolved"]))

    def test_weekly_alias_conflicts_and_legacy_unknown_parts_are_rejected(self) -> None:
        temporary, church = self._church()
        with temporary:
            profile = self._profile()
            profile["catalog"]["parts"]["part-prayer"] = {
                "name": "Part Prayer", "unit": "eucharistic-prayer", "file": "worship/liturgy/ordinary-creed.md",
            }
            self._write_profile(church, profile)
            for direct in (
                {"sources": {"eucharistic_prayer": "worship/liturgy/ordinary-creed.md"}},
                {"files": {"eucharistic_prayer": "worship/liturgy/ordinary-creed.md"}},
            ):
                with self.subTest(direct=direct):
                    with self.assertRaises(WorshipResolutionError) as caught:
                        resolve_worship_profile(church, {"liturgy": {**direct, "part_selections": {"eucharistic-prayer": "part-prayer"}}})
                    self.assertEqual(caught.exception.code, "catalog_layer_conflict")
            legacy = self._profile()
            legacy.pop("catalog")
            self._write_profile(church, legacy)
            with self.assertRaises(WorshipResolutionError) as caught:
                resolve_worship_profile(church, {"liturgy": {"part_selections": {"unknown-unit": "anything"}}})
        self.assertEqual(caught.exception.code, "catalog_unknown_unit")

    def test_final_source_wins_and_resolved_liturgy_round_trips(self) -> None:
        temporary, church = self._church()
        with temporary:
            source = church / "worship" / "liturgy" / "weekly-prayer.md"
            source.write_text("Synthetic weekly prayer.\n", encoding="utf-8")
            verify_liturgy_source(church, source)
            profile = self._profile()
            profile["catalog"]["parts"]["part-prayer"] = {
                "name": "Part Prayer", "unit": "eucharistic-prayer", "file": "worship/liturgy/ordinary-creed.md",
            }
            profile["catalog"]["services"]["ordinary"]["part_selections"]["eucharistic-prayer"] = "part-prayer"
            # This stale source must not be reconsidered after the selected
            # verified part replaces it.
            profile["sources"] = {"eucharistic_prayer": "worship/liturgy/missing.md"}
            self._write_profile(church, profile)
            part = resolve_worship_profile(church)
            direct = resolve_worship_profile(church, {"liturgy": {"sources": {"eucharistic_prayer": "worship/liturgy/weekly-prayer.md"}}})
            round_trip = resolve_worship_profile(church, {"liturgy": part["liturgy"]})
        self.assertEqual(part["status"], "resolved")
        self.assertEqual(direct["status"], "resolved")
        self.assertNotIn("eucharistic-prayer", direct["liturgy"].get("files", {}))
        self.assertNotIn("eucharistic_prayer", direct["liturgy"].get("files", {}))
        self.assertEqual(direct["liturgy"]["sources"]["eucharistic_prayer"], "worship/liturgy/weekly-prayer.md")
        self.assertNotIn("part_selections", part["liturgy"])
        self.assertEqual(round_trip["status"], "resolved")

    def test_direct_verified_file_satisfies_choice_readiness(self) -> None:
        temporary, church = self._church()
        with temporary:
            profile = self._profile()
            profile["catalog"]["services"]["ordinary"]["files"] = {
                "eucharistic-prayer": "worship/liturgy/ordinary-creed.md",
            }
            self._write_profile(church, profile)
            resolved = resolve_worship_profile(church)
        self.assertEqual(resolved["status"], "resolved")

    def test_explicit_legacy_service_controls_history_inheritance(self) -> None:
        profile = self._profile()
        profile["catalog"]["legacy_service"] = "ordinary"
        self.assertEqual(validate_catalog(profile)["legacy_service"], "ordinary")
        for value, code in (("missing", "catalog_unknown_service"), (" ordinary ", "catalog_invalid_id"), (1, "catalog_invalid_id")):
            with self.subTest(value=value):
                invalid = copy.deepcopy(profile)
                invalid["catalog"]["legacy_service"] = value
                with self.assertRaises(ServiceCatalogError) as caught:
                    validate_catalog(invalid)
                self.assertEqual(caught.exception.code, code)
        temporary, church = self._church()
        with temporary:
            profile["catalog"]["services"]["ordinary"]["name"] = "Renamed Sunday Eucharist"
            self._write_profile(church, profile)
            ordinary = resolve_worship_profile(church)
            family = resolve_worship_profile(church, {"service": {"service_id": "family"}})
            second = resolve_worship_profile(church, {"service": {"occurrence_id": "evening"}})
        self.assertEqual(ordinary["service_context"]["service_id"], "ordinary")
        self.assertEqual(ordinary["service_context"]["name"], "Renamed Sunday Eucharist")
        self.assertTrue(ordinary["service_context"]["inherits_legacy_history"])
        self.assertFalse(family["service_context"]["inherits_legacy_history"])
        self.assertFalse(second["service_context"]["inherits_legacy_history"])


if __name__ == "__main__":
    unittest.main()
