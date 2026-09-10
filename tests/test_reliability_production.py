from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import weasyprint
import yaml
from PIL import Image
from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce
from skills.bulletin.bulletin_production.interface import finalize
from skills.bulletin.source_inventory import add_section, mark_review_complete
from skills.onboarding.bulletin_import import import_bulletin
from tests.helpers import bulletin_input, make_church


def _synthetic_supplied_pdf(path: Path, pages: int = 2) -> None:
    """A tiny synthetic multi-page PDF: no real church content, just enough
    for the import pipeline's native tools to render, extract, and hash."""
    body = "".join(
        f'<div style="page-break-after: always;">Synthetic supplied page {i}</div>'
        for i in range(1, pages + 1)
    )
    weasyprint.HTML(string=f"<html><body>{body}</body></html>").write_pdf(str(path))


class ReliabilityProductionIntegrationTest(unittest.TestCase):
    """Production reliability coverage across both canonical layouts.

    Each check exercises the real ``produce`` interface, not a stubbed
    renderer call, so a regression in the actual production path fails here.
    """

    def _church_with_large_roster_and_standing_doxology(self, tmp: Path) -> Path:
        church = make_church(tmp)
        config_path = church / "church.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["leadership"] = {
            "print_in_bulletin": True,
            "clergy_and_staff": [
                {"name": f"Parishioner {i:02d}", "role": "Vestry"} for i in range(35)
            ],
        }
        config["bulletin"] = {"doxology_music": {
            "title": "Standing Doxology",
            "lyrics": [{"speaker": "All", "bold": True, "lines": ["Synthetic standing doxology text."]}],
        }}
        config_path.write_text(yaml.safe_dump(config))
        return church

    def _base_bulletin(self, template: str, service_date: str) -> dict:
        bulletin = bulletin_input()
        bulletin["template"] = template
        bulletin["service"]["date"] = service_date
        bulletin["liturgy"].update({
            "eucharistic_prayer": "A",
            "lords_prayer": "traditional",
            "prayers_of_the_people": "III",
            "blessing": "omit",
            "closing_hymn_position": "before_dismissal",
        })
        return bulletin

    def test_large_directory_closing_position_and_doxology_omission_in_both_layouts(self) -> None:
        for template, service_date in (("classic", "2026-09-20"), ("modern", "2026-09-27")):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = self._church_with_large_roster_and_standing_doxology(Path(tmp))

                # Week 1: weekly input omits service_music.doxology, so the
                # standing doxology_music applies. The closing hymn is asked
                # to print before the spoken dismissal (a source order choice).
                week_one = self._base_bulletin(template, service_date)
                result = produce(church, week_one)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                pdf_path = next(folder.glob(f"*{template}.pdf"))
                pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

                # 35-name directory: all names retained in a normal body
                # section, not truncated by the running-footer capacity, and
                # not duplicated into the footer roster.
                self.assertIn("Parish Directory", html)
                self.assertNotIn("Parish Leadership", html)
                for i in range(35):
                    name = f"Parishioner {i:02d}"
                    self.assertIn(name, html)
                    self.assertIn(name, pdf_text)
                self.assertEqual(html.count("Vestry"), 35)
                # The extracted font can insert stray spaces around some
                # glyphs (a known artifact elsewhere in this fixture, e.g.
                # "T est"); compare compactly rather than on exact spacing.
                self.assertIn("vestry", "".join(pdf_text.split()).lower())

                # Source-order choice: the closing hymn prints before the
                # spoken dismissal rather than the documented default order.
                self.assertLess(html.index("Test Closing"), html.index("The Dismissal"))

                # Standing doxology music applied because the week omitted it.
                self.assertIn("Standing Doxology", pdf_text)
                self.assertIn("Synthetic standing doxology text.", pdf_text)

                # Week 2: the pastor explicitly omits doxology music this
                # week. That explicit choice must survive, not be silently
                # replaced by the standing default.
                week_two = self._base_bulletin(template, "2026-10-04" if template == "classic" else "2026-10-11")
                week_two["service_music"]["doxology"] = None
                result_two = produce(church, week_two)
                self.assertEqual(result_two["status"], "ready_for_review", result_two)
                html_two = next(Path(result_two["week_folder"]).glob("*.html")).read_text(encoding="utf-8")
                self.assertNotIn("Standing Doxology", html_two)
                self.assertNotIn("Synthetic standing doxology text.", html_two)

    def test_explicit_footer_placement_above_capacity_still_blocks_in_both_layouts(self) -> None:
        # print_in_bulletin stays true throughout: an explicit footer
        # request for a roster over capacity is a layout error to fix, not
        # a reason to silently drop the roster from the bulletin.
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                config_path = church / "church.yaml"
                config = yaml.safe_load(config_path.read_text())
                config["leadership"] = {
                    "print_in_bulletin": True,
                    "placement": "footer",
                    "clergy_and_staff": [
                        {"name": f"Parishioner {i:02d}", "role": "Vestry"} for i in range(35)
                    ],
                }
                config_path.write_text(yaml.safe_dump(config))
                result = produce(church, self._base_bulletin(template, "2026-09-20"))
                self.assertEqual(result["status"], "blocked", result)
                self.assertEqual(result["errors"][0]["code"], "leadership_roster_capacity")
                self.assertTrue(config["leadership"]["print_in_bulletin"])


class SourceInventoryProductionGateTest(unittest.TestCase):
    """Synthetic-only coverage for the source-inventory gate wired into
    ``produce``/``finalize`` (``validate_for_production``, called
    read-only, never modified here)."""

    def _import(self, church: Path, tmp: Path, pages: int = 2) -> str:
        pdf_path = tmp / "supplied.pdf"
        _synthetic_supplied_pdf(pdf_path, pages=pages)
        manifest = import_bulletin(church, pdf_path)
        return manifest["import_id"]

    def _map_hymn_image(self, church: Path, import_id: str, *, service_date: str, asset_name: str = "imported-hymn.png") -> None:
        music_dir = church / "music"
        music_dir.mkdir(exist_ok=True)
        Image.new("RGB", (200, 100), (10, 20, 30)).save(music_dir / asset_name)
        add_section(
            church, import_id,
            section_id="hymn-1", page_start=1, page_end=1,
            disposition="mapped", scope="weekly",
            target={"asset_path": f"music/{asset_name}"},
            service_date=service_date,
        )
        mark_review_complete(church, import_id, note="Reviewed synthetic hymn image")

    def _bulletin_referencing(self, service_date: str, asset_name: str = "imported-hymn.png") -> dict:
        bulletin = bulletin_input()
        bulletin["service"]["date"] = service_date
        bulletin["hymns"]["entrance"]["image"] = f"music/{asset_name}"
        return bulletin

    def _bulletin_referencing_none(self, service_date: str) -> dict:
        bulletin = bulletin_input()
        bulletin["service"]["date"] = service_date
        return bulletin

    def test_no_upload_church_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "ready_for_review", result)

    def test_unfinished_import_blocks_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            self._import(church, tmp)
            # No add_section call at all: nothing recorded yet.
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "source_inventory_invalid")
            diagnostics = result["errors"][0]["diagnostics"]
            self.assertEqual(diagnostics["unresolved_sections"][0]["code"], "import_not_reviewed")

    def test_relevant_unresolved_section_blocks_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            add_section(
                church, import_id,
                section_id="local-welcome", page_start=1, page_end=1,
                disposition="unresolved", scope="standing",
            )
            mark_review_complete(church, import_id, note="Everything else reviewed")
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "source_inventory_invalid")
            unresolved = result["errors"][0]["diagnostics"]["unresolved_sections"]
            self.assertTrue(any(item.get("section_id") == "local-welcome" for item in unresolved))

    def test_wrong_week_unresolved_content_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            add_section(
                church, import_id,
                section_id="next-months-insert", page_start=2, page_end=2,
                disposition="unresolved", scope="weekly", service_date="2099-01-01",
            )
            mark_review_complete(church, import_id, note="Only next month's insert is pending")
            result = produce(church, self._bulletin_referencing_none("2026-09-20"))
            self.assertEqual(result["status"], "ready_for_review", result)

    def test_missing_mapped_asset_blocks_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            self._map_hymn_image(church, import_id, service_date="2026-09-20")
            (church / "music" / "imported-hymn.png").unlink()
            result = produce(church, self._bulletin_referencing("2026-09-20"))
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "source_inventory_invalid")
            errors = result["errors"][0]["diagnostics"]["errors"]
            self.assertTrue(any(item["code"] == "missing_asset" for item in errors))

    def test_valid_mapped_source_produces_with_visual_review_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            self._map_hymn_image(church, import_id, service_date="2026-09-20")
            result = produce(church, self._bulletin_referencing("2026-09-20"))
            self.assertEqual(result["status"], "ready_for_review", result)
            receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["source_inventory"]["imports_checked"], 1)
            self.assertEqual(len(receipt["source_inventory"]["visual_review"]), 1)
            self.assertEqual(receipt["source_inventory"]["visual_review"][0]["section_id"], "hymn-1")

    def test_changing_a_reviewed_mapping_makes_the_prior_receipt_stale(self) -> None:
        from skills.bulletin.source_inventory import validate_for_production

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            self._map_hymn_image(church, import_id, service_date="2026-09-20")
            bulletin = self._bulletin_referencing("2026-09-20")
            first = produce(church, bulletin)
            self.assertEqual(first["status"], "ready_for_review", first)
            first_fingerprint = validate_for_production(church, bulletin)["fingerprint"]

            # Re-record the same mapped section with a changed note (any
            # add_section call resets review-complete), mark it reviewed
            # again: a different, still-valid inventory state.
            add_section(
                church, import_id,
                section_id="hymn-1", page_start=1, page_end=1,
                disposition="mapped", scope="weekly",
                target={"asset_path": "music/imported-hymn.png"},
                service_date="2026-09-20", notes="Re-recorded after a visual check",
            )
            mark_review_complete(church, import_id, note="Re-reviewed synthetic hymn image")
            second_fingerprint = validate_for_production(church, bulletin)["fingerprint"]
            self.assertNotEqual(first_fingerprint, second_fingerprint)

            # A produce() call repeated for the same date with an unchanged
            # weekly bulletin, after the underlying source mapping changed,
            # must not silently reuse the stale receipt: it demands an
            # explicit revision.
            second = produce(church, bulletin)
            self.assertEqual(second["status"], "blocked", second)
            self.assertEqual(second["errors"][0]["code"], "existing_run_conflict")

    def test_finalize_blocks_when_the_source_mapping_changed_since_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            self._map_hymn_image(church, import_id, service_date="2026-09-20")
            bulletin = self._bulletin_referencing("2026-09-20")
            produced = produce(church, bulletin)
            self.assertEqual(produced["status"], "ready_for_review", produced)

            add_section(
                church, import_id,
                section_id="hymn-1", page_start=1, page_end=1,
                disposition="mapped", scope="weekly",
                target={"asset_path": "music/imported-hymn.png"},
                service_date="2026-09-20", notes="Changed after production, before approval",
            )
            mark_review_complete(church, import_id, note="Re-reviewed before approval")

            approval = {
                "production_run_id": json.loads(Path(produced["receipt_path"]).read_text())["run_id"],
                "approved_by": "Test Pastor",
                "reviewed_artifact_hashes": {
                    item["role"]: item["sha256"]
                    for item in json.loads(Path(produced["receipt_path"]).read_text())["artifacts"]
                },
            }
            outcome = finalize(produced["receipt_path"], approval)
            self.assertEqual(outcome["status"], "blocked", outcome)
            self.assertEqual(outcome["errors"][0]["code"], "source_inventory_changed")

    def test_finalize_succeeds_when_the_source_mapping_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            church = make_church(tmp)
            import_id = self._import(church, tmp)
            self._map_hymn_image(church, import_id, service_date="2026-09-20")
            bulletin = self._bulletin_referencing("2026-09-20")
            produced = produce(church, bulletin)
            self.assertEqual(produced["status"], "ready_for_review", produced)
            receipt = json.loads(Path(produced["receipt_path"]).read_text())
            approval = {
                "production_run_id": receipt["run_id"],
                "approved_by": "Test Pastor",
                "reviewed_artifact_hashes": {item["role"]: item["sha256"] for item in receipt["artifacts"]},
            }
            outcome = finalize(produced["receipt_path"], approval)
            self.assertEqual(outcome["status"], "approved", outcome)


if __name__ == "__main__":
    unittest.main()
