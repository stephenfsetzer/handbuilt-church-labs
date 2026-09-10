from __future__ import annotations

import json
import tempfile
import unittest
from tests.helpers import verify_liturgy_source
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from skills.bulletin.bulletin_production.interface import (
    StageFailure,
    _booklet_signature,
    _copy_music_assets,
    _copy_liturgy_sources,
    _authority_fingerprint,
    _validate_brand_asset_paths,
    _history_entry,
    _load_church_configuration,
    _resolve_standing_preferences,
    _stage_effective_brand,
    _validate_back_page_merge,
    _validate_bulletin,
    _validate_leadership,
    _validate_lyric_layout,
    _validate_qr,
    _validate_service_variant,
    produce,
)
from tests.helpers import bulletin_input, make_church


class BulletinProductionPromotionTest(unittest.TestCase):
    def test_private_lyrics_do_not_trigger_a_missing_music_image_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            stage.mkdir()
            warnings: list[dict] = []
            bulletin = {"hymns": {"closing": {
                "title": "Synthetic Closing Song",
                "lyrics": [{"part": "All", "lines": ["Walk in hope"]}],
            }}}
            _copy_music_assets(bulletin, Path(tmp), stage, warnings)
            self.assertEqual(warnings, [])

    def test_effective_brand_merges_confirmed_leadership_without_touching_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            original_church = (church / "church.yaml").read_text(encoding="utf-8")
            original_brand = (church / "brand.json").read_text(encoding="utf-8")
            (church / "church.yaml").write_text(
                original_church
                + "\nleadership:\n  print_in_bulletin: true\n  governing_body:\n    label: Council\n    members:\n      - name: Ada Example\n        role: Member\n",
                encoding="utf-8",
            )
            config, brand = _load_church_configuration(church)
            stage = church / "stage"
            stage.mkdir()
            staged = _stage_effective_brand(brand, config, church, stage)
            self.assertEqual(json.loads(staged.read_text(encoding="utf-8"))["leadership"]["governing_body"]["label"], "Council")
            self.assertNotIn("leadership", json.loads(original_brand))
            self.assertEqual((church / "brand.json").read_text(encoding="utf-8"), original_brand)

    def test_effective_brand_excludes_yaml_confirmation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            stage.mkdir()
            staged = _stage_effective_brand(
                {"church": {"name": "Synthetic"}},
                {"leadership": {
                    "print_in_bulletin": True,
                    "last_confirmed": date(2026, 9, 1),
                    "clergy_and_staff": [{"name": "Alex", "role": "Pastor"}],
                    "governing_body": {"label": "Council", "members": []},
                }},
                root,
                stage,
            )
            effective = json.loads(staged.read_text(encoding="utf-8"))
            self.assertNotIn("last_confirmed", effective["leadership"])

    def test_effective_brand_removes_stale_brand_leadership_and_stages_footer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config, brand = _load_church_configuration(church)
            brand["leadership"] = {"name": "stale"}
            config["bulletin"] = {"footer": {
                "contact_name": "Synthetic Contact",
                "address": "1 Test Lane",
                "phone": "555-0100",
                "email": "contact@test.invalid",
                "website": "https://test.invalid",
            }}
            stage = church / "stage"
            stage.mkdir()
            staged = _stage_effective_brand(brand, config, church, stage)
            effective = json.loads(staged.read_text(encoding="utf-8"))
            self.assertNotIn("leadership", effective)
            self.assertEqual(effective["bulletin_footer"]["contact_name"], "Synthetic Contact")
            self.assertEqual(brand["leadership"]["name"], "stale")

    def test_staged_service_time_does_not_guess_among_several_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config, brand = _load_church_configuration(church)
            config["church"]["regular_services"] = [
                {"day": "Sunday", "time": "9:00"},
                {"day": "Sunday", "time": "11:15"},
            ]
            multiple = church / "stage-multiple"
            multiple.mkdir()
            staged = _stage_effective_brand(brand, config, church, multiple)
            effective = json.loads(staged.read_text(encoding="utf-8"))
            self.assertEqual(effective["church"]["service_time"], "")

            config["church"]["regular_services"] = [{"day": "Sunday", "time": "9:00"}]
            single = church / "stage-single"
            single.mkdir()
            staged_single = _stage_effective_brand(brand, config, church, single)
            effective_single = json.loads(staged_single.read_text(encoding="utf-8"))
            self.assertEqual(effective_single["church"]["service_time"], "9:00")

    def test_footer_must_be_a_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config, brand = _load_church_configuration(church)
            config["bulletin"] = {"footer": "not a mapping"}
            with self.assertRaises(StageFailure) as caught:
                _stage_effective_brand(brand, config, church, church / "stage")
            self.assertEqual(caught.exception.code, "invalid_bulletin_footer")

    def test_church_owned_blessing_source_updates_renderer_file_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            source = church / "worship" / "liturgy" / "blessing.md"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# Local Blessing\n\nMay this synthetic community go in peace.\n", encoding="utf-8")
            verify_liturgy_source(church, source)
            bulletin = {"liturgy": {
                "blessing": "local-blessing",
                "eucharistic_prayer": "A",
                "sources": {"blessing": "worship/liturgy/blessing.md"},
            }}
            stage = church / "stage"
            stage.mkdir()
            staged = _copy_liturgy_sources(bulletin, church, stage)
            self.assertIsNotNone(staged)
            self.assertEqual(bulletin["liturgy"]["files"]["blessing"], "local-blessing")
            self.assertEqual((staged / "local-blessing.md").read_text(encoding="utf-8").splitlines()[2], "May this synthetic community go in peace.")

            ep_source = church / "worship" / "liturgy" / "thanksgiving.md"
            ep_source.write_text("# Local Thanksgiving\n\nSynthetic thanksgiving.\n", encoding="utf-8")
            verify_liturgy_source(church, ep_source)
            ep_bulletin = {"liturgy": {
                "eucharistic_prayer": "A",
                "sources": {"eucharistic_prayer": "worship/liturgy/thanksgiving.md"},
            }}
            ep_stage = church / "ep-stage"
            ep_stage.mkdir()
            _copy_liturgy_sources(ep_bulletin, church, ep_stage)
            self.assertEqual(ep_bulletin["liturgy"]["files"]["eucharistic-prayer-a"], "A")

    def test_standing_preferences_fill_only_missing_weekly_options(self) -> None:
        config = {"bulletin": {"defaults": {"include_serving_today": False, "serving_roles": ["Reader"]}}}
        weekly = {"options": {"include_serving_today": True}}
        _resolve_standing_preferences(weekly, config)
        self.assertTrue(weekly["options"]["include_serving_today"])
        self.assertEqual(weekly["options"]["serving_roles"], ["Reader"])

    def test_actual_onboarding_brand_with_deferred_qr_produces_a_review_package(self) -> None:
        # The normal fixture uses a minimal brand and previously hid the
        # scaffold's explanatory QR comment from production validation.
        from tests.helpers import REPO_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            brand = json.loads((REPO_ROOT / "scaffold/church-folder/brand.json").read_text())
            brand["logo_status"] = "none"
            brand["colors_status"] = "neutral"
            (church / "brand.json").write_text(json.dumps(brand))
            before = (church / "brand.json").read_bytes()
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "ready_for_review", result)
            self.assertEqual((church / "brand.json").read_bytes(), before)
            self.assertNotIn("qr_asset_missing", [item["code"] for item in result["warnings"]])

    def test_qr_blocks_unconfirmed_configuration_and_legacy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            warnings: list[dict] = []
            with self.assertRaises(StageFailure) as caught:
                _validate_qr(
                    {"qr": {"connect": {"image": "connect.png"}}}, root, warnings
                )
            self.assertEqual(caught.exception.code, "unresolved_qr_configuration")
            with self.assertRaises(StageFailure) as caught:
                _validate_qr({"qr": {"connect": "connect.png"}}, root, [])
            self.assertEqual(caught.exception.code, "unresolved_qr_configuration")
            _validate_qr(
                {"qr": {"connect": {"image": "connect.png", "url": "https://connect.invalid"},
                         "standard_copy_accepted": False,
                         "copy": {"heading": "Join us", "connect": {"heading": "Connect"}}}},
                root,
                [],
            )
            (root / "music").mkdir()
            (root / "music" / "connect.png").write_bytes(b"synthetic")
            warnings = []
            _validate_qr(
                {"qr": {"connect": {"image": "connect.png", "url": "https://connect.invalid"},
                         "standard_copy_accepted": True}},
                root,
                warnings,
            )
            self.assertEqual(warnings[0]["code"], "qr_asset_missing")

    def test_brand_assets_cannot_escape_the_church_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(StageFailure) as caught:
                _validate_brand_asset_paths({"logo": {"banner": "../outside.png"}}, root)
            self.assertEqual(caught.exception.code, "unsafe_path")

    def test_leadership_label_shape_and_capacity_fail_closed(self) -> None:
        with self.assertRaises(StageFailure) as caught:
            _validate_leadership({"leadership": {"print_in_bulletin": True, "officers": [{"name": "Ada", "role": "Warden"}]}})
        self.assertEqual(caught.exception.code, "unresolved_leadership_label")
        with self.assertRaises(StageFailure) as caught:
            _validate_leadership({"leadership": {"print_in_bulletin": True, "staff": ["Ada"]}})
        self.assertEqual(caught.exception.code, "invalid_leadership_entry")
        self.assertEqual(
            _validate_leadership({"leadership": {"staff": ["incomplete"]}})["printed"],
            False,
        )
        people = [{"name": f"Person {i}", "role": "Staff"} for i in range(10)]
        with self.assertRaises(StageFailure) as caught:
            _validate_leadership({"leadership": {"print_in_bulletin": True, "placement": "footer", "staff": people}})
        self.assertEqual(caught.exception.code, "leadership_roster_capacity")

    def test_leadership_placement_auto_flows_a_large_roster_to_the_body(self) -> None:
        small = [{"name": f"Person {i}", "role": "Staff"} for i in range(9)]
        small_result = _validate_leadership({"leadership": {"print_in_bulletin": True, "staff": small}})
        self.assertEqual(small_result["placement"], "footer")

        large = [{"name": f"Person {i}", "role": "Staff"} for i in range(35)]
        large_result = _validate_leadership({"leadership": {"print_in_bulletin": True, "staff": large}})
        self.assertEqual(large_result["placement"], "body")
        self.assertEqual(len(large_result["entries"]), 35)

        explicit_body = _validate_leadership(
            {"leadership": {"print_in_bulletin": True, "placement": "body", "staff": small}}
        )
        self.assertEqual(explicit_body["placement"], "body")

    def test_leadership_placement_rejects_an_unrecognized_value(self) -> None:
        with self.assertRaises(StageFailure) as caught:
            _validate_leadership({"leadership": {
                "print_in_bulletin": True, "placement": "sidebar",
                "staff": [{"name": "Ada", "role": "Staff"}],
            }})
        self.assertEqual(caught.exception.code, "invalid_leadership_placement")
        self.assertEqual(caught.exception.field, "leadership.placement")

    def test_private_lyrics_need_no_rights_metadata_but_validate_columns(self) -> None:
        _validate_lyric_layout({"hymns": {"closing": {"lyrics": []}}})
        _validate_lyric_layout(
            {"hymns": {"closing": {"lyrics": ["Synthetic private line"]}}},
        )
        with self.assertRaises(StageFailure) as caught:
            _validate_lyric_layout({"hymns": {"closing": {
                "lyrics": ["Synthetic private line"], "lyric_columns": 3,
            }}})
        self.assertEqual(caught.exception.code, "invalid_lyric_columns")

    def test_private_lyrics_need_no_labs_permission_fields(self) -> None:
        weekly = {"hymns": {"closing": {
            "lyrics": ["Synthetic private line"],
        }}}
        _validate_lyric_layout(weekly)

    def test_blessing_requires_resolved_text_or_explicit_omit(self) -> None:
        bulletin = bulletin_input()
        bulletin["liturgy"] = {"eucharistic_prayer": "A", "lords_prayer": "traditional"}
        with self.assertRaises(StageFailure) as caught:
            _validate_bulletin(bulletin)
        self.assertEqual(caught.exception.field, "liturgy.service_plan")
        bulletin["liturgy"]["service_plan"] = "episcopal-rite-ii"
        with self.assertRaises(StageFailure) as caught:
            _validate_bulletin(bulletin)
        self.assertEqual(caught.exception.code, "unresolved_blessing")
        bulletin["liturgy"]["blessing"] = "omit"
        _validate_bulletin(bulletin)

    def test_back_page_merge_rejects_image_closing_hymn(self) -> None:
        _validate_back_page_merge({"options": {"merge_back_page": True}, "hymns": {"closing": {
            "lyrics": [{"speaker": "People", "lines": ["Invented line"]}],
        }}})
        _validate_back_page_merge({"options": {"merge_back_page": True}, "hymns": {"closing": {
            "title": "Title only",
        }}})
        with self.assertRaises(StageFailure) as caught:
            _validate_back_page_merge({"options": {"merge_back_page": True}, "hymns": {"closing": {"image": "scan.png"}}})
        self.assertEqual(caught.exception.code, "back_page_merge_unsafe")

    def test_service_variant_provenance_blocks_bypass_and_accepts_safe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            order = root / "worship" / "variants" / "special.json"
            order.parent.mkdir(parents=True)
            order.write_text("{}", encoding="utf-8")
            base = {"liturgy": {"service_variant": {"id": "special"}}}
            with self.assertRaises(StageFailure) as caught:
                _validate_service_variant(base, root)
            self.assertEqual(caught.exception.code, "service_variant_provenance_required")
            safe = {"liturgy": {
                "worship_profile_ref": "worship/profile.yaml",
                "service_variant": {"id": "special"},
                "service_variant_provenance": {
                    "variant_id": "special",
                    "order_file_chain": ["worship/variants/special.json"],
                    "confirmation_policy": "ask_each_time",
                },
            }}
            _validate_service_variant(safe, root)
            for chain in (["/tmp/special.json"], ["worship/../special.json"], ["worship/variants/missing.json"]):
                unsafe = json.loads(json.dumps(safe))
                unsafe["liturgy"]["service_variant_provenance"]["order_file_chain"] = chain
                with self.assertRaises(StageFailure) as caught:
                    _validate_service_variant(unsafe, root)
                self.assertIn(caught.exception.code, {"unsafe_service_variant_path", "missing_service_variant_source"})
            none = {"liturgy": {
                "service_variant": {"id": "none"},
                "service_variant_provenance": {
                    "variant_id": "none", "order_file_chain": [], "confirmation_policy": "explicit_none",
                },
            }}
            _validate_service_variant(none, root)

    def test_authority_change_invalidates_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["liturgy"] = {"service_plan": "episcopal-rite-ii", "blessing": "A synthetic blessing."}

            def fake_run(command, *, stage, env=None, reject_warnings=False):
                if stage == "render":
                    output = Path(command[command.index("--out") + 1])
                    (output / "bulletin-2026-09-20-classic.html").write_text("synthetic", encoding="utf-8")
                    writer = PdfWriter()
                    for _ in range(4):
                        writer.add_blank_page(width=612, height=792)
                    writer.write(str(output / "bulletin-2026-09-20-classic.pdf"))
                elif stage == "imposition":
                    writer = PdfWriter()
                    for _ in range(2):
                        writer.add_blank_page(width=1224, height=792)
                    writer.write(str(command[-1]))
                return ""

            with patch("skills.bulletin.bulletin_production.interface._run", fake_run), patch(
                "skills.bulletin.bulletin_production.interface._quality_gate", lambda *args: []
            ):
                first = produce(church, bulletin)
                self.assertEqual(first["status"], "ready_for_review")
                (church / "church.yaml").write_text(
                    (church / "church.yaml").read_text(encoding="utf-8") + "\n# authority changed\n",
                    encoding="utf-8",
                )
                second = produce(church, bulletin)
            self.assertEqual(second["status"], "blocked")
            self.assertEqual(second["errors"][0]["code"], "existing_run_conflict")

    def test_booklet_signature_is_derived_from_verified_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequential = root / "sequential.pdf"
            booklet = root / "booklet.pdf"
            writer = PdfWriter()
            for _ in range(5):
                writer.add_blank_page(width=612, height=792)
            with sequential.open("wb") as handle:
                writer.write(handle)
            writer = PdfWriter()
            for _ in range(4):
                writer.add_blank_page(width=1224, height=792)
            with booklet.open("wb") as handle:
                writer.write(handle)
            signature = _booklet_signature(sequential, booklet)
            self.assertEqual(signature["sequential_pages"], 5)
            self.assertEqual(signature["padded_pages"], 8)
            self.assertEqual(signature["sheet_count_11x17"], 2)
            self.assertEqual(signature["blank_pages"], 3)

    def test_service_variant_provenance_reaches_approved_history(self) -> None:
        config = {
            "service": {"date": "2026-09-20"},
            "readings": {},
            "liturgy": {
                "service_variant": {
                    "id": "synthetic-special",
                    "title": "Synthetic Special",
                    "base_service": "episcopal-rite-ii",
                },
                "service_variant_provenance": {
                    "variant_id": "synthetic-special",
                    "order_file_chain": ["worship/variants/synthetic-special.json"],
                    "confirmation_policy": "confirmed_weekly_resolution",
                    "source": "church-owned weekly resolution",
                },
            },
        }
        history = _history_entry(config, {"artifacts": [{"role": "sequential_pdf", "path": "bulletin-2026-09-20-classic.pdf"}], "run_id": "run"}, "approval")
        self.assertEqual(history["service_variant"]["id"], "synthetic-special")
        self.assertEqual(history["service_variant_provenance"]["source"], "church-owned weekly resolution")


if __name__ == "__main__":
    unittest.main()
