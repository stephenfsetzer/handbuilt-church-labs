from __future__ import annotations

import json
import tempfile
import unittest
from tests.helpers import verify_liturgy_source
from pathlib import Path

from skills.bulletin.worship_resolution import WorshipResolutionError, resolve_profile_data, resolve_worship_profile


EPISCOPAL_PACK = {
    "id": "episcopal-bcp-rite-ii",
    "family": "Anglican",
    "denomination": "Episcopal",
    "service_book": "Book of Common Prayer 1979",
    "rite": "Rite II",
    "choices": {
        "eucharistic_prayer": {"values": ["A", "B", "C", "D"]},
        "lords_prayer": {"values": ["traditional", "contemporary"]},
    },
}


class WorshipResolutionTest(unittest.TestCase):
    def test_reading_flags_default_true_and_weekly_override_is_local(self) -> None:
        profile = {
            "status": "confirmed",
            "tradition_pack": "episcopal-bcp-rite-ii",
            "defaults": {"eucharistic_prayer": "A", "lords_prayer": "traditional"},
        }
        result = resolve_profile_data(profile, EPISCOPAL_PACK, {"liturgy": {"include_second_reading": False}})
        self.assertTrue(result["liturgy"]["include_first_reading"])
        self.assertFalse(result["liturgy"]["include_second_reading"])
        self.assertNotIn("include_second_reading", profile["defaults"])

    def test_both_reading_flags_disabled_are_rejected(self) -> None:
        with self.assertRaisesRegex(WorshipResolutionError, "At least one non-Gospel"):
            resolve_profile_data(
                {"defaults": {"eucharistic_prayer": "A", "lords_prayer": "traditional",
                               "include_first_reading": False, "include_second_reading": False}},
                EPISCOPAL_PACK,
            )

    def test_standing_defaults_merge_with_weekly_overrides(self) -> None:
        result = resolve_profile_data(
            {
                "status": "confirmed",
                "tradition_pack": "episcopal-bcp-rite-ii",
                "tradition": {"family": "Anglican", "denomination": "Episcopal"},
                "defaults": {"eucharistic_prayer": "A", "lords_prayer": "traditional", "blessing": "omit"},
                "sources": {"eucharistic_prayer": "profile review"},
                "provenance": {"last_reviewed_on": "2026-08-28"},
            },
            EPISCOPAL_PACK,
            {"liturgy": {"eucharistic_prayer": "B"}},
        )
        self.assertEqual(result["liturgy"]["eucharistic_prayer"], "B")
        self.assertEqual(result["liturgy"]["lords_prayer"], "traditional")
        self.assertEqual(result["unresolved"], [])
        self.assertTrue(result["provenance"]["weekly_override_supplied"])
        self.assertEqual(result["liturgy"]["worship_profile_ref"], "worship/profile.yaml")

    def test_blank_required_choice_is_reviewable_unresolved_state(self) -> None:
        result = resolve_profile_data(
            {
                "status": "needs_onboarding",
                "tradition_pack": "episcopal-bcp-rite-ii",
                "defaults": {"eucharistic_prayer": "", "lords_prayer": "", "blessing": ""},
            },
            EPISCOPAL_PACK,
        )
        self.assertEqual(
            {item["field"] for item in result["unresolved"]},
            {"liturgy.eucharistic_prayer", "liturgy.lords_prayer"},
        )
        self.assertEqual(result["liturgy"]["blessing"], "general-blessing")

    def test_blank_blessing_uses_the_general_default(self) -> None:
        result = resolve_profile_data(
            {
                "tradition_pack": "episcopal-bcp-rite-ii",
                "defaults": {
                    "eucharistic_prayer": "A",
                    "lords_prayer": "traditional",
                    "blessing": "",
                },
            },
            EPISCOPAL_PACK,
        )
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["liturgy"]["blessing"], "general-blessing")

    def test_missing_blessing_uses_the_general_default(self) -> None:
        result = resolve_profile_data(
            {
                "tradition_pack": "episcopal-bcp-rite-ii",
                "defaults": {"eucharistic_prayer": "A", "lords_prayer": "traditional"},
            },
            EPISCOPAL_PACK,
        )
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["liturgy"]["blessing"], "general-blessing")

    def test_blessing_omit_is_an_explicit_resolved_choice(self) -> None:
        result = resolve_profile_data(
            {
                "tradition_pack": "episcopal-bcp-rite-ii",
                "defaults": {
                    "eucharistic_prayer": "A",
                    "lords_prayer": "traditional",
                    "blessing": "omit",
                },
            },
            EPISCOPAL_PACK,
        )
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["liturgy"]["blessing"], "omit")
        self.assertEqual(result["liturgy"]["sources"], {})

    def test_choice_outside_tradition_pack_is_blocked(self) -> None:
        with self.assertRaises(WorshipResolutionError) as caught:
            resolve_profile_data(
                {
                    "tradition_pack": "episcopal-bcp-rite-ii",
                    "defaults": {"eucharistic_prayer": "Setting One", "lords_prayer": "traditional", "blessing": "omit"},
                },
                EPISCOPAL_PACK,
            )
        self.assertEqual(caught.exception.code, "unsupported_choice")
        self.assertEqual(caught.exception.field, "liturgy.eucharistic_prayer")

    def _church_with_profile(self, root: Path, profile: str, orders: dict[str, str]) -> Path:
        church = root / "synthetic-parish"
        (church / "worship" / "orders").mkdir(parents=True)
        (church / "church.yaml").write_text("worship_profile: worship/profile.yaml\n", encoding="utf-8")
        (church / "brand.json").write_text(json.dumps({"church": {}}), encoding="utf-8")
        (church / "worship" / "profile.yaml").write_text(profile, encoding="utf-8")
        for name, content in orders.items():
            (church / "worship" / "orders" / name).write_text(content, encoding="utf-8")
        return church

    def test_variant_resolves_private_order_base_first_and_child_last(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  ordinary:
    name: Synthetic ordinary variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/ordinary.yaml
    confirmation_policy: ask_each_week
  festival:
    name: Synthetic festival variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/festival.yaml
    confirmation_policy: scheduled
"""
        orders = {
            "ordinary.yaml": "replace:\n  - unit: prayers-of-the-people\n    with: [local-prayers]\ninsert:\n  - after: peace\n    units: [local-greeting]\n",
            "festival.yaml": "extends: ordinary\nreplace:\n  - unit: prayers-of-the-people\n    with: [festival-prayers]\ninsert:\n  - after: peace\n    units: [festival-hymn]\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = resolve_worship_profile(
                self._church_with_profile(Path(tmp), profile, orders),
                {"service": {"variant": "festival"}},
            )
        variant = result["liturgy"]["service_variant"]
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(variant["name"], "Synthetic festival variation")
        self.assertEqual(variant["replace"], [{"unit": "prayers-of-the-people", "with": ["festival-prayers"]}])
        self.assertEqual(variant["insert"], [{"after": "peace", "units": ["local-greeting", "festival-hymn"]}])
        self.assertEqual(result["liturgy"]["worship_profile_ref"], "worship/profile.yaml")
        self.assertEqual(
            result["liturgy"]["service_variant_provenance"],
            {
                "variant_id": "festival",
                "order_file_chain": ["worship/orders/ordinary.yaml", "worship/orders/festival.yaml"],
                "confirmation_policy": "scheduled",
            },
        )

    def test_explicit_none_confirms_the_ordinary_service(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  local:
    name: Synthetic local variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/local.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {"local.yaml": "{}\n"})
            result = resolve_worship_profile(church, {"service": {"variant": "none"}})
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["liturgy"]["service_variant"]["id"], "none")
        self.assertEqual(result["liturgy"]["service_variant"]["replace"], [])
        self.assertEqual(result["liturgy"]["service_variant_provenance"]["order_file_chain"], [])

    def test_variant_configuration_requires_an_explicit_weekly_selection(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  local:
    name: Synthetic local variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/local.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {"local.yaml": "{}\n"})
            result = resolve_worship_profile(church)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["unresolved"][0]["field"], "service.variant")

    def test_standing_only_does_not_require_a_weekly_variant_selection(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  local:
    name: Synthetic local variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/local.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {"local.yaml": "{}\n"})
            standing = resolve_worship_profile(church, standing_only=True)
            self.assertEqual(standing["status"], "resolved")
            self.assertEqual(standing["unresolved"], [])
            self.assertTrue(standing["service_variant_pending"])

            weekly = resolve_worship_profile(church)
            self.assertEqual(weekly["status"], "needs_input")
            self.assertEqual(weekly["unresolved"][0]["field"], "service.variant")
            self.assertTrue(weekly["service_variant_pending"])

            selected = resolve_worship_profile(church, {"service": {"variant": "local"}}, standing_only=True)
            self.assertEqual(selected["status"], "resolved")
            self.assertFalse(selected["service_variant_pending"])

    def test_variant_files_merge_into_liturgy_files_for_staging(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  local:
    name: Synthetic local variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/local.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church = self._church_with_profile(root, profile, {
                "local.yaml": "files:\n  local-unit: worship/liturgy/local-unit.md\n",
            })
            source = church / "worship" / "liturgy" / "local-unit.md"
            source.parent.mkdir(parents=True)
            source.write_text("Synthetic private liturgy unit.\n", encoding="utf-8")
            verify_liturgy_source(church, source)
            result = resolve_worship_profile(church, {"service": {"variant": "local"}})
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["liturgy"]["files"], {"local-unit": "worship/liturgy/local-unit.md"})

    def test_variant_cycle_is_needs_input(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  first:
    name: First variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/first.yaml
    confirmation_policy: ask_each_week
  second:
    name: Second variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/second.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {
                "first.yaml": "extends: second\n",
                "second.yaml": "extends: first\n",
            })
            result = resolve_worship_profile(church, {"service": {"variant": "first"}})
        self.assertEqual(result["unresolved"][0]["field"], "service.variant")
        self.assertIn("cyclically", result["unresolved"][0]["reason"])

    def test_variant_failures_are_needs_input_with_actionable_reason(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  unsafe:
    name: Unsafe variation
    base_service_plan: episcopal-rite-ii
    order_file: ../outside.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {})
            result = resolve_worship_profile(church, {"service": {"variant": "missing"}})
            self.assertEqual(result["status"], "needs_input")
            self.assertEqual(result["unresolved"][0]["field"], "service.variant")
            self.assertIn("Unknown service variant", result["unresolved"][0]["reason"])
            result = resolve_worship_profile(church, {"service": {"variant": "unsafe"}})
            self.assertEqual(result["unresolved"][0]["field"], "service.variant")
            self.assertIn("inside the church folder", result["unresolved"][0]["reason"])

    def test_variant_base_service_plan_mismatch_is_needs_input(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  lutheran:
    name: Wrong plan variation
    base_service_plan: lutheran-holy-communion
    order_file: worship/orders/wrong.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {"wrong.yaml": "{}\n"})
            result = resolve_worship_profile(church, {"service": {"variant": "lutheran"}})
        self.assertEqual(result["unresolved"][0]["field"], "service.variant")
        self.assertIn("service plan", result["unresolved"][0]["reason"])

    def test_unknown_service_plan_anchor_is_needs_input(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: omit
service_variants:
  local:
    name: Invalid anchor variation
    base_service_plan: episcopal-rite-ii
    order_file: worship/orders/local.yaml
    confirmation_policy: ask_each_week
"""
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_profile(Path(tmp), profile, {
                "local.yaml": "replace:\n  - unit: unknown-anchor\n    with: [local-unit]\n",
            })
            result = resolve_worship_profile(church, {"service": {"variant": "local"}})
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("Unknown replace anchor", result["unresolved"][0]["reason"])

    def test_profile_blessing_source_is_merged_for_private_staging(self) -> None:
        profile = """
schema_version: 1
status: confirmed
tradition_pack: episcopal-bcp-rite-ii
defaults:
  eucharistic_prayer: A
  lords_prayer: traditional
  prayers_of_the_people: III
  blessing: local-blessing
sources:
  blessing: worship/liturgy/blessing.md
service_variants: {}
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church = self._church_with_profile(root, profile, {})
            source = church / "worship" / "liturgy" / "blessing.md"
            source.parent.mkdir(parents=True)
            source.write_text("Synthetic licensed blessing.\n", encoding="utf-8")
            verify_liturgy_source(church, source)
            result = resolve_worship_profile(church)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["liturgy"]["sources"]["blessing"], "worship/liturgy/blessing.md")


if __name__ == "__main__":
    unittest.main()
