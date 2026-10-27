"""Exercise the installed WOFF2 decoder through the PDF renderer."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

import brotli
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pypdf import PdfReader
from weasyprint import HTML


class RuntimeFontCodecTests(unittest.TestCase):
    def test_synthetic_woff2_is_decoded_and_embedded_with_the_patched_brotli(self):
        with tempfile.TemporaryDirectory() as temporary:
            font_path = Path(temporary) / 'riverbend-synthetic.woff2'
            builder = FontBuilder(1000, isTTF=True)
            builder.setupGlyphOrder(['.notdef', 'A'])
            builder.setupCharacterMap({65: 'A'})
            glyphs = {}
            for name in ['.notdef', 'A']:
                pen = TTGlyphPen(None)
                pen.moveTo((100, 0))
                pen.lineTo((500, 0))
                pen.lineTo((300, 700))
                pen.closePath()
                glyphs[name] = pen.glyph()
            builder.setupGlyf(glyphs)
            builder.setupHorizontalMetrics({name: (600, 50) for name in glyphs})
            builder.setupHorizontalHeader(ascent=800, descent=-200)
            builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
            builder.setupNameTable({'familyName': 'RiverbendSafety', 'styleName': 'Regular',
                                    'uniqueFontIdentifier': 'RiverbendSafety-Regular',
                                    'fullName': 'RiverbendSafety Regular', 'psName': 'RiverbendSafety-Regular'})
            builder.setupPost()
            builder.font.flavor = 'woff2'
            builder.font.save(font_path)
            document = HTML(string=(
                '<style>@font-face{font-family:RiverbendSafety;src:url("'
                + font_path.as_uri() + '")}body{font-family:RiverbendSafety}</style><p>AAA</p>'
            )).write_pdf()
            fonts = PdfReader(BytesIO(document)).pages[0]['/Resources']['/Font']
            embedded = [str(font.get_object().get('/BaseFont')) for font in fonts.values()]
            self.assertTrue(any('RiverbendSafety' in name for name in embedded), embedded)
            self.assertEqual(brotli.__version__, '1.2.1')


if __name__ == '__main__':
    unittest.main()
