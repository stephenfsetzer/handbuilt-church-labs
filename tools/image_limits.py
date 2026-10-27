"""Bound and validate raster image inputs before Pillow decodes pixels."""

from __future__ import annotations

import os
import warnings
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from PIL import Image

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
RASTER_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF"})


class ImageInputError(ValueError):
    """The image exceeds a safe input bound or is not an accepted raster."""


def _check_header(image: Image.Image, allowed_formats: frozenset[str], path: Path) -> None:
    if image.format not in allowed_formats:
        raise ImageInputError(f"Unsupported raster format: {path.name}")
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ImageInputError(f"Image dimensions exceed the {MAX_IMAGE_PIXELS:,}-pixel limit: {path.name}")


@contextmanager
def open_raster(path: str | Path, *, allowed_formats: frozenset[str] = RASTER_FORMATS) -> Iterator[Image.Image]:
    """Open a bounded image, checking its header before any pixel decode.

    The caller owns the yielded image and must not retain it after the context.
    Pillow decompression-bomb warnings become input errors for both header
    parsing and any later load or conversion performed by the caller.
    """
    from PIL import Image

    image_path = Path(path)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = None
        handle = image_path.open("rb")
        try:
            if os.fstat(handle.fileno()).st_size > MAX_IMAGE_BYTES:
                raise ImageInputError(f"Image file exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit: {image_path.name}")
            with os.fdopen(os.dup(handle.fileno()), "rb") as probe_handle:
                with Image.open(probe_handle) as probe:
                    _check_header(probe, allowed_formats, image_path)
                    probe.verify()
            image = Image.open(handle)
            _check_header(image, allowed_formats, image_path)
            yield image
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageInputError(f"Image is rejected as a decompression bomb: {image_path.name}") from exc
        except Image.UnidentifiedImageError as exc:
            raise ImageInputError(f"File is not a readable raster image: {image_path.name}") from exc
        finally:
            if image is not None:
                image.close()
            handle.close()


@contextmanager
def open_raster_bytes(data: bytes, *, name: str = "image", allowed_formats: frozenset[str] = RASTER_FORMATS) -> Iterator[Image.Image]:
    """Validate and open already bounded raster bytes before decoding pixels."""
    from PIL import Image

    if len(data) > MAX_IMAGE_BYTES:
        raise ImageInputError(f"Image file exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit: {name}")
    stream = BytesIO(data)
    image = None
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(BytesIO(data)) as probe:
                _check_header(probe, allowed_formats, Path(name))
                probe.verify()
            image = Image.open(stream)
            _check_header(image, allowed_formats, Path(name))
            yield image
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageInputError(f"Image is rejected as a decompression bomb: {name}") from exc
        except Image.UnidentifiedImageError as exc:
            raise ImageInputError(f"File is not a readable raster image: {name}") from exc
        finally:
            if image is not None:
                image.close()
            stream.close()
