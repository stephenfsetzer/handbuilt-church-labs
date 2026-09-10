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
from tests.test_bulletin_music_slots import _painted_image_colors


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


class ParishInformationTest(unittest.TestCase):
    """Standing before/after-service parish-information sections: saved
    defaults consumed automatically by canonical produce, distinct from
    dated announcements, in both canonical layouts."""

    def _church_with_parish_information(self, tmp: Path) -> Path:
        church = make_church(tmp)
        config_path = church / "church.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["bulletin"] = {"parish_information": {
            "before_service": [
                {"title": "Welcome", "text": "Welcome to All Saints. We are glad you are here today."},
            ],
            "after_service": [
                {"title": "Accessibility", "text": "Ramp access is available at the side door."},
                {"title": "Pastoral Contact", "text": "Reach the parish office at 555-0100."},
                {"title": "About Our Worship Book", "text": "Hymnal numbers are printed above each hymn."},
            ],
        }}
        config_path.write_text(yaml.safe_dump(config))
        return church

    def test_saved_defaults_flow_through_real_produce_in_both_layouts_in_order(self) -> None:
        for template, service_date in (("classic", "2026-09-20"), ("modern", "2026-09-27")):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = self._church_with_parish_information(Path(tmp))
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["service"]["date"] = service_date
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                pdf_text = "\n".join(
                    page.extract_text() or ""
                    for page in PdfReader(str(next(folder.glob(f"*{template}.pdf")))).pages
                )

                titles_in_order = [
                    "Welcome", "Accessibility", "Pastoral Contact", "About Our Worship Book",
                ]
                texts_in_order = [
                    "Welcome to All Saints. We are glad you are here today.",
                    "Ramp access is available at the side door.",
                    "Reach the parish office at 555-0100.",
                    "Hymnal numbers are printed above each hymn.",
                ]
                # The embedded test font's extracted text can insert stray
                # spaces around some glyphs (a known artifact elsewhere in
                # this fixture, e.g. "T est"); compare the PDF compactly.
                compact_pdf_text = "".join(pdf_text.split())
                for text in texts_in_order:
                    self.assertIn(text, html)
                    self.assertIn("".join(text.split()), compact_pdf_text)
                # Order preserved, both in the HTML flow and in the printed
                # page-extracted text.
                self.assertEqual(
                    sorted(range(len(titles_in_order)), key=lambda i: html.index(titles_in_order[i])),
                    list(range(len(titles_in_order))),
                )
                self.assertEqual(
                    sorted(
                        range(len(texts_in_order)),
                        key=lambda i: compact_pdf_text.index("".join(texts_in_order[i].split())),
                    ),
                    list(range(len(texts_in_order))),
                )
                # Distinct from dated announcements: each parish-information
                # section is its own section (one per entry), never folded
                # into the dated Announcements block.
                self.assertEqual(html.count('<div class="section parish-info">'), 4)
                # The welcome (before_service) prints ahead of the actual
                # service content; the logo/service content are not omitted.
                self.assertLess(html.index("Welcome to All Saints"), html.index("Entrance Hymn"))
                self.assertIn("cover-church-name", html)

    def test_weekly_explicit_empty_override_suppresses_only_that_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_parish_information(Path(tmp))
            bulletin = bulletin_input()
            bulletin["parish_information"] = {"after_service": []}
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review", result)
            html = next(Path(result["week_folder"]).glob("*.html")).read_text(encoding="utf-8")
            # Suppressed this week by explicit pastor request.
            self.assertNotIn("Accessibility", html)
            self.assertNotIn("Pastoral Contact", html)
            self.assertNotIn("About Our Worship Book", html)
            # The scope the week did not mention still uses the saved default.
            self.assertIn("Welcome to All Saints", html)

            # A later week that omits the override entirely reverts to the
            # saved default rather than carrying the suppression forward.
            next_week = bulletin_input()
            next_week["service"]["date"] = "2026-09-27"
            result_two = produce(church, next_week)
            self.assertEqual(result_two["status"], "ready_for_review", result_two)
            html_two = next(Path(result_two["week_folder"]).glob("*.html")).read_text(encoding="utf-8")
            self.assertIn("Accessibility", html_two)

    def test_unrecognized_scope_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["parish_information"] = {"mid_service": []}
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")
            self.assertEqual(result["errors"][0]["field"], "parish_information")

    def test_section_missing_required_text_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["parish_information"] = {"before_service": [{"title": "Welcome"}]}
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")
            self.assertEqual(result["errors"][0]["field"], "parish_information.before_service[0].text")

    def test_unrecognized_section_field_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["parish_information"] = {
                "before_service": [{"title": "Welcome", "text": "Hi", "html": "<script>bad</script>"}],
            }
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")

    def test_non_string_title_or_text_is_rejected_not_coerced(self) -> None:
        # A null, number, list, or mapping must never be stringified into
        # nonsense printed text such as the literal word "None".
        for bad_entry in (
            {"title": None, "text": "Hi"},
            {"title": "Welcome", "text": None},
            {"title": 12, "text": "Hi"},
            {"title": "Welcome", "text": ["Hi"]},
            {"title": "Welcome", "text": {"nested": "Hi"}},
        ):
            with self.subTest(bad_entry=bad_entry), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                bulletin = bulletin_input()
                bulletin["parish_information"] = {"before_service": [bad_entry]}
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "blocked", result)
                self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")

    def test_explicit_null_scope_is_rejected_distinct_from_missing_or_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = self._church_with_parish_information(Path(tmp))
            bulletin = bulletin_input()
            # Explicit null is neither "missing" (inherit) nor "[]" (suppress).
            bulletin["parish_information"] = {"before_service": None}
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")
            self.assertEqual(result["errors"][0]["field"], "parish_information.before_service")

    def test_malformed_saved_standing_value_blocks_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config_path = church / "church.yaml"
            config = yaml.safe_load(config_path.read_text())
            config["bulletin"] = {"parish_information": {"before_service": [{"title": "Welcome"}]}}
            config_path.write_text(yaml.safe_dump(config))
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")
            self.assertIn("church.yaml", result["errors"][0]["message"])

    def test_unknown_saved_standing_scope_blocks_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            config_path = church / "church.yaml"
            config = yaml.safe_load(config_path.read_text())
            config["bulletin"] = {"parish_information": {"mid_service": []}}
            config_path.write_text(yaml.safe_dump(config))
            result = produce(church, bulletin_input())
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "invalid_parish_information")


class AnnouncementImageTest(unittest.TestCase):
    """Supported event-poster/QR artwork attached to a dated announcement,
    distinct from a generic layout builder: a church-relative image or
    images field, staged and source-accounted like a hymn image."""

    def test_two_distinct_posters_are_painted_in_order_in_both_layouts(self) -> None:
        colors = [(220, 20, 60), (30, 60, 200)]
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                music_dir = church / "music"
                music_dir.mkdir(exist_ok=True)
                # Same basename in two different source directories: staged
                # filenames must not collide and overwrite one another.
                second_dir = music_dir / "second"
                second_dir.mkdir()
                Image.new("RGB", (900, 1200), colors[0]).save(music_dir / "poster.png")
                Image.new("RGB", (900, 1200), colors[1]).save(second_dir / "poster.png")
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["announcements"] = [
                    {"title": "Fall Festival", "image": "music/poster.png", "caption": "See you there"},
                    {"title": "Sign Up", "text": "Scan to register.", "image": "music/second/poster.png"},
                ]
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                first_marker = "announcement-images/0-0-poster.png"
                second_marker = "announcement-images/1-0-poster.png"
                self.assertIn(first_marker, html)
                self.assertIn(second_marker, html)
                self.assertLess(html.index("Fall Festival"), html.index("Sign Up"))
                self.assertLess(html.index(first_marker), html.index(second_marker))
                self.assertIn("See you there", html)
                # Both staged files exist separately: neither overwrote the
                # other despite sharing a source basename.
                staged_first = next(folder.rglob("0-0-poster.png"))
                staged_second = next(folder.rglob("1-0-poster.png"))
                self.assertNotEqual(staged_first.read_bytes(), staged_second.read_bytes())

                pdf = next(folder.glob(f"*{template}.pdf"))
                reader = PdfReader(str(pdf))
                pages_painted = [_painted_image_colors(page) for page in reader.pages]
                painted = {color for page in pages_painted for color in page}
                # Both distinct posters actually reached the printed PDF,
                # not just the staged HTML config. Visual QA checks cropping.
                self.assertEqual(painted, set(colors))
                first_page = next(i for i, colors_on_page in enumerate(pages_painted) if colors[0] in colors_on_page)
                second_page = next(i for i, colors_on_page in enumerate(pages_painted) if colors[1] in colors_on_page)
                self.assertLessEqual(first_page, second_page)

    def test_missing_announcement_image_blocks_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["announcements"] = [{"title": "Bake Sale", "image": "music/missing.png"}]
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "missing_announcement_image")

    def test_announcement_image_resolves_the_exact_path_not_a_music_basename_fallback(self) -> None:
        # A same-named file elsewhere under music/ must never be silently
        # substituted for a missing exact path.
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            music_dir = church / "music"
            music_dir.mkdir(exist_ok=True)
            Image.new("RGB", (10, 10), (1, 2, 3)).save(music_dir / "poster.png")
            bulletin = bulletin_input()
            bulletin["announcements"] = [{"title": "Bake Sale", "image": "announcements/poster.png"}]
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "missing_announcement_image")

    def test_announcement_image_cannot_escape_the_church_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            Image.new("RGB", (10, 10), (0, 0, 0)).save(Path(tmp) / "outside.png")
            bulletin = bulletin_input()
            bulletin["announcements"] = [{"title": "Bake Sale", "image": "../outside.png"}]
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["errors"][0]["code"], "unsafe_path")


if __name__ == "__main__":
    unittest.main()
