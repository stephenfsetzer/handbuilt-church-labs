from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock, PropertyMock

from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.errors import LimitReachedError
from pypdf.generic import ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from weasyprint import HTML

from skills.onboarding.bulletin_import import (
    MAX_PDF_BYTES, MAX_PDF_PAGES, MAX_RENDER_OUTPUT_BYTES, MAX_TOTAL_RENDER_PIXELS,
    MAX_PDF_GRAPH_NODES_PER_PAGE,
    MAX_CONTENT_OPERATIONS_PER_PAGE, MAX_DECODED_CONTENT_BYTES_PER_PAGE,
    BulletinImportError, _add_bounded_output, _bounded_pdf_inspection, _extract_page_assets,
    _hash_file_bounded, _inspect_pdf, _preflight_page_images, _read_source_pdf, _render_geometry,
    _run, _run_text, _validate_render_dpi, import_bulletin, list_imports, read_manifest,
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

    def test_oversized_cached_snapshot_is_rebuilt_from_current_source(self):
        pdf_path = _pdf_from_html("<html><body><p>Restore a bounded snapshot.</p></body></html>",
                                  self.tmp / "cached-snapshot.pdf")
        first = import_bulletin(self.church, pdf_path)
        snapshot = self.church / first["source"]["path"]
        with snapshot.open("r+b") as handle:
            handle.truncate(MAX_PDF_BYTES + 1)
        with self.assertRaisesRegex(BulletinImportError, "cached bulletin snapshot"):
            _hash_file_bounded(snapshot, MAX_PDF_BYTES)

        repaired = import_bulletin(self.church, pdf_path)
        self.assertEqual(repaired, first)
        self.assertEqual(snapshot.stat().st_size, pdf_path.stat().st_size)

    def test_oversized_raw_image_dimensions_are_rejected_before_decode(self):
        class OversizedImage:
            indirect_reference = Mock(get_object=Mock(return_value={"/Width": 5001, "/Height": 5000}))

            def __init__(self):
                self.decode_attempted = False

            @property
            def image(self):
                self.decode_attempted = True
                raise AssertionError("oversized image must not be decoded")

        image = OversizedImage()

        class ImageList:
            def __len__(self):
                return 1

            def __getitem__(self, _index):
                return image

        class Page:
            images = ImageList()

        assets = _extract_page_assets(Page(), 1, self.tmp)
        self.assertEqual(len(assets), 1)
        self.assertIn("invalid or oversized dimensions", assets[0]["error"])
        self.assertFalse(image.decode_attempted)

    def test_oversized_xobject_is_preflighted_before_page_images_access(self):
        pdf = self.tmp / "oversized-xobject.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image[NameObject("/Type")] = NameObject("/XObject")
        image[NameObject("/Subtype")] = NameObject("/Image")
        image[NameObject("/Width")] = NumberObject(5001)
        image[NameObject("/Height")] = NumberObject(5000)
        image[NameObject("/BitsPerComponent")] = NumberObject(1)
        image[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
        image_ref = writer._add_object(image)
        content = DecodedStreamObject()
        content.set_data(b"q /Im0 Do Q")
        content_ref = writer._add_object(content)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref}),
        })
        page[NameObject("/Contents")] = content_ref
        with pdf.open("wb") as handle:
            writer.write(handle)

        with patch.object(PageObject, "images", new_callable=PropertyMock,
                          side_effect=AssertionError("page.images must not be touched")) as images_property, \
                patch("pypdf.generic._image_xobject._xobj_to_image",
                      side_effect=AssertionError("image decoder must not run")) as decoder:
            inspection = _inspect_pdf(pdf, self.tmp / "xobject-assets", 150)

        images_property.assert_not_called()
        decoder.assert_not_called()
        self.assertEqual(len(inspection["images"]), 1)
        self.assertIn("Could not safely extract page images", inspection["images"][0][0]["error"])
        self.assertIn("invalid or oversized dimensions", inspection["images"][0][0]["error"])

    def test_oversized_inline_image_settings_are_preflighted_before_page_images_access(self):
        pdf = self.tmp / "oversized-inline-image.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        content = DecodedStreamObject()
        content.set_data(b"BI /W 5001 /H 5000 /BPC 1 /CS /G ID \x00 EI Q")
        page[NameObject("/Contents")] = writer._add_object(content)
        with pdf.open("wb") as handle:
            writer.write(handle)

        with patch.object(PageObject, "images", new_callable=PropertyMock,
                          side_effect=AssertionError("page.images must not be touched")) as images_property, \
                patch("pypdf.generic._image_xobject._xobj_to_image",
                      side_effect=AssertionError("image decoder must not run")) as decoder:
            inspection = _inspect_pdf(pdf, self.tmp / "inline-assets", 150)

        images_property.assert_not_called()
        decoder.assert_not_called()
        self.assertEqual(len(inspection["images"]), 1)
        self.assertIn("Could not safely extract page images", inspection["images"][0][0]["error"])
        self.assertIn("invalid or oversized dimensions", inspection["images"][0][0]["error"])

    def test_inherited_image_resources_are_checked_before_rendering(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image.update({NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(5001),
                      NameObject("/Height"): NumberObject(5000)})
        parent = page["/Parent"].get_object()
        parent[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): writer._add_object(image)})})
        page.pop("/Resources", None)
        from skills.onboarding.bulletin_import import _preflight_page_images
        with patch.object(PageObject, "images", new_callable=PropertyMock) as images_property:
            with self.assertRaisesRegex(BulletinImportError, "oversized dimensions"):
                _preflight_page_images(page)
        images_property.assert_not_called()

    def test_small_inline_image_still_extracts_after_preflight(self):
        pdf = self.tmp / "small-inline-image.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        content = DecodedStreamObject()
        content.set_data(b"q BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 EI Q")
        page[NameObject("/Contents")] = writer._add_object(content)
        with pdf.open("wb") as handle:
            writer.write(handle)
        assets = self.tmp / "small-inline-assets"
        assets.mkdir()
        inspection = _inspect_pdf(pdf, assets, 150)
        image = inspection["images"][0][0]
        self.assertNotIn("error", image)
        self.assertEqual((image["width"], image["height"]), (1, 1))
        self.assertTrue((assets / image["asset_path"]).is_file())

    def test_unsafe_embedded_artwork_blocks_poppler_rendering(self):
        pdf = self.tmp / "unsafe-artwork.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        content = DecodedStreamObject()
        content.set_data(b"q BI /W 5001 /H 5000 /BPC 1 /CS /G ID \x00 EI Q")
        page[NameObject("/Contents")] = writer._add_object(content)
        with pdf.open("wb") as handle:
            writer.write(handle)
        with patch("skills.onboarding.bulletin_import._run") as render, \
                patch("skills.onboarding.bulletin_import._run_text") as extract:
            with self.assertRaisesRegex(BulletinImportError, "artwork that cannot be processed safely"):
                import_bulletin(self.church, pdf)
        render.assert_not_called()
        extract.assert_not_called()

    def test_nested_form_soft_mask_is_preflighted_before_image_decode(self):
        pdf = self.tmp / "oversized-form-soft-mask.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)

        mask = DecodedStreamObject()
        mask.set_data(b"\x00")
        mask[NameObject("/Type")] = NameObject("/XObject")
        mask[NameObject("/Subtype")] = NameObject("/Image")
        mask[NameObject("/Width")] = NumberObject(5001)
        mask[NameObject("/Height")] = NumberObject(5000)
        mask[NameObject("/BitsPerComponent")] = NumberObject(1)
        mask[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
        mask_ref = writer._add_object(mask)

        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image[NameObject("/Type")] = NameObject("/XObject")
        image[NameObject("/Subtype")] = NameObject("/Image")
        image[NameObject("/Width")] = NumberObject(1)
        image[NameObject("/Height")] = NumberObject(1)
        image[NameObject("/BitsPerComponent")] = NumberObject(8)
        image[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
        image[NameObject("/SMask")] = mask_ref
        image_ref = writer._add_object(image)

        form = DecodedStreamObject()
        form.set_data(b"q /Im0 Do Q")
        form[NameObject("/Type")] = NameObject("/XObject")
        form[NameObject("/Subtype")] = NameObject("/Form")
        form[NameObject("/BBox")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)])
        form[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref}),
        })
        form_ref = writer._add_object(form)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Fm0"): form_ref}),
        })
        content = DecodedStreamObject()
        content.set_data(b"q /Fm0 Do Q")
        page[NameObject("/Contents")] = writer._add_object(content)
        with pdf.open("wb") as handle:
            writer.write(handle)

        with patch.object(PageObject, "images", new_callable=PropertyMock,
                          side_effect=AssertionError("page.images must not be touched")) as images_property, \
                patch("pypdf.generic._image_xobject._xobj_to_image",
                      side_effect=AssertionError("image decoder must not run")) as decoder:
            inspection = _inspect_pdf(pdf, self.tmp / "form-assets", 150)

        images_property.assert_not_called()
        decoder.assert_not_called()
        self.assertIn("Could not safely extract page images", inspection["images"][0][0]["error"])
        self.assertIn("invalid or oversized dimensions", inspection["images"][0][0]["error"])

    def _write_unsafe_graph_pdf(self, kind: str) -> Path:
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image.update({NameObject("/Type"): NameObject("/XObject"),
                      NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(5001),
                      NameObject("/Height"): NumberObject(5000),
                      NameObject("/BitsPerComponent"): NumberObject(1),
                      NameObject("/ColorSpace"): NameObject("/DeviceGray")})
        image_ref = writer._add_object(image)
        form = DecodedStreamObject()
        form.set_data(b"q /Im0 Do Q")
        form.update({NameObject("/Type"): NameObject("/XObject"),
                     NameObject("/Subtype"): NameObject("/Form"),
                     NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0),
                                                        NumberObject(10), NumberObject(10)]),
                     NameObject("/Resources"): DictionaryObject({
                         NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})})})
        form_ref = writer._add_object(form)
        resources = DictionaryObject()
        if kind == "annotation":
            appearance = DictionaryObject({NameObject("/N"): form_ref, NameObject("/R"): form_ref,
                                           NameObject("/D"): form_ref})
            annot = DictionaryObject({NameObject("/Type"): NameObject("/Annot"),
                                      NameObject("/Subtype"): NameObject("/Stamp"),
                                      NameObject("/Rect"): ArrayObject([NumberObject(0), NumberObject(0),
                                                                         NumberObject(20), NumberObject(20)]),
                                      NameObject("/AP"): appearance})
            page[NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
        elif kind == "pattern":
            pattern = DecodedStreamObject()
            pattern.set_data(b"/Im0 Do")
            pattern.update({NameObject("/Type"): NameObject("/Pattern"),
                            NameObject("/PatternType"): NumberObject(1),
                            NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0),
                                                               NumberObject(10), NumberObject(10)]),
                            NameObject("/XStep"): NumberObject(10), NameObject("/YStep"): NumberObject(10),
                            NameObject("/Resources"): DictionaryObject({
                                NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})})})
            resources[NameObject("/Pattern")] = DictionaryObject({NameObject("/P1"): writer._add_object(pattern)})
        elif kind == "type3":
            charproc = DecodedStreamObject()
            charproc.set_data(b"/Im0 Do")
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type3"),
                                     NameObject("/FontBBox"): ArrayObject([NumberObject(0), NumberObject(0),
                                                                            NumberObject(10), NumberObject(10)]),
                                     NameObject("/FontMatrix"): ArrayObject([NumberObject(1), NumberObject(0),
                                                                             NumberObject(0), NumberObject(1),
                                                                             NumberObject(0), NumberObject(0)]),
                                     NameObject("/CharProcs"): DictionaryObject({
                                         NameObject("/g"): writer._add_object(charproc)}),
                                     NameObject("/Resources"): DictionaryObject({
                                         NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})}),
                                     NameObject("/Encoding"): DictionaryObject({NameObject("/Differences"): ArrayObject([])}),
                                     NameObject("/FirstChar"): NumberObject(0), NameObject("/LastChar"): NumberObject(0),
                                     NameObject("/Widths"): ArrayObject([NumberObject(10)])})
            resources[NameObject("/Font")] = DictionaryObject({NameObject("/F3"): writer._add_object(font)})
        elif kind == "soft-mask-group":
            resources[NameObject("/ExtGState")] = DictionaryObject({NameObject("/GS1"): DictionaryObject({
                NameObject("/Type"): NameObject("/ExtGState"),
                NameObject("/SMask"): DictionaryObject({NameObject("/S"): NameObject("/Alpha"),
                                                        NameObject("/G"): form_ref})})})
        page[NameObject("/Resources")] = resources
        path = self.tmp / f"unsafe-{kind}.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def test_annotation_pattern_type3_and_soft_mask_images_are_preflighted(self):
        for kind in ("annotation", "pattern", "type3", "soft-mask-group"):
            with self.subTest(kind=kind):
                pdf = self._write_unsafe_graph_pdf(kind)
                with patch.object(PageObject, "images", new_callable=PropertyMock,
                                  side_effect=AssertionError("page.images must not be touched")) as images_property, \
                        patch("pypdf.generic._image_xobject._xobj_to_image",
                              side_effect=AssertionError("image decoder must not run")) as decoder:
                    inspection = _inspect_pdf(pdf, self.tmp / f"assets-{kind}", 150)
                images_property.assert_not_called()
                decoder.assert_not_called()
                self.assertIn("invalid or oversized dimensions", inspection["geometry"][0]["image_preflight_error"])
                with patch("skills.onboarding.bulletin_import._run") as render, \
                        patch("skills.onboarding.bulletin_import._run_text") as extract:
                    with self.assertRaisesRegex(BulletinImportError, "artwork that cannot be processed safely"):
                        import_bulletin(self.church, pdf)
                render.assert_not_called()
                extract.assert_not_called()

    def test_safe_cyclic_and_shared_resources_finish_preflight(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image.update({NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(1), NameObject("/Height"): NumberObject(1)})
        image_ref = writer._add_object(image)
        resources = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})})
        form = DecodedStreamObject()
        form.set_data(b"q Q")
        form.update({NameObject("/Subtype"): NameObject("/Form"),
                     NameObject("/Resources"): resources})
        form_ref = writer._add_object(form)
        resources["/XObject"][NameObject("/Fm0")] = form_ref
        page[NameObject("/Resources")] = resources
        # The writer's direct object graph is enough to exercise the cycle
        # without asking pypdf or Poppler to decode any image.
        self.assertEqual(_preflight_page_images(page)["images"], 1)

    def test_graph_node_budget_fails_closed(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        annotations = ArrayObject()
        for _ in range(MAX_PDF_GRAPH_NODES_PER_PAGE // 2 + 1):
            appearance = DecodedStreamObject()
            appearance.set_data(b"q Q")
            appearance_ref = writer._add_object(appearance)
            annotation = DictionaryObject({NameObject("/AP"): DictionaryObject({NameObject("/N"): appearance_ref})})
            annotations.append(writer._add_object(annotation))
        page[NameObject("/Annots")] = annotations
        with self.assertRaisesRegex(BulletinImportError, "too many artwork resources"):
            _preflight_page_images(page)

    def test_content_operation_and_decoded_byte_budgets_fail_closed(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        content = DecodedStreamObject()
        content.set_data(b"q Q q Q")
        page[NameObject("/Contents")] = writer._add_object(content)
        with patch("skills.onboarding.bulletin_import.MAX_CONTENT_OPERATIONS_PER_PAGE", 2):
            with self.assertRaisesRegex(BulletinImportError, "too many content operations"):
                _preflight_page_images(page)
        with patch("skills.onboarding.bulletin_import.MAX_DECODED_CONTENT_BYTES_PER_PAGE", 2):
            with self.assertRaisesRegex(BulletinImportError, "too much decoded artwork content"):
                _preflight_page_images(page)

    def test_annotation_images_and_masks_share_document_output_budget_before_decode(self):
        writer = PdfWriter()
        for page_number in range(2):
            page = writer.add_blank_page(width=612, height=792)
            mask = DecodedStreamObject()
            mask.set_data(b"\x00")
            mask.update({NameObject("/Subtype"): NameObject("/Image"),
                         NameObject("/Width"): NumberObject(5000),
                         NameObject("/Height"): NumberObject(5000),
                         NameObject("/BitsPerComponent"): NumberObject(1),
                         NameObject("/ColorSpace"): NameObject("/DeviceGray")})
            mask_ref = writer._add_object(mask)
            image = DecodedStreamObject()
            image.set_data(b"\x00")
            image.update({NameObject("/Subtype"): NameObject("/Image"),
                          NameObject("/Width"): NumberObject(5000),
                          NameObject("/Height"): NumberObject(5000),
                          NameObject("/BitsPerComponent"): NumberObject(8),
                          NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                          NameObject("/SMask"): mask_ref})
            image_ref = writer._add_object(image)
            form = DecodedStreamObject()
            form.set_data(b"/Im0 Do")
            form.update({NameObject("/Subtype"): NameObject("/Form"),
                         NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0),
                                                            NumberObject(10), NumberObject(10)]),
                         NameObject("/Resources"): DictionaryObject({
                             NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})})})
            form_ref = writer._add_object(form)
            annotation = DictionaryObject({NameObject("/Subtype"): NameObject("/Stamp"),
                                           NameObject("/Rect"): ArrayObject([NumberObject(0), NumberObject(0),
                                                                              NumberObject(20), NumberObject(20)]),
                                           NameObject("/AP"): DictionaryObject({NameObject("/N"): form_ref})})
            page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
        pdf = self.tmp / "annotation-image-budget.pdf"
        with pdf.open("wb") as handle:
            writer.write(handle)

        with patch.object(PageObject, "images", new_callable=PropertyMock,
                          side_effect=AssertionError("page.images must not be touched")) as images_property, \
                patch("pypdf.generic._image_xobject._xobj_to_image",
                      side_effect=AssertionError("image decoder must not run")) as decoder:
            inspection = _inspect_pdf(pdf, self.tmp / "budget-assets", 150)
        images_property.assert_not_called()
        decoder.assert_not_called()
        self.assertNotIn("image_preflight_error", inspection["geometry"][0])
        self.assertIn("document image-output limit", inspection["geometry"][1]["image_preflight_error"])
        with patch("skills.onboarding.bulletin_import._run") as render, \
                patch("skills.onboarding.bulletin_import._run_text") as extract:
            with self.assertRaisesRegex(BulletinImportError, "artwork that cannot be processed safely"):
                import_bulletin(self.church, pdf)
        render.assert_not_called()
        extract.assert_not_called()

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

    def test_source_byte_limit_is_checked_before_opening_file(self):
        oversized = self.tmp / "oversized.pdf"
        oversized.write_bytes(b"%PDF-")
        with oversized.open("r+b") as handle:
            handle.truncate(MAX_PDF_BYTES + 1)
        with patch.object(Path, "open", side_effect=AssertionError("source must not be read")):
            with self.assertRaisesRegex(BulletinImportError, "32 MiB"):
                _read_source_pdf(oversized)

    def test_render_dpi_and_page_geometry_limits(self):
        self.assertEqual(_render_geometry(612, 792, 150), (1275, 1650, 2_103_750))
        for invalid_dpi in (71, 301, True):
            with self.subTest(dpi=invalid_dpi), self.assertRaises(BulletinImportError):
                _validate_render_dpi(invalid_dpi)
        with self.assertRaisesRegex(BulletinImportError, "too large"):
            _render_geometry(30_000, 792, 150)
        with self.assertRaisesRegex(BulletinImportError, "too large"):
            _render_geometry(200_000, 792, 300)

    def test_total_page_render_budget_rejects_excessive_output(self):
        self.assertGreater(MAX_RENDER_OUTPUT_BYTES, MAX_TOTAL_RENDER_PIXELS * 4)
        with self.assertRaisesRegex(BulletinImportError, "output limit"):
            _add_bounded_output(MAX_RENDER_OUTPUT_BYTES - 4, 5, MAX_RENDER_OUTPUT_BYTES, "Rendered pages")
        self.assertEqual(_add_bounded_output(10, 5, 15, "Rendered pages"), 15)

    def test_page_count_limit_is_checked_before_rendering(self):
        pdf = self.tmp / "too-many-pages.pdf"
        writer = PdfWriter()
        for _ in range(MAX_PDF_PAGES + 1):
            writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as handle:
            writer.write(handle)
        with self.assertRaisesRegex(BulletinImportError, "between 1 and 100 pages"):
            _inspect_pdf(pdf, self.tmp / "assets", 150)

    def test_total_page_pixel_limit_is_checked_before_rendering(self):
        pdf = self.tmp / "too-many-pixels.pdf"
        writer = PdfWriter()
        page_pixels = _render_geometry(612, 792, 150)[2]
        page_count = MAX_TOTAL_RENDER_PIXELS // page_pixels + 1
        for _ in range(page_count):
            writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as handle:
            writer.write(handle)
        with self.assertRaisesRegex(BulletinImportError, "total page-rendering limit"):
            _inspect_pdf(pdf, self.tmp / "pixel-assets", 150)

    def test_pdf_parser_timeout_terminates_worker(self):
        class StuckProcess:
            def __init__(self, **_kwargs):
                self.alive = True
                self.exitcode = None
                self.terminated = False

            def start(self):
                pass

            def join(self, _timeout=None):
                pass

            def is_alive(self):
                return self.alive

            def terminate(self):
                self.terminated = True
                self.alive = False

        process = StuckProcess()
        context = Mock()
        context.Process.return_value = process
        with patch("skills.onboarding.bulletin_import.multiprocessing.get_context", return_value=context), \
                patch("skills.onboarding.bulletin_import.PDF_PARSE_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(BulletinImportError, "took longer"):
                _bounded_pdf_inspection(self.tmp / "source.pdf", self.tmp, 150, self.tmp / "result.json")
        self.assertTrue(process.terminated)

    def test_poppler_timeout_is_reported_clearly(self):
        process = Mock()
        process.stderr = io.BytesIO()
        process.wait.side_effect = [subprocess.TimeoutExpired(["pdftoppm"], 1), 0]
        with patch("skills.onboarding.bulletin_import.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(BulletinImportError, "time limit"):
                _run(["pdftoppm"], timeout=1)
        process.kill.assert_called_once()

    def test_pdftotext_output_is_bounded(self):
        class NoisyProcess:
            def __init__(self, _args, *, stdout, **_kwargs):
                self.returncode = 0
                self.stdout = io.BytesIO(b"x" * 17)

            def kill(self):
                self.returncode = -9

            def wait(self, **_kwargs):
                return self.returncode

        with patch("skills.onboarding.bulletin_import.subprocess.Popen", NoisyProcess):
            with self.assertRaisesRegex(BulletinImportError, "output exceeded"):
                _run_text(["pdftotext"], timeout=1, max_bytes=16)

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

    def test_oversized_embedded_image_does_not_abort_the_import(self):
        """A real 16-page bulletin crashed the importer when one embedded
        image's decompressed size exceeded pypdf's zlib output limit: the
        exception surfaced while pypdf lazily decoded the image during
        ``for image_file in page.images``, outside any of our try/except
        blocks, and aborted the whole import -- losing every other page's
        text and renders along with it. Simulate that failure mode by
        making the first of two images on a page raise pypdf's
        LimitReachedError, and confirm the import still completes, the
        failing asset is recorded as an error, and the surrounding text and
        the second image are unaffected."""
        second_logo_path = self.tmp / "second-logo.png"
        second_image = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(second_image).ellipse([20, 20, 100, 100], fill=(20, 90, 180, 255))
        second_image.save(second_logo_path)
        pdf_path = _pdf_from_html(f"""
            <html><body>
              <p>Text before the oversized image.</p>
              <img src="file://{self.logo_path}" style="width:80px;height:80px;">
              <p>Text between the two images.</p>
              <img src="file://{second_logo_path}" style="width:60px;height:60px;">
            </body></html>
        """, self.tmp / "oversized-image.pdf")

        original_get_image = PageObject._get_image
        calls = {"n": 0}

        def flaky_get_image(self, id, obj=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LimitReachedError("Limit reached while decompressing. 175587 bytes remaining.")
            return original_get_image(self, id, obj)

        extracted_dir = self.tmp / "oversized-extracted"
        extracted_dir.mkdir()
        with patch.object(PageObject, "_get_image", flaky_get_image):
            inspection = _inspect_pdf(pdf_path, extracted_dir, 150)

        manifest = import_bulletin(self.church, pdf_path, original_filename="oversized-image.pdf")
        page = manifest["pages"][0]
        page_text = (self.church / page["text_path"]).read_text()
        self.assertIn("Text before the oversized image.", page_text)
        self.assertIn("Text between the two images.", page_text)
        images = inspection["images"][0]
        self.assertEqual(len(images), 2)
        self.assertIn("error", images[0])
        self.assertIn("Limit reached while decompressing", images[0]["error"])
        self.assertFalse((extracted_dir / images[0]["asset_path"]).is_file())
        self.assertNotIn("error", images[1])
        self.assertTrue((extracted_dir / images[1]["asset_path"]).is_file())

    def test_image_enumeration_failure_preserves_pages_and_saved_manifest(self):
        pdf_path = _pdf_from_html(f"""
            <html><body>
              <p>Text on the page with unreadable image references.</p>
              <div style="break-before:page">
                <p>Text on the following page.</p>
                <img src="file://{self.logo_path}" style="width:80px;height:80px;">
              </div>
            </body></html>
        """, self.tmp / "enumeration-failure.pdf")
        original_get_ids = PageObject._get_ids_image
        failed_pages = []

        def failing_first_page(page, *args, **kwargs):
            if not failed_pages:
                failed_pages.append(page)
            if page is failed_pages[0]:
                raise LimitReachedError("Synthetic image enumeration failure")
            return original_get_ids(page, *args, **kwargs)

        extracted_dir = self.tmp / "enumeration-extracted"
        extracted_dir.mkdir()
        with patch.object(PageObject, "_get_ids_image", failing_first_page):
            inspection = _inspect_pdf(pdf_path, extracted_dir, 150)
        self.assertEqual(inspection["page_count"], 2)
        self.assertEqual(len(inspection["images"]), 2)
        self.assertEqual(inspection["images"][0], [{
            "error": "Could not enumerate embedded images on this page: Synthetic image enumeration failure",
        }])
        self.assertEqual(len(inspection["images"][1]), 1)
        self.assertTrue((extracted_dir / inspection["images"][1][0]["asset_path"]).is_file())

        manifest = import_bulletin(self.church, pdf_path)
        self.assertEqual(len(manifest["pages"]), 2)
        first, second = manifest["pages"]
        for page, expected_text in (
            (first, "Text on the page with unreadable image references."),
            (second, "Text on the following page."),
        ):
            self.assertIn(expected_text, (self.church / page["text_path"]).read_text())
            self.assertTrue((self.church / page["render_path"]).is_file())
        self.assertEqual(len(second["images"]), 1)
        self.assertTrue((self.church / second["images"][0]["asset_path"]).is_file())
        self.assertEqual(read_manifest(self.church, manifest["import_id"]), manifest)
        with patch.object(PageObject, "_get_ids_image", side_effect=AssertionError("Unexpected re-import")):
            self.assertEqual(import_bulletin(self.church, pdf_path), manifest)

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
