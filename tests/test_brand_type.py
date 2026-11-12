"""An approved brand's typefaces reach the bulletin and the finance report."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "skills" / "bulletin" / "renderer" / "fonts"
FINANCE = ROOT / "skills" / "finance-report" / "scripts" / "report_renderer.py"

from skills.bulletin.renderer.brand_type import brand_faces, is_variable_font, variation_settings  # noqa: E402
from skills.bulletin.renderer.render_bulletin import build_css  # noqa: E402


def _brand(display_files: dict, text_files: dict) -> dict:
    return {
        "colors": {"ink": "#111111", "accent": "#224466", "accent_deep": "#112233", "paper": "#ffffff", "rubric_red": "#8b3a3a"},
        "brand_system": {"type": {
            "display": {"family": "Test Serif (tailored: weight 700)", "license": "OFL", "files": display_files},
            "text": {"family": "Test Sans", "license": "OFL", "files": text_files},
        }},
    }


class BrandTypeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.church = Path(self.temp.name)
        (self.church / "brand" / "type").mkdir(parents=True)
        shutil.copy(FONTS / "SourceSerif4-Regular.ttf", self.church / "brand/type/Display-Regular.ttf")
        shutil.copy(FONTS / "SourceSerif4-Bold.ttf", self.church / "brand/type/Display-Bold.ttf")
        shutil.copy(FONTS / "SourceSans3-Regular.ttf", self.church / "brand/type/Text-Regular.ttf")
        self.brand = _brand(
            {"regular": "brand/type/Display-Regular.ttf", "bold": "brand/type/Display-Bold.ttf"},
            {"regular": "brand/type/Text-Regular.ttf"},
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_faces_use_fixed_names_never_the_descriptive_label(self):
        css, families = brand_faces(self.brand, self.church)
        self.assertEqual(families, {"display": "Brand Display", "text": "Brand Text"})
        self.assertNotIn("tailored", css)
        self.assertIn('font-family: "Brand Display"', css)
        self.assertIn("font-weight: 700", css)
        self.assertIn((self.church / "brand/type/Display-Bold.ttf").resolve().as_uri(), css)

    def test_missing_files_or_no_type_leave_the_renderer_alone(self):
        self.assertEqual(brand_faces({}, self.church), ("", {}))
        gone = _brand({"regular": "brand/type/Nope.ttf"}, {"regular": "brand/type/Text-Regular.ttf"})
        css, families = brand_faces(gone, self.church)
        self.assertEqual(families, {"text": "Brand Text"})
        self.assertTrue(is_variable_font(FONTS / "SourceSans3-Regular.ttf"))
        (self.church / "not-a-font.ttf").write_bytes(b"hello")
        self.assertFalse(is_variable_font(self.church / "not-a-font.ttf"))

    def test_a_lone_variable_file_covers_every_weight(self):
        css, _ = brand_faces(self.brand, self.church)
        text_rule = [line for line in css.splitlines() if '"Brand Text"' in line]
        self.assertEqual(len(text_rule), 1)
        self.assertIn("font-weight: 100 900", text_rule[0])
        display_rules = [line for line in css.splitlines() if '"Brand Display"' in line]
        self.assertEqual(len(display_rules), 2)

    def test_a_variable_file_stops_below_a_static_cut_of_the_same_style(self):
        shutil.copy(FONTS / "SourceSerif4-Regular.ttf", self.church / "brand/type/Variable.ttf")
        static = self.church / "brand/type/Static-Bold.ttf"
        static.write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 8)  # a font header with no tables: not variable
        brand = _brand({"regular": "brand/type/Variable.ttf", "bold": "brand/type/Static-Bold.ttf"},
                       {"regular": "brand/type/Text-Regular.ttf"})
        css, _ = brand_faces(brand, self.church)
        rules = [line for line in css.splitlines() if '"Brand Display"' in line]
        self.assertIn("font-weight: 100 699", rules[0])
        self.assertIn("font-weight: 700", rules[1])

    def test_the_reading_face_sets_running_liturgy_with_its_axis_settings(self):
        shutil.copy(FONTS / "SourceSerif4-Italic.ttf", self.church / "brand/type/Reading-Italic.ttf")
        self.brand["brand_system"]["type"]["reading"] = {
            "family": "Test Serif (reading)", "license": "OFL",
            "files": {"regular": "brand/type/Display-Regular.ttf", "italic": "brand/type/Reading-Italic.ttf"},
            "variation": {"opsz": 12, "SOFT": 30, "bad": 1},
        }
        self.assertEqual(variation_settings(self.brand, "reading"), '"opsz" 12, "SOFT" 30')
        self.assertEqual(variation_settings(self.brand, "text"), "normal")
        css = build_css("modern", self.brand, self.church)
        self.assertIn('body {\n    font-family: "Brand Reading", "Source Serif 4", Georgia, serif;\n    font-variation-settings: "opsz" 12, "SOFT" 30;', css)
        self.assertIn('font-family: "Brand Reading"; src: url("' + (self.church / "brand/type/Reading-Italic.ttf").resolve().as_uri() + '"); font-weight: 100 900; font-style: italic;', css)

    def test_bulletin_sets_titles_and_labels_in_the_brand_faces(self):
        css = build_css("modern", self.brand, self.church)
        self.assertIn('@font-face { font-family: "Brand Display"', css)
        self.assertIn('font-family: "Brand Display", "Source Serif 4", Georgia, serif;\n    font-size: 40pt;', css)
        self.assertIn('.hymn-head {\n    font-family: "Brand Text", "Source Sans 3"', css)
        self.assertIn('body {\n    font-family: "Source Serif 4", Georgia, serif;\n    font-variation-settings: normal;', css)
        neutral = build_css("modern", {"colors": self.brand["colors"]}, self.church)
        self.assertNotIn("Brand Display", neutral.split("*/", 1)[-1])
        self.assertIn('.hymn-head {\n    font-family: "Source Sans 3"', neutral)

    def test_bulletin_pdf_embeds_the_brand_faces(self):
        try:
            import weasyprint
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("WeasyPrint and pypdf are needed to render")
        html = (f"<style>{build_css('modern', self.brand, self.church)}</style>"
                '<div class="cover"><h1 class="cover-occasion">The Feast</h1>'
                '<p class="cover-kicker">Holy Eucharist</p></div><p>Body text.</p>')
        out = self.church / "proof.pdf"
        weasyprint.HTML(string=html).write_pdf(out)
        names = {str(f.get_object()["/BaseFont"]) for page in PdfReader(out).pages
                 for f in page["/Resources"]["/Font"].values()}
        self.assertTrue(any("Brand-Display" in n for n in names), names)
        self.assertTrue(any("Brand-Text" in n for n in names), names)

    def test_finance_report_uses_the_brand_faces(self):
        spec = importlib.util.spec_from_file_location("report_renderer_brand_type", FINANCE)
        renderer = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(FINANCE.parent), *sys.path]):
            spec.loader.exec_module(renderer)
        renderer.CHURCH_ROOT = self.church
        theme, log = renderer.resolve_theme(self.brand, {})
        self.assertEqual((theme["heading"], theme["body"]), ("Brand Display", "Brand Text"))
        css, used = renderer.font_css(theme)
        self.assertIn('font-family: "Brand Display"', css)
        self.assertNotIn("googleapis", css)
        self.assertIn("Brand Text: the church's brand files", used)
        plain, _ = renderer.resolve_theme(json.loads(json.dumps({"colors": self.brand["colors"]})), {})
        self.assertEqual(plain["heading"], "Source Serif 4")


class BrandFontSafetyTest(unittest.TestCase):
    """Every renderer embeds brand fonts in a PDF, so the files are checked in one place."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = Path(self.temp.name).resolve() / "church"
        (self.church / "brand" / "type").mkdir(parents=True)

    def brand(self, rel: str) -> dict:
        return {"brand_system": {"type": {"display": {"family": "Test", "files": {"regular": rel}}}}}

    def test_a_missing_file_is_skipped_and_the_renderer_keeps_its_own_faces(self):
        self.assertEqual(brand_faces(self.brand("brand/type/absent.ttf"), self.church), ("", {}))

    def test_a_link_a_file_outside_the_folder_and_an_oversized_file_are_refused(self):
        from skills.bulletin.renderer import brand_type
        outside = Path(self.temp.name).resolve() / "outside.ttf"
        outside.write_bytes(b"synthetic font")
        (self.church / "brand" / "type" / "linked.ttf").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "regular file inside"):
            brand_faces(self.brand("brand/type/linked.ttf"), self.church)
        with self.assertRaisesRegex(ValueError, "stay inside"):
            brand_faces(self.brand("../outside.ttf"), self.church)
        big = self.church / "brand" / "type" / "big.ttf"
        big.write_bytes(b"x")
        with mock.patch.object(brand_type, "MAX_FONT_BYTES", 0):
            with self.assertRaisesRegex(ValueError, "limit"):
                brand_faces(self.brand("brand/type/big.ttf"), self.church)


if __name__ == "__main__":
    unittest.main()
