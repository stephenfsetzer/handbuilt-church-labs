from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from weasyprint import HTML

from skills.onboarding.bulletin_import import import_bulletin
from skills.bulletin.source_inventory import (
    InventoryError, add_section, check_mapping_integrity, check_rendered_text,
    list_inventories, mark_review_complete, read_inventory, validate_for_production,
)
from tests.helpers import bulletin_input, make_church

SERVICE_DATE = "2026-09-20"


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.church = make_church(self.tmp)
        pdf_path = self.tmp / "bulletin.pdf"
        HTML(string="""
            <html><body>
              <p>Collect of the day printed text goes here for testing.</p>
              <p>A second page rubric.</p>
            </body></html>
        """).write_pdf(pdf_path)
        self.manifest = import_bulletin(self.church, pdf_path, original_filename="bulletin.pdf")
        self.import_id = self.manifest["import_id"]

    def _text_file(self, name: str, content: str) -> Path:
        path = self.church / "worship" / "liturgy" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    # -- basic informative check ---------------------------------------

    def test_check_mapping_integrity_with_no_imports_is_never_blocking(self):
        empty_church = make_church(self.tmp / "no-upload")
        result = check_mapping_integrity(empty_church)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["imports_checked"], 0)
        self.assertEqual(result["errors"], [])

    def test_unresolved_section_is_surfaced_not_an_error(self):
        add_section(
            self.church, self.import_id,
            section_id="collect-of-day", page_start=1,
            disposition="unresolved", scope="weekly", service_date=SERVICE_DATE,
            notes="Needs the pastor to confirm this is the standing collect.",
        )
        result = check_mapping_integrity(self.church, self.import_id)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(len(result["unresolved_sections"]), 1)

    def test_omitted_section_requires_a_reason(self):
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="unsupported-qr", page_start=1,
                disposition="omitted", scope="weekly", service_date=SERVICE_DATE,
                notes="",
            )
        add_section(
            self.church, self.import_id,
            section_id="unsupported-qr", page_start=1,
            disposition="omitted", scope="weekly", service_date=SERVICE_DATE,
            notes="Pastor approved dropping this element for the reflow layout.",
        )
        result = check_mapping_integrity(self.church, self.import_id)
        self.assertEqual(result["status"], "valid")

    def test_weekly_section_requires_service_date_standing_rejects_it(self):
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="weekly-no-date", page_start=1,
                disposition="unresolved", scope="weekly", notes="pending",
            )
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="standing-with-date", page_start=1,
                disposition="unresolved", scope="standing", service_date=SERVICE_DATE, notes="pending",
            )

    def test_mapped_text_file_must_exist(self):
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="collect-of-day", page_start=1,
                disposition="mapped", scope="standing",
                target={"text_file": "worship/liturgy/missing.txt"},
            )

    def test_mapped_text_file_hash_change_is_detected(self):
        text_path = self._text_file("collect.txt", "# Collect\n\nOriginal verified wording.\n")
        add_section(
            self.church, self.import_id,
            section_id="collect-of-day", page_start=1,
            disposition="mapped", scope="standing",
            target={"text_file": "worship/liturgy/collect.txt"},
        )
        self.assertEqual(check_mapping_integrity(self.church, self.import_id)["status"], "valid")
        text_path.write_text("# Collect\n\nSilently edited wording.\n", encoding="utf-8")
        result = check_mapping_integrity(self.church, self.import_id)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "text_changed")

    def test_source_hash_change_is_detected(self):
        add_section(
            self.church, self.import_id,
            section_id="page-1-note", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "church.name"},
        )
        source_pdf = self.church / self.manifest["source"]["path"]
        source_pdf.write_bytes(source_pdf.read_bytes() + b"\ncorrupted")
        result = check_mapping_integrity(self.church, self.import_id)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("source_changed", {e["code"] for e in result["errors"]})

    def test_list_inventories_includes_recorded_sections(self):
        add_section(
            self.church, self.import_id,
            section_id="collect-of-day", page_start=1,
            disposition="unresolved", scope="weekly", service_date=SERVICE_DATE,
        )
        inventories = list_inventories(self.church)
        self.assertEqual(len(inventories), 1)
        self.assertEqual(len(inventories[0]["sections"]), 1)

    def test_import_id_path_traversal_rejected(self):
        with self.assertRaises(InventoryError):
            read_inventory(self.church, "../../../../etc")

    # -- destination allowlist -------------------------------------------

    def test_config_path_rejects_made_up_destination_even_if_present_in_data(self):
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="bogus", page_start=1,
                disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
                target={"config_path": "liturgy.made_up"},
            )

    def test_config_path_rejects_fake_hymn_slot(self):
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="bogus-slot", page_start=1,
                disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
                target={"config_path": "hymns.made_up_slot.image"},
            )

    def test_reference_collection_ignores_a_fake_hymn_slot_key(self):
        asset_dir = self.church / "music"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "page.png"
        asset_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        add_section(
            self.church, self.import_id,
            section_id="music-page", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"asset_path": "music/page.png"},
        )
        bulletin = bulletin_input()
        # A made-up hymn slot key must not count as a reference just because
        # the path is present there -- only the renderer's five real slots do.
        bulletin["hymns"]["made_up_slot"] = {"image": "music/page.png"}
        result = validate_for_production(self.church, bulletin)
        self.assertIn("asset_not_referenced", {e["code"] for e in result["errors"]})

        del bulletin["hymns"]["made_up_slot"]
        bulletin["hymns"]["entrance"]["image"] = "music/page.png"
        result = validate_for_production(self.church, bulletin)
        self.assertNotIn("asset_not_referenced", {e["code"] for e in result["errors"]})

    def test_config_path_accepts_service_time_and_eucharistic_prayer(self):
        bulletin = bulletin_input()
        bulletin["service"]["time"] = "10:00 AM"
        bulletin["liturgy"]["eucharistic_prayer"] = "A"
        add_section(
            self.church, self.import_id,
            section_id="service-time", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"config_path": "service.time"},
        )
        add_section(
            self.church, self.import_id,
            section_id="eucharistic-prayer", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"config_path": "liturgy.eucharistic_prayer"},
        )
        result = validate_for_production(self.church, bulletin)
        codes = {e["code"] for e in result["errors"]}
        self.assertNotIn("config_path_not_found", codes)
        self.assertNotIn("unsupported_destination", codes)

    def test_config_path_accepts_standing_leadership_placement(self):
        add_section(
            self.church, self.import_id,
            section_id="roster-placement", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "leadership.placement"},
        )
        # standing_config is loaded from disk, not the bulletin, so this
        # resolves only once church.yaml actually has the field.
        import yaml
        config_path = self.church / "church.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config.setdefault("leadership", {})["placement"] = "footer"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        result = validate_for_production(self.church, bulletin_input())
        codes = {e["code"] for e in result["errors"] if e["section_id"] == "roster-placement"}
        self.assertEqual(codes, set())

    def test_config_path_accepts_numeric_list_traversal_for_announcements(self):
        bulletin = bulletin_input()
        bulletin["announcements"] = [{"title": "Fall Kickoff", "text": "Join us."}]
        add_section(
            self.church, self.import_id,
            section_id="announcement-1", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"config_path": "announcements.0.title"},
        )
        result = validate_for_production(self.church, bulletin)
        codes = {e["code"] for e in result["errors"]}
        self.assertNotIn("config_path_not_found", codes)
        self.assertNotIn("unsupported_destination", codes)

    def test_mapped_logo_uses_brand_json_not_church_yaml(self):
        with self.assertRaises(InventoryError):
            add_section(
                self.church, self.import_id,
                section_id="logo-wrong-root", page_start=1,
                disposition="mapped", scope="standing",
                target={"config_path": "church.logo"},
            )
        add_section(
            self.church, self.import_id,
            section_id="logo-right-root", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "brand.logo.banner"},
        )
        brand_path = self.church / "brand.json"
        brand = json.loads(brand_path.read_text(encoding="utf-8"))
        brand["logo"]["banner"] = "brand/logo.png"
        brand_path.write_text(json.dumps(brand), encoding="utf-8")
        result = validate_for_production(self.church, bulletin_input())
        codes = {e["code"] for e in result["errors"] if e["section_id"] == "logo-right-root"}
        self.assertEqual(codes, set())

    def test_episcopal_shield_is_a_supported_cover_logo_fallback(self):
        add_section(
            self.church, self.import_id,
            section_id="shield-fallback", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "brand.logo.episcopal_shield"},
        )
        brand_path = self.church / "brand.json"
        brand = json.loads(brand_path.read_text(encoding="utf-8"))
        brand["logo"]["episcopal_shield"] = "brand/shield.png"
        brand_path.write_text(json.dumps(brand), encoding="utf-8")
        result = validate_for_production(self.church, bulletin_input())
        codes = {e["code"] for e in result["errors"] if e["section_id"] == "shield-fallback"}
        self.assertEqual(codes, set())

        asset_dir = self.church / "brand"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "shield.png"
        asset_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        add_section(
            self.church, self.import_id,
            section_id="shield-asset", page_start=1,
            disposition="mapped", scope="standing",
            target={"asset_path": "brand/shield.png"},
        )
        result = validate_for_production(self.church, bulletin_input())
        codes = {e["code"] for e in result["errors"] if e["section_id"] == "shield-asset"}
        self.assertNotIn("asset_not_referenced", codes)

    # -- validate_for_production: blocking behavior -----------------------

    def test_import_with_no_recorded_sections_blocks_production(self):
        result = validate_for_production(self.church, bulletin_input())
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["unresolved_sections"][0]["code"], "import_not_reviewed")

    def test_relevant_unresolved_section_blocks_production(self):
        add_section(
            self.church, self.import_id,
            section_id="collect-of-day", page_start=1,
            disposition="unresolved", scope="weekly", service_date=SERVICE_DATE,
            notes="pending pastor decision",
        )
        result = validate_for_production(self.church, bulletin_input())
        self.assertEqual(result["status"], "invalid")

    def test_weekly_section_from_a_different_week_does_not_block(self):
        add_section(
            self.church, self.import_id,
            section_id="collect-of-day", page_start=1,
            disposition="unresolved", scope="weekly", service_date="2026-01-04",
            notes="pending pastor decision",
        )
        # A different week's unresolved section shouldn't make *this* import
        # look reviewed, so also give it a resolved section for this week.
        add_section(
            self.church, self.import_id,
            section_id="church-name", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "church.name"},
        )
        mark_review_complete(self.church, self.import_id, note="Reviewed all 2 pages.")
        result = validate_for_production(self.church, bulletin_input())
        self.assertEqual(result["status"], "valid")

    # -- review-complete attestation ---------------------------------------

    def test_recording_only_one_section_does_not_pass_without_review_complete(self):
        add_section(
            self.church, self.import_id,
            section_id="standing-logo", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "brand.logo.banner"},
        )
        result = validate_for_production(self.church, bulletin_input())
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["unresolved_sections"][0]["code"], "review_not_complete")

    def test_review_complete_needs_a_note_and_at_least_one_section(self):
        with self.assertRaises(InventoryError):
            mark_review_complete(self.church, self.import_id, note="")
        with self.assertRaises(InventoryError):
            mark_review_complete(self.church, self.import_id, note="nothing recorded yet")
        add_section(
            self.church, self.import_id,
            section_id="church-name", page_start=1,
            disposition="mapped", scope="standing",
            target={"config_path": "church.name"},
        )
        mark_review_complete(self.church, self.import_id, note="Reviewed all pages.")
        self.assertEqual(validate_for_production(self.church, bulletin_input())["status"], "valid")

    def test_editing_a_section_after_review_invalidates_it(self):
        add_section(
            self.church, self.import_id,
            section_id="dropped", page_start=1,
            disposition="omitted", scope="weekly", service_date=SERVICE_DATE,
            notes="approved omission",
        )
        mark_review_complete(self.church, self.import_id, note="Reviewed both pages.")
        self.assertEqual(validate_for_production(self.church, bulletin_input())["status"], "valid")

        add_section(
            self.church, self.import_id,
            section_id="dropped", page_start=1,
            disposition="omitted", scope="weekly", service_date=SERVICE_DATE,
            notes="reconsidered reason",
        )
        result = validate_for_production(self.church, bulletin_input())
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["unresolved_sections"][0]["code"], "review_not_complete")

    # -- referenced-by-render-input checks ---------------------------------

    def test_weekly_asset_must_be_referenced_by_a_supported_render_input(self):
        asset_dir = self.church / "music"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "page.png"
        asset_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        add_section(
            self.church, self.import_id,
            section_id="music-page", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"asset_path": "music/page.png"},
        )
        bulletin = bulletin_input()
        result = validate_for_production(self.church, bulletin)
        self.assertIn("asset_not_referenced", {e["code"] for e in result["errors"]})

        bulletin["debug_notes"] = "see music/page.png for context"
        result = validate_for_production(self.church, bulletin)
        self.assertIn("asset_not_referenced", {e["code"] for e in result["errors"]},
                       "an unrelated/ignored JSON key must not count as a reference")

        bulletin["hymns"]["entrance"]["image"] = "music/page.png"
        result = validate_for_production(self.church, bulletin)
        self.assertNotIn("asset_not_referenced", {e["code"] for e in result["errors"]})

    def test_standing_asset_must_be_referenced_in_brand_json(self):
        asset_dir = self.church / "brand"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "logo.png"
        asset_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        add_section(
            self.church, self.import_id,
            section_id="standing-logo", page_start=1,
            disposition="mapped", scope="standing",
            target={"asset_path": "brand/logo.png"},
        )
        result = validate_for_production(self.church, bulletin_input())
        self.assertIn("asset_not_referenced", {e["code"] for e in result["errors"]})

        brand_path = self.church / "brand.json"
        brand = json.loads(brand_path.read_text(encoding="utf-8"))
        brand["logo"]["banner"] = "brand/logo.png"
        brand_path.write_text(json.dumps(brand), encoding="utf-8")
        result = validate_for_production(self.church, bulletin_input())
        self.assertNotIn("asset_not_referenced", {e["code"] for e in result["errors"]})

    def test_liturgy_files_recognized_alongside_liturgy_sources(self):
        self._text_file("gathering.txt", "Gathering rite text for a Lutheran service variant.")
        add_section(
            self.church, self.import_id,
            section_id="gathering-rite", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"text_file": "worship/liturgy/gathering.txt"},
        )
        bulletin = bulletin_input()
        bulletin["liturgy"]["files"] = {"gathering": "worship/liturgy/gathering.txt"}
        result = validate_for_production(self.church, bulletin)
        self.assertNotIn("text_not_referenced", {e["code"] for e in result["errors"]})

    def test_reference_comparison_resolves_relative_and_absolute_aliases(self):
        asset_dir = self.church / "music"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "page.png"
        asset_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        add_section(
            self.church, self.import_id,
            section_id="music-page", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"asset_path": "music/page.png"},
        )
        bulletin = bulletin_input()
        # Referenced with the church-root-absolute spelling instead of the
        # relative spelling recorded on the section.
        bulletin["hymns"]["entrance"]["image"] = str(asset_path.resolve())
        result = validate_for_production(self.church, bulletin)
        self.assertNotIn("asset_not_referenced", {e["code"] for e in result["errors"]})

    # -- fingerprint --------------------------------------------------------

    def test_fingerprint_changes_between_two_different_valid_states(self):
        bulletin = bulletin_input()
        bulletin["liturgy"]["sources"] = {"collect": "worship/liturgy/collect.txt"}
        self._text_file("collect.txt", "Original verified collect wording.")
        add_section(
            self.church, self.import_id,
            section_id="collect-text", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"text_file": "worship/liturgy/collect.txt"},
        )
        mark_review_complete(self.church, self.import_id, note="Reviewed both pages.")
        first = validate_for_production(self.church, bulletin)
        self.assertEqual(first["status"], "valid")

        again = validate_for_production(self.church, bulletin)
        self.assertEqual(again["fingerprint"], first["fingerprint"], "no change should mean no fingerprint change")

        self._text_file("collect.txt", "Revised verified collect wording.")
        add_section(
            self.church, self.import_id,
            section_id="collect-text", page_start=1,
            disposition="mapped", scope="weekly", service_date=SERVICE_DATE,
            target={"text_file": "worship/liturgy/collect.txt"},
        )
        mark_review_complete(self.church, self.import_id, note="Reviewed both pages again after the edit.")
        second = validate_for_production(self.church, bulletin)
        self.assertEqual(second["status"], "valid")
        self.assertNotEqual(second["fingerprint"], first["fingerprint"],
                             "re-recorded content must change the fingerprint even though both states are valid")

    # -- path safety and tampered records ------------------------------------

    def test_malformed_manifest_json_is_rejected_cleanly(self):
        manifest_path = self.church / "onboarding" / "imports" / self.import_id / "manifest.json"
        manifest_path.write_text("{not valid json", encoding="utf-8")
        result = check_mapping_integrity(self.church, self.import_id)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "malformed_record")

    def test_manifest_source_path_escape_attempt_does_not_read_outside_church(self):
        manifest_path = self.church / "onboarding" / "imports" / self.import_id / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["source"]["path"] = "/etc/passwd"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        result = check_mapping_integrity(self.church, self.import_id)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("source_changed", {e["code"] for e in result["errors"]})

    # -- optional post-render check ------------------------------------------

    def test_check_rendered_text_normalizes_whitespace(self):
        self._text_file("prayer.txt", "*The Celebrant*\tThe   Lord\nbe with you.")
        add_section(
            self.church, self.import_id,
            section_id="opening-dialogue", page_start=1,
            disposition="mapped", scope="standing",
            target={"text_file": "worship/liturgy/prayer.txt"},
        )
        rendered_pdf = self.church / "bulletins" / "rendered.pdf"
        HTML(string="<html><body><p>The Celebrant   The Lord\nbe with you.</p></body></html>").write_pdf(rendered_pdf)
        result = check_rendered_text(self.church, self.import_id, "opening-dialogue", rendered_pdf)
        self.assertEqual(result["status"], "found")


if __name__ == "__main__":
    unittest.main()
