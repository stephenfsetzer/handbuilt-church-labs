from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce
from skills.bulletin.renderer.render_bulletin import cover_logo, cover_page
from tests.helpers import bulletin_input, make_church


class ClassicCoverLogoTests(unittest.TestCase):
    def test_banner_only_logo_is_on_first_pdf_page_and_booklet_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            (church / 'brand').mkdir(exist_ok=True)
            Image.new('RGB', (1000, 180), '#532775').save(church / 'brand/banner.png')
            brand_file = church / 'brand.json'
            brand = json.loads(brand_file.read_text())
            brand['logo'] = {'banner': 'brand/banner.png'}
            brand_file.write_text(json.dumps(brand))
            result = produce(church, bulletin_input())
            self.assertEqual(result['status'], 'ready_for_review', result)
            week = Path(result['week_folder'])
            pdf = PdfReader(next(week.glob('*classic.pdf')))
            self.assertTrue(pdf.pages[0].images)
            self.assertIn('Public Test Parish', pdf.pages[0].extract_text())
            booklet = PdfReader(next(week.glob('*booklet-11x17.pdf')))
            self.assertTrue(booklet.pages[0].images)

    def test_uses_existing_alternative_and_prefers_church_mark_to_shield(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('mark.png', 'banner.png', 'shield.png'):
                Image.new('RGB', (80, 80), '#532775').save(root / name)
            brand = {'logo': {'mark': 'mark.png', 'banner': 'banner.png', 'episcopal_shield': 'shield.png'}}
            self.assertEqual(cover_logo(brand, root), (root / 'mark.png').resolve())
            brand['logo']['mark'] = 'missing.png'
            self.assertEqual(cover_logo(brand, root), (root / 'banner.png').resolve())
            brand['logo']['banner'] = 'https://parish.invalid/logo.svg'
            self.assertEqual(cover_logo(brand, root), (root / 'shield.png').resolve())

    def test_configured_missing_remote_or_corrupt_logo_blocks_production(self):
        for raw in ('brand/missing.png', 'https://parish.invalid/logo.svg', 'brand/broken.png', 'brand/broken.svg'):
            with self.subTest(logo=raw), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                (church / 'brand').mkdir(exist_ok=True)
                (church / 'brand/broken.png').write_text('not an image')
                (church / 'brand/broken.svg').write_text('<html>not an SVG</html>')
                path = church / 'brand.json'
                brand = json.loads(path.read_text())
                brand['logo'] = {'banner': raw}
                path.write_text(json.dumps(brand))
                result = produce(church, bulletin_input())
                self.assertNotEqual(result['status'], 'ready_for_review', result)
                self.assertIn('church_logo_unavailable', json.dumps(result))
                self.assertFalse(list((church / 'bulletins').rglob('*.pdf')))

    def test_local_svg_logo_is_used_on_classic_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = root / 'logo.svg'
            logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="purple"/></svg>')
            brand = {'church': {'name': 'Public Test Parish'}, 'logo': {'banner': 'logo.svg'}}
            html = cover_page(bulletin_input(), brand, root, 'classic')
            self.assertIn(logo.resolve().as_uri(), html)
            self.assertIn('cover-mark', html)

    def test_no_provided_logo_keeps_name_only_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            brand = {'church': {'name': 'Public Test Parish'}, 'logo': {'banner': ''}}
            html = cover_page(bulletin_input(), brand, Path(tmp), 'classic')
            self.assertNotIn('<img', html)
            self.assertIn('Public Test Parish', html)

    def test_modern_uses_mark_when_banner_is_missing_or_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new('RGB', (80, 80), '#532775').save(root / 'mark.png')
            for banner in ('', 'missing.png', 'https://parish.invalid/logo.svg'):
                brand = {'church': {'name': 'Public Test Parish'}, 'logo': {'mark': 'mark.png', 'banner': banner}}
                html = cover_page(bulletin_input(), brand, root, 'modern')
                self.assertIn((root / 'mark.png').resolve().as_uri(), html)
                self.assertIn('Public Test Parish', html)

    def test_modern_prefers_banner_when_both_shapes_are_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('mark.png', 'banner.png'):
                Image.new('RGB', (80, 80), '#532775').save(root / name)
            brand = {'logo': {'mark': 'mark.png', 'banner': 'banner.png'}}
            self.assertEqual(cover_logo(brand, root, 'modern'), (root / 'banner.png').resolve())

    def test_modern_remote_only_logo_blocks_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            path = church / 'brand.json'
            brand = json.loads(path.read_text())
            brand['logo'] = {'banner': 'https://parish.invalid/logo.svg'}
            path.write_text(json.dumps(brand))
            request = bulletin_input()
            request['template'] = 'modern'
            result = produce(church, request)
            self.assertIn('church_logo_unavailable', json.dumps(result))
