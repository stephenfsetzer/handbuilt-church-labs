import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from skills.bulletin.renderer import render_bulletin


class MusicPrintWidthTests(unittest.TestCase):
    def _width(self, hymn):
        with tempfile.TemporaryDirectory() as tmp:
            Image.new("RGB", (1200, 400), "black").save(Path(tmp) / "m.png", dpi=(200, 200))
            html = render_bulletin.hymn_block("Sanctus", {"title": "Synthetic", "images": ["m.png"], **hymn},
                                              Path(tmp), full_page=False, content_w=5.7)
        return float(re.search(r"width:([\d.]+)in", html).group(1))

    def test_default_uses_text_column(self):
        self.assertAlmostEqual(self._width({}), 5.7, places=2)

    def test_print_width_narrows_music(self):
        self.assertAlmostEqual(self._width({"print_width": 4.5}), 4.5, places=2)

    def test_invalid_print_width_is_ignored(self):
        self.assertAlmostEqual(self._width({"print_width": "wide"}), 5.7, places=2)


if __name__ == "__main__":
    unittest.main()
