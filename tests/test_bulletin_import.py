from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from weasyprint import HTML

from skills.onboarding.bulletin_import import (
    BulletinImportError, import_bulletin, list_imports, read_manifest,
)
from tests.helpers import make_church

# A stencil bit pattern (4x4, one byte per row, 4 high bits used) that is not
# symmetric, so an inverted Decode array produces a genuinely different
# painted shape rather than an accidental palindrome.
_STENCIL_ROWS = (0b10010000, 0b01100000, 0b01100000, 0b10000000)


def _alpha_logo_png(path: Path) -> None:
    image = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([50, 10, 70, 110], fill=(180, 20, 20, 255))
    draw.rectangle([10, 50, 110, 70], fill=(180, 20, 20, 255))
    image.save(path)


def _pdf_from_html(html: str, destination: Path) -> Path:
    HTML(string=html).write_pdf(destination)
    return destination


def _stencil_pdf(destination: Path, decode: tuple[int, int]) -> Path:
    """Hand-build a one-page PDF with a 1-bit /ImageMask stencil so we can
    prove the importer respects the PDF-level Decode array rather than the
    raw bit pattern."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    stencil = DecodedStreamObject()
    stencil.set_data(bytes(_STENCIL_ROWS))
    stencil[NameObject("/Type")] = NameObject("/XObject")
    stencil[NameObject("/Subtype")] = NameObject("/Image")
    stencil[NameObject("/Width")] = NumberObject(4)
    stencil[NameObject("/Height")] = NumberObject(4)
    stencil[NameObject("/ImageMask")] = BooleanObject(True)
    stencil[NameObject("/BitsPerComponent")] = NumberObject(1)
    stencil[NameObject("/Decode")] = ArrayObject([NumberObject(decode[0]), NumberObject(decode[1])])
    stencil_ref = writer._add_object(stencil)
    content = DecodedStreamObject()
    content.set_data(b"q 0.78 0.12 0.12 rg 160 0 0 160 20 20 cm /Stencil1 Do Q")
    content_ref = writer._add_object(content)
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Stencil1"): stencil_ref})
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = content_ref
    with open(destination, "wb") as handle:
        writer.write(handle)
    return destination


class BulletinImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.church = make_church(self.tmp)
        self.logo_path = self.tmp / "logo.png"
        _alpha_logo_png(self.logo_path)

    def test_masked_logo_keeps_alpha(self):
        pdf_path = _pdf_from_html(f"""
            <html><body>
              <h1>Test Church</h1>
              <img src="file://{self.logo_path}" style="width:100px;height:100px;">
            </body></html>
        """, self.tmp / "logo-bulletin.pdf")
        manifest = import_bulletin(self.church, pdf_path, original_filename="logo-bulletin.pdf")
        images = manifest["pages"][0]["images"]
        self.assertEqual(len(images), 1)
        asset = images[0]
        self.assertTrue(asset["has_alpha"])
        self.assertFalse(asset["alpha_composite_warning"])
        self.assertFalse(asset["stencil"])
        extracted = Image.open(self.church / asset["asset_path"])
        self.assertEqual(extracted.mode, "RGBA")
        self.assertEqual(extracted.getpixel((0, 0))[3], 0)
        r, g, b, a = extracted.getpixel((60, 60))
        self.assertEqual(a, 255)
        self.assertGreater(r, 100)

    def test_image_only_page_is_not_treated_as_empty(self):
        pdf_path = _pdf_from_html(f"""
            <html><body>
              <img src="file://{self.logo_path}" style="width:80px;height:80px;">
            </body></html>
        """, self.tmp / "music-only.pdf")
        manifest = import_bulletin(self.church, pdf_path)
        page = manifest["pages"][0]
        self.assertEqual(page["text_length"], 0)
        self.assertEqual(len(page["images"]), 1)
        self.assertTrue((self.church / page["render_path"]).is_file())
        self.assertTrue((self.church / page["images"][0]["asset_path"]).is_file())

    def test_neighboring_text_does_not_bleed_into_asset(self):
        pdf_path = _pdf_from_html(f"""
            <html><body>
              <p>The Celebrant continues with a printed rubric right here.</p>
              <img src="file://{self.logo_path}" style="width:80px;height:80px;">
              <p>A second rubric appears directly below the image.</p>
            </body></html>
        """, self.tmp / "crop-case.pdf")
        manifest = import_bulletin(self.church, pdf_path)
        page = manifest["pages"][0]
        self.assertIn("printed rubric", (self.church / page["text_path"]).read_text())
        asset = page["images"][0]
        with Image.open(self.church / asset["asset_path"]) as extracted, \
                Image.open(self.church / page["render_path"]) as rendered:
            self.assertEqual(extracted.size, (120, 120))
            self.assertNotEqual(extracted.size, rendered.size)

    def test_reimport_same_bytes_is_idempotent(self):
        pdf_path = _pdf_from_html("<html><body><p>Plain bulletin text.</p></body></html>", self.tmp / "plain.pdf")
        first = import_bulletin(self.church, pdf_path)
        second = import_bulletin(self.church, pdf_path)
        self.assertEqual(first, second)
        self.assertEqual(len(list_imports(self.church)), 1)

    def test_idempotent_reimport_repairs_damaged_snapshot(self):
        pdf_path = _pdf_from_html("<html><body><p>Repair me.</p></body></html>", self.tmp / "repair.pdf")
        first = import_bulletin(self.church, pdf_path)
        page_render = self.church / first["pages"][0]["render_path"]
        self.assertTrue(page_render.is_file())
        page_render.unlink()
        self.assertFalse(page_render.is_file())
        repaired = import_bulletin(self.church, pdf_path)
        self.assertEqual(repaired, first)
        self.assertTrue(page_render.is_file())

    def test_source_hash_is_recorded_and_readable(self):
        pdf_path = _pdf_from_html("<html><body><p>Hashed content.</p></body></html>", self.tmp / "hashed.pdf")
        manifest = import_bulletin(self.church, pdf_path)
        reread = read_manifest(self.church, manifest["import_id"])
        self.assertEqual(reread["source"]["sha256"], manifest["source"]["sha256"])
        self.assertEqual(len(manifest["source"]["sha256"]), 64)

    def test_rejects_non_pdf(self):
        fake = self.tmp / "not-a-pdf.txt"
        fake.write_text("hello")
        with self.assertRaises(BulletinImportError):
            import_bulletin(self.church, fake)

    def test_rejects_non_church_folder(self):
        pdf_path = _pdf_from_html("<html><body><p>x</p></body></html>", self.tmp / "x.pdf")
        with self.assertRaises(BulletinImportError):
            import_bulletin(self.tmp / "not-a-church", pdf_path)

    def test_read_manifest_rejects_path_traversal_import_id(self):
        with self.assertRaises(BulletinImportError):
            read_manifest(self.church, "../../../../etc")

    def test_stencil_inversion_produces_true_alpha_inverse(self):
        normal_pdf = _stencil_pdf(self.tmp / "stencil-normal.pdf", decode=(0, 1))
        inverted_pdf = _stencil_pdf(self.tmp / "stencil-inverted.pdf", decode=(1, 0))
        normal = import_bulletin(self.church, normal_pdf, original_filename="stencil-normal.pdf")
        inverted = import_bulletin(self.church, inverted_pdf, original_filename="stencil-inverted.pdf")
        normal_asset = normal["pages"][0]["images"][0]
        inverted_asset = inverted["pages"][0]["images"][0]
        self.assertTrue(normal_asset["stencil"])
        self.assertTrue(inverted_asset["stencil"])
        normal_image = Image.open(self.church / normal_asset["asset_path"])
        inverted_image = Image.open(self.church / inverted_asset["asset_path"])
        self.assertEqual(normal_image.size, inverted_image.size)
        normal_alpha = normal_image.getchannel("A")
        inverted_alpha = inverted_image.getchannel("A")
        pixels_differ = False
        for xy in [(x, y) for x in range(normal_image.width) for y in range(normal_image.height)]:
            a1 = normal_alpha.getpixel(xy)
            a2 = inverted_alpha.getpixel(xy)
            self.assertEqual(a1 + a2, 255, f"alpha at {xy} should be an exact inverse, got {a1} and {a2}")
            if a1 != a2:
                pixels_differ = True
        self.assertTrue(pixels_differ, "an asymmetric stencil pattern must produce different shapes when inverted")

    def test_symlinked_import_root_cannot_write_outside_church(self):
        outside = self.tmp / "outside-escape"
        outside.mkdir()
        (self.church / "onboarding").symlink_to(outside)
        pdf_path = _pdf_from_html("<html><body><p>Escape attempt.</p></body></html>", self.tmp / "escape.pdf")
        with self.assertRaises(BulletinImportError):
            import_bulletin(self.church, pdf_path)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
