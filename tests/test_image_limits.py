from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from PIL import Image

from tools.image_limits import ImageInputError, MAX_IMAGE_BYTES, open_raster


def png_header(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


class ImageLimitsTest(unittest.TestCase):
    def test_oversized_header_is_rejected_before_load_or_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            path.write_bytes(png_header(5000, 4000))
            with mock.patch.object(Image.Image, "load", side_effect=AssertionError("pixels decoded")), \
                    mock.patch.object(Image.Image, "convert", side_effect=AssertionError("pixels converted")):
                with self.assertRaises(ImageInputError):
                    with open_raster(path):
                        self.fail("oversized image was accepted")

    def test_file_byte_cap_is_checked_before_pillow_opens_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            with path.open("wb") as handle:
                handle.truncate(MAX_IMAGE_BYTES + 1)
            with mock.patch.object(Image, "open", side_effect=AssertionError("Pillow opened oversized file")):
                with self.assertRaises(ImageInputError):
                    with open_raster(path):
                        self.fail("oversized file was accepted")

    def test_actual_format_must_be_an_accepted_raster(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-png.png"
            Image.new("RGB", (2, 2), "white").save(path, format="GIF")
            with self.assertRaises(ImageInputError):
                with open_raster(path, allowed_formats=frozenset({"PNG"})):
                    self.fail("mismatched raster was accepted")

    def test_decompression_bomb_warning_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bomb.png"
            path.write_bytes(png_header(20, 20))
            with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 100):
                with self.assertRaises(ImageInputError):
                    with open_raster(path):
                        self.fail("decompression bomb warning was ignored")

    def test_normal_transparent_png_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transparent.png"
            Image.new("RGBA", (4, 4), (10, 20, 30, 0)).save(path)
            with open_raster(path) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.convert("RGBA").getchannel("A").getextrema(), (0, 0))


if __name__ == "__main__":
    unittest.main()
