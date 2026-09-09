from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from skills.bulletin.renderer.render_bulletin import (
    doxology_block,
    gospel_block,
    psalm_block,
    reading_block,
    render_blocks,
    resolved_service_display,
    service_variant_order,
)


class BulletinPresentationTest(unittest.TestCase):
    def test_cover_title_uses_resolved_service_without_internal_variant_label(self):
        cfg = {"liturgy": {"service_plan": "episcopal-rite-ii",
                           "service_variant": {"id": "none", "name": "Ordinary service"}}}
        self.assertEqual(resolved_service_display(cfg, {}), "Holy Eucharist, Rite II")
        cfg["liturgy"]["service_plan"] = "lutheran-holy-communion"
        self.assertEqual(resolved_service_display(cfg, {}), "Holy Communion")
        self.assertEqual(resolved_service_display(cfg, {"service_line": "Sunday Communion"}),
                         "Sunday Communion")
        cfg["liturgy"]["service_variant"] = {"id": "baptism", "name": "Holy Baptism"}
        self.assertEqual(resolved_service_display(cfg, {}), "Holy Baptism")
        cfg["service"] = {"display_name": "Parish Eucharist"}
        self.assertEqual(resolved_service_display(cfg, {}), "Parish Eucharist")

    def test_shaped_reading_paragraphs_and_poetry_keep_their_boundaries(self):
        html = reading_block("The First Reading", {
            "citation": "Synthetic 1:1-4",
            "paragraphs": ["First paragraph.", "Second paragraph with 3 actual."],
        })
        self.assertEqual(html.count('class="reading-text"'), 2)
        self.assertIn("Second paragraph with 3 actual.", html)

        poetry = gospel_block({
            "citation": "Matthew 1:1-2",
            "format": "poetry",
            "paragraphs": ["First line", "Second line\nThird line"],
        })
        self.assertIn('class="reading-text reading-poetry"', poetry)
        self.assertIn("Second line<br>\nThird line", poetry)

    def test_explicit_psalm_modes_keep_numbers_and_only_shaped_halves_split(self):
        half = psalm_block({
            "number": "23",
            "format": "responsive_half_verse",
            "verses": [{"number": 1, "first": "The Lord is my shepherd;", "second": "I shall not be in want."}],
        })
        self.assertIn('<span class="vnum">1</span>', half)
        self.assertIn("<strong>I shall not be in want.</strong>", half)

        whole = psalm_block({
            "number": "23",
            "format": "responsive_whole_verse",
            "verses": [{"number": 1, "text": "The Lord is my shepherd;"},
                       {"number": 2, "text": "He makes me lie down."}],
        })
        self.assertIn('<p class="psalm-verse"><span class="vnum">1</span>', whole)
        self.assertIn('<p class="psalm-response psalm-whole-verse"><span class="vnum">2</span>', whole)
        self.assertIn("<strong>He makes me lie down.</strong>", whole)

        punctuation = psalm_block({
            "number": "23",
            "format": "responsive_whole_verse",
            "text": "1 A sentence, with punctuation. * Still one whole verse.",
        })
        self.assertNotIn("psalm-response", punctuation)
        self.assertIn("* Still one whole verse.", punctuation)

    def test_explicit_psalm_pattern_replaces_imported_bold_markup(self):
        plain = psalm_block({"number": "1", "format": "plain", "text": "1 **Former response.**"})
        self.assertNotIn("<strong>", plain)
        half = psalm_block({"number": "1", "format": "responsive_half_verse",
                            "verses": [{"number": 1, "first": "**Leader.**", "second": "People."}]})
        self.assertNotIn("<strong>Leader.</strong>", half)
        self.assertIn("<strong>People.</strong>", half)

    def test_prayer_presentation_suppresses_only_consecutive_labels(self):
        blocks = [
            ("dialogue", {"speaker": "Celebrant", "lines": [(None, "First prayer.")], "bold": False}),
            ("dialogue", {"speaker": "Celebrant", "lines": [(None, "Second prayer.")], "bold": False}),
            ("dialogue", {"speaker": "People", "lines": [(None, "Amen.")], "bold": True}),
            ("dialogue", {"speaker": "Celebrant", "lines": [(None, "Third prayer.")], "bold": False}),
        ]
        continuous = render_blocks(blocks, {"prayer_presentation": "continuous"})
        self.assertEqual(continuous.count("Celebrant"), 2)
        self.assertIn("First prayer.", continuous)
        self.assertIn("Second prayer.", continuous)
        self.assertIn("Third prayer.", continuous)
        repeated = render_blocks(blocks, {"prayer_presentation": "repeated_labels"})
        self.assertEqual(repeated.count("Celebrant"), 3)

    def test_rubric_style_changes_only_the_allowlisted_procedure(self):
        blocks = [("rubric", "Then, facing the Holy Table, the Celebrant proceeds."),
                  ("rubric", "The people stand.")]
        concise = render_blocks(blocks, {"rubric_style": "concise"})
        self.assertIn("The celebrant proceeds.", concise)
        self.assertIn("The people stand.", concise)
        source = render_blocks(blocks, {"rubric_style": "source"})
        self.assertIn("Then, facing the Holy Table, the Celebrant proceeds.", source)

    def test_doxology_modes_and_service_music_use_one_rendering_path(self):
        order = service_variant_order({"liturgy": {"service_plan": "episcopal-rite-ii"}})
        traditional = doxology_block(
            {"liturgy": {"doxology": "traditional"}},
            {"liturgy_files": {}}, order, Path("/tmp"))
        self.assertIn("Praise Father, Son, and Holy Ghost.", traditional)
        self.assertNotIn("Trinity of love", traditional)

        omitted = doxology_block(
            {"liturgy": {"doxology": "omit"}, "service_music": {
                "doxology": {"title": "Printed Doxology", "lyrics": [
                    {"speaker": "All", "bold": True, "lines": ["Praise"]}]} }},
            {"liturgy_files": {}}, order, Path("/tmp"))
        self.assertEqual(omitted, "")

        music = doxology_block(
            {"liturgy": {"doxology": "traditional"}, "service_music": {
                "doxology": {"title": "Printed Doxology", "lyrics": [
                    {"speaker": "All", "bold": True, "lines": ["Praise"]}]} }},
            {"liturgy_files": {}}, order, Path("/tmp"))
        self.assertIn("Printed Doxology", music)
        self.assertIn('class="lyrics-group response"', music)
        self.assertNotIn("Praise Father, Son, and Holy Ghost.", music)

        with TemporaryDirectory() as temp:
            source = Path(temp) / "local-doxology.md"
            source.write_text("# Local Doxology\n\nPriest\tLocal text.\n", encoding="utf-8")
            with patch("skills.bulletin.renderer.render_bulletin.LITURGY_DIR", Path(temp)):
                custom = doxology_block(
                    {"liturgy": {"doxology": "custom", "files": {"doxology": "local-doxology"}}},
                    {"liturgy_files": {"doxology": "local-doxology"}}, order, Path("/tmp"))
            self.assertIn("Local text.", custom)


if __name__ == "__main__":
    unittest.main()
