"""Snapshot a supplied bulletin PDF and extract page, text, and artwork evidence.

This module turns one pastor-supplied PDF into private, inspectable evidence:
a retained source snapshot, per-page rendered images, per-page selectable
text, and any embedded artwork with its transparency preserved. It never
decides what that evidence means. Mapping a source section to a church
setting, a private text file, or a private asset is a separate, explicit step
recorded through :mod:`skills.bulletin.source_inventory`.

A page with no selectable text is still saved with its rendered image and any
extracted artwork. Absence of selectable text never means the page is blank;
a scanned or image-set music page commonly has none.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream


class BulletinImportError(ValueError):
    """A safe, actionable bulletin-import error."""


IMPORT_ROOT = "onboarding/imports"
_IMPORT_ID_RE = re.compile(r"^[0-9a-f]{16}$")
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PDF_PAGES = 100
MIN_RENDER_DPI = 72
MAX_RENDER_DPI = 300
MAX_PAGE_RENDER_PIXELS = 50_000_000
MAX_TOTAL_RENDER_PIXELS = 100_000_000
MAX_RENDER_OUTPUT_BYTES = 400 * 1024 * 1024
MAX_TEXT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_TEXT_PAGE_BYTES = 1024 * 1024
MAX_IMAGES_PER_PAGE = 100
MAX_IMAGES_PER_PDF = 1000
MAX_XOBJECTS_PER_PAGE = 500
MAX_FORM_DEPTH = 32
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_OUTPUT_BYTES = 256 * 1024 * 1024
PDF_PARSE_TIMEOUT_SECONDS = 30
POPPLER_TIMEOUT_SECONDS = 30
MAX_TOOL_DIAGNOSTIC_BYTES = 4096


def _church_root(church_folder: str | Path) -> Path:
    root = Path(church_folder).expanduser().resolve()
    if not all((root / name).is_file() for name in ("church.yaml", "brand.json")) or any(
        (parent / ".codex-plugin" / "plugin.json").is_file() for parent in (root, *root.parents)
    ):
        raise BulletinImportError("Use an initialized private church folder outside the plugin")
    return root


def _owned_source(raw: str | Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_symlink():
        raise BulletinImportError("The supplied bulletin must be a regular file, not a symlink")
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise BulletinImportError(f"Supplied bulletin not found: {resolved}")
    return resolved


def _valid_import_id(import_id: str) -> str:
    if not isinstance(import_id, str) or not _IMPORT_ID_RE.match(import_id):
        raise BulletinImportError("import_id must be the 16-character import identifier from an import result")
    return import_id


def _confined(root: Path, *parts: str) -> Path:
    """Build root/parts, rejecting any existing symlink at or above the target.

    Every import write goes through this so a pre-existing symlink placed at
    ``onboarding``, ``onboarding/imports``, or one import's own folder cannot
    redirect a write outside the private church folder. Each ``part`` is
    split on ``/`` and checked segment by segment -- checking only after each
    whole ``part`` is joined would miss a symlink planted at an intermediate
    segment inside a single caller-supplied part like ``"onboarding/imports"``.
    """
    current = root
    for part in parts:
        for segment in Path(part).parts:
            current = current / segment
            if current.is_symlink():
                raise BulletinImportError(f"{current} must not be a symlink inside the church folder")
    if current.exists():
        resolved = current.resolve()
        if not resolved.is_relative_to(root):
            raise BulletinImportError("This import path would escape the private church folder")
    return current


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_file_bounded(path)


def _hash_file_bounded(path: Path, max_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        if max_bytes is not None and os.fstat(handle.fileno()).st_size > max_bytes:
            raise BulletinImportError("The cached bulletin snapshot exceeds the PDF import limit")
        while chunk := handle.read(1024 * 1024):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise BulletinImportError("The cached bulletin snapshot exceeds the PDF import limit")
            digest.update(chunk)
    return digest.hexdigest()


def _native_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise BulletinImportError(
            f"{name} is not on PATH. Run the runtime doctor's native install plan, then retry the import."
        )
    return found


def _run(args: list[str], *, timeout: int = POPPLER_TIMEOUT_SECONDS) -> None:
    try:
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:
        raise BulletinImportError(f"Could not start {Path(args[0]).name}: {exc}") from exc
    tail = bytearray()

    def collect_diagnostic() -> None:
        assert process.stderr is not None
        while True:
            chunk = process.stderr.read(8192)
            if not chunk:
                return
            tail.extend(chunk)
            if len(tail) > MAX_TOOL_DIAGNOSTIC_BYTES:
                del tail[:-MAX_TOOL_DIAGNOSTIC_BYTES]

    reader = threading.Thread(target=collect_diagnostic, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        reader.join()
        if process.stderr is not None:
            process.stderr.close()
        raise BulletinImportError(f"{Path(args[0]).name} exceeded its {timeout}-second time limit") from exc
    reader.join()
    if process.stderr is not None:
        process.stderr.close()
    if returncode != 0:
        message = bytes(tail).decode("utf-8", errors="replace").strip()
        if len(tail) >= MAX_TOOL_DIAGNOSTIC_BYTES:
            message += " (diagnostic truncated)"
        raise BulletinImportError(f"{Path(args[0]).name} failed: {message or 'no diagnostic available'}")


def _run_text(args: list[str], *, timeout: int, max_bytes: int) -> bytes:
    """Capture stdout in memory with a hard byte cap and a wall-clock limit."""
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise BulletinImportError(f"Could not start {Path(args[0]).name}: {exc}") from exc
    output = bytearray()
    exceeded = threading.Event()

    def collect_output() -> None:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                return
            remaining = max_bytes - len(output)
            if len(chunk) > remaining:
                if remaining > 0:
                    output.extend(chunk[:remaining])
                exceeded.set()
                process.kill()
            elif not exceeded.is_set():
                output.extend(chunk)

    reader = threading.Thread(target=collect_output, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        reader.join()
        if process.stdout is not None:
            process.stdout.close()
        raise BulletinImportError(f"{Path(args[0]).name} exceeded its {timeout}-second time limit") from exc
    reader.join()
    if process.stdout is not None:
        process.stdout.close()
    if exceeded.is_set():
        raise BulletinImportError(f"{Path(args[0]).name} output exceeded its size limit")
    if returncode != 0:
        raise BulletinImportError(f"{Path(args[0]).name} failed while extracting page text")
    return bytes(output)


def _read_source_pdf(source: Path) -> bytes:
    if source.stat().st_size > MAX_PDF_BYTES:
        raise BulletinImportError(f"The supplied bulletin is larger than the {MAX_PDF_BYTES // (1024 * 1024)} MiB import limit")
    with source.open("rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        if size > MAX_PDF_BYTES:
            raise BulletinImportError(f"The supplied bulletin is larger than the {MAX_PDF_BYTES // (1024 * 1024)} MiB import limit")
        data = handle.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise BulletinImportError(f"The supplied bulletin is larger than the {MAX_PDF_BYTES // (1024 * 1024)} MiB import limit")
    return data


def _render_geometry(width_points: float, height_points: float, dpi: int) -> tuple[int, int, int]:
    _validate_render_dpi(dpi)
    if not width_points or not height_points:
        raise BulletinImportError("The supplied bulletin has a page with invalid dimensions")
    width = round(abs(float(width_points)) * dpi / 72)
    height = round(abs(float(height_points)) * dpi / 72)
    pixels = width * height
    if width <= 0 or height <= 0 or width > 20_000 or height > 20_000 or pixels > MAX_PAGE_RENDER_PIXELS:
        raise BulletinImportError("The supplied bulletin has a page that is too large to render safely")
    return width, height, pixels


def _validate_render_dpi(dpi: int) -> None:
    if not isinstance(dpi, int) or isinstance(dpi, bool) or not MIN_RENDER_DPI <= dpi <= MAX_RENDER_DPI:
        raise BulletinImportError(f"Render resolution must be between {MIN_RENDER_DPI} and {MAX_RENDER_DPI} DPI")


def _add_bounded_output(current: int, added: int, limit: int, label: str) -> int:
    total = current + added
    if total > limit:
        raise BulletinImportError(f"{label} exceeded its total output limit")
    return total


def _validate_image_dimensions(width: int, height: int) -> None:
    if (width <= 0 or height <= 0 or width > 20_000 or height > 20_000
            or width * height > MAX_IMAGE_PIXELS):
        raise ValueError("embedded image has invalid or oversized dimensions")


def _resolved_pdf_object(value: Any) -> Any:
    if isinstance(value, dict) or isinstance(value, (list, tuple)):
        return value
    get_object = getattr(value, "get_object", None)
    return get_object() if callable(get_object) else value


def _pdf_object_identity(original: Any, resolved: Any) -> Any:
    reference = getattr(original, "indirect_reference", None) or getattr(resolved, "indirect_reference", None)
    if reference is not None:
        return ("ref", getattr(reference, "idnum", None), getattr(reference, "generation", None))
    return ("object", id(resolved))


def _raw_image_dimensions(image: Any) -> tuple[int, int]:
    try:
        width, height = image["/Width"], image["/Height"]
    except (KeyError, TypeError) as exc:
        raise BulletinImportError("An embedded image is missing its dimensions") from exc
    if (not isinstance(width, int) or isinstance(width, bool)
            or not isinstance(height, int) or isinstance(height, bool)):
        raise BulletinImportError("An embedded image has invalid dimensions")
    try:
        _validate_image_dimensions(width, height)
    except ValueError as exc:
        raise BulletinImportError(str(exc)) from exc
    return width, height


def _preflight_content_stream(content: Any, reader: Any, counts: dict[str, int]) -> None:
    if content is None:
        return
    try:
        stream = content if hasattr(content, "operations") else ContentStream(content, reader)
        operations = stream.operations
    except Exception as exc:
        raise BulletinImportError("Could not safely inspect a PDF content stream") from exc
    for operands, operator in operations:
        if operator != b"INLINE IMAGE":
            continue
        counts["inline"] += 1
        counts["images"] += 1
        if counts["inline"] > MAX_IMAGES_PER_PAGE or counts["images"] > MAX_IMAGES_PER_PAGE:
            raise BulletinImportError("A page has too many embedded images to import safely")
        settings = operands.get("settings", {})
        normalized = {
            "/Width": settings.get("/Width", settings.get("/W")),
            "/Height": settings.get("/Height", settings.get("/H")),
        }
        _raw_image_dimensions(normalized)


def _preflight_image_masks(image: Any, counts: dict[str, int], active: set[Any]) -> None:
    for key in ("/SMask", "/Mask"):
        raw_mask = image.get(key)
        if raw_mask is None:
            continue
        mask = _resolved_pdf_object(raw_mask)
        if not isinstance(mask, dict) or "/Width" not in mask or "/Height" not in mask:
            continue
        marker = _pdf_object_identity(raw_mask, mask)
        if marker in active:
            continue
        active.add(marker)
        counts["images"] += 1
        if counts["images"] > MAX_IMAGES_PER_PAGE:
            raise BulletinImportError("A page has too many embedded images to import safely")
        _raw_image_dimensions(mask)
        _preflight_image_masks(mask, counts, active)
        active.remove(marker)


def _preflight_resources(resources: Any, reader: Any, counts: dict[str, int],
                         active: set[Any], depth: int = 0) -> None:
    if depth > MAX_FORM_DEPTH:
        raise BulletinImportError("The supplied bulletin has too many nested XObject resources")
    resource_dict = _resolved_pdf_object(resources)
    if not isinstance(resource_dict, dict):
        return
    xobjects = _resolved_pdf_object(resource_dict.get("/XObject"))
    if not isinstance(xobjects, dict):
        return
    for raw_xobject in xobjects.values():
        counts["xobjects"] += 1
        if counts["xobjects"] > MAX_XOBJECTS_PER_PAGE:
            raise BulletinImportError("A page has too many PDF image and form resources")
        xobject = _resolved_pdf_object(raw_xobject)
        if not isinstance(xobject, dict):
            continue
        marker = _pdf_object_identity(raw_xobject, xobject)
        subtype = str(xobject.get("/Subtype", ""))
        if subtype == "/Image":
            counts["images"] += 1
            if counts["images"] > MAX_IMAGES_PER_PAGE:
                raise BulletinImportError("A page has too many embedded images to import safely")
            _raw_image_dimensions(xobject)
            _preflight_image_masks(xobject, counts, active | {marker})
            continue
        if marker in active:
            continue
        if subtype == "/Form":
            _preflight_content_stream(xobject, reader, counts)
        if "/Resources" in xobject:
            active.add(marker)
            try:
                _preflight_resources(xobject.get("/Resources"), reader, counts, active, depth + 1)
            finally:
                active.remove(marker)


def _preflight_page_images(page: Any) -> dict[str, int]:
    counts = {"images": 0, "inline": 0, "xobjects": 0}
    try:
        _preflight_content_stream(page.get_contents(), page.pdf, counts)
        _preflight_resources(page.get_inherited("/Resources", {}), page.pdf, counts, set())
    except BulletinImportError:
        raise
    except Exception as exc:
        raise BulletinImportError("Could not safely inspect embedded images on this page") from exc
    return counts


def _inspect_pdf(source: Path, assets_dir: Path, dpi: int) -> dict[str, Any]:
    """Parse and extract PDF objects in a killable worker process."""
    reader = PdfReader(source)
    pdf_pages = reader.pages
    page_count = len(pdf_pages)
    if page_count < 1 or page_count > MAX_PDF_PAGES:
        raise BulletinImportError(f"A bulletin must contain between 1 and {MAX_PDF_PAGES} pages")
    page_geometry = []
    total_pixels = 0
    for page in pdf_pages:
        box = page.mediabox
        width, height, pixels = _render_geometry(box.width, box.height, dpi)
        total_pixels += pixels
        if total_pixels > MAX_TOTAL_RENDER_PIXELS or total_pixels * 4 > MAX_RENDER_OUTPUT_BYTES:
            raise BulletinImportError("The supplied bulletin would exceed the total page-rendering limit")
        page_geometry.append({"width": width, "height": height, "pixels": pixels})
    page_assets = []
    total_image_bytes = 0
    total_image_count = 0
    preflight_image_count = 0
    estimated_image_output = [0]
    for page_number, page in enumerate(pdf_pages, start=1):
        try:
            preflight = _preflight_page_images(page)
            preflight_image_count += preflight["images"]
            if preflight_image_count > MAX_IMAGES_PER_PDF:
                raise BulletinImportError(f"A bulletin may contain no more than {MAX_IMAGES_PER_PDF} embedded images")
        except BulletinImportError as exc:
            # Poppler must not decode artwork that failed the same preflight.
            page_geometry[page_number - 1]["image_preflight_error"] = str(exc)[:MAX_TOOL_DIAGNOSTIC_BYTES]
            page_assets.append([{"error": f"Could not safely extract page images: {str(exc)[:MAX_TOOL_DIAGNOSTIC_BYTES]}"}])
            continue
        images = _extract_page_assets(page, page_number, assets_dir, estimated_image_output)
        total_image_count += len(images)
        if total_image_count > MAX_IMAGES_PER_PDF:
            raise BulletinImportError(f"A bulletin may contain no more than {MAX_IMAGES_PER_PDF} embedded images")
        for image in images:
            if "sha256" not in image:
                continue
            image_path = assets_dir / Path(image["asset_path"]).name
            total_image_bytes = _add_bounded_output(
                total_image_bytes,
                image_path.stat().st_size,
                MAX_IMAGE_OUTPUT_BYTES,
                "Extracted images",
            )
        page_assets.append(images)
    return {"page_count": page_count, "geometry": page_geometry, "images": page_assets}


def _pdf_worker(source: str, assets_dir: str, dpi: int, result_path: str) -> None:
    try:
        try:
            import resource
            cpu_soft, cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
            cpu_limit = min(25, cpu_hard) if cpu_hard != resource.RLIM_INFINITY else 25
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
            if hasattr(resource, "RLIMIT_AS"):
                memory_soft, memory_hard = resource.getrlimit(resource.RLIMIT_AS)
                memory_limit = min(2 * 1024**3, memory_hard) if memory_hard != resource.RLIM_INFINITY else 2 * 1024**3
                resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_hard))
        except (ImportError, OSError, ValueError):
            # The parent process still enforces a wall-clock timeout on platforms
            # without POSIX resource limits.
            pass
        result = _inspect_pdf(Path(source), Path(assets_dir), dpi)
        Path(result_path).write_text(json.dumps({"ok": True, "result": result}), encoding="utf-8")
    except BaseException as exc:
        Path(result_path).write_text(json.dumps({"ok": False, "error": str(exc)[:MAX_TOOL_DIAGNOSTIC_BYTES]}), encoding="utf-8")


def _bounded_pdf_inspection(source: Path, assets_dir: Path, dpi: int, result_path: Path) -> dict[str, Any]:
    """Run pypdf parsing in a separate process so a stuck parser can be stopped."""
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_pdf_worker, args=(str(source), str(assets_dir), dpi, str(result_path)))
    try:
        process.start()
    except (OSError, RuntimeError) as exc:
        raise BulletinImportError("Could not start the isolated PDF inspection process") from exc
    process.join(PDF_PARSE_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join()
        raise BulletinImportError(f"The supplied bulletin took longer than {PDF_PARSE_TIMEOUT_SECONDS} seconds to inspect")
    if process.exitcode != 0 or not result_path.is_file():
        raise BulletinImportError("Could not safely inspect the supplied bulletin")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BulletinImportError("Could not safely inspect the supplied bulletin") from exc
    if not result.get("ok"):
        raise BulletinImportError(result.get("error") or "Could not safely inspect the supplied bulletin")
    return result["result"]


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _stencil_to_rgba(pil_image: Image.Image, ink: tuple[int, int, int] = (0, 0, 0)) -> Image.Image:
    """Composite a decoded PDF stencil mask into a real alpha channel.

    pypdf decodes a ``/ImageMask`` XObject's samples (already honoring its
    ``/Decode`` array) into a plain bitonal image, without applying PDF's
    stencil paint convention (sample 0 = paint, 1 = transparent) or the
    current fill color. Reproducing that here is what makes an inverted
    ``/Decode`` array (light-on-dark scanned artwork, common in stencil logos)
    come out with the correct shape instead of an inverted silhouette. The
    original fill color is not recoverable from the image object alone, so
    painted pixels use a neutral ink color and only the shape and
    transparency are guaranteed faithful.
    """
    gray = pil_image.convert("L")
    alpha = gray.point(lambda sample: 255 - sample)
    rgba = Image.new("RGBA", pil_image.size, (*ink, 0))
    rgba.putalpha(alpha)
    return rgba


def _ensure_alpha(pil_image: Image.Image, raw_xobject: dict[str, Any]) -> tuple[Image.Image, bool, bool]:
    """Never silently drop a soft mask, explicit mask, or stencil mask.

    Returns (image, has_alpha, alpha_expected). ``alpha_expected`` is true
    when the original PDF image object carries a soft mask, an explicit
    mask, or is itself a stencil (``/ImageMask``); when that is true but the
    decoded image has no alpha channel, the caller records a warning instead
    of a silent flattened image.
    """
    if raw_xobject.get("/ImageMask"):
        return _stencil_to_rgba(pil_image), True, True
    alpha_expected = "/SMask" in raw_xobject or "/Mask" in raw_xobject
    has_alpha = pil_image.mode in ("RGBA", "LA") or (pil_image.mode == "P" and "transparency" in pil_image.info)
    if has_alpha and pil_image.mode not in ("RGBA", "LA"):
        pil_image = pil_image.convert("RGBA")
    return pil_image, has_alpha, alpha_expected


def _extract_page_assets(
    page: Any, page_number: int, assets_dir: Path, estimated_output: list[int] | None = None,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    try:
        image_count = len(page.images)
    except Exception as exc:  # pypdf can fail while enumerating a page's XObjects
        return [{"error": f"Could not enumerate embedded images on this page: {str(exc)[:MAX_TOOL_DIAGNOSTIC_BYTES]}"}]
    if image_count > MAX_IMAGES_PER_PAGE:
        raise BulletinImportError(f"Page {page_number} has too many embedded images to import safely")
    for asset_index in range(1, image_count + 1):
        asset_name = f"page-{page_number:04d}-image-{asset_index:02d}.png"
        asset_path = assets_dir / asset_name
        try:
            # Indexing (rather than iterating) page.images decodes only this
            # one image, so a decode failure here -- such as pypdf's
            # LimitReachedError on an oversized embedded image -- cannot
            # abort the images still to come. Iterating the sequence
            # directly would decode the next image before this loop body,
            # and its try/except, ever runs.
            image_file = page.images[asset_index - 1]
            raw = image_file.indirect_reference.get_object() if image_file.indirect_reference else {}
            # Inline images have no indirect reference. Their raw dimensions
            # were checked during page preflight, before pypdf decoded them.
            if image_file.indirect_reference:
                try:
                    _raw_image_dimensions(raw)
                except BulletinImportError as error:
                    raise ValueError(str(error)) from error
            pil_image, has_alpha, alpha_expected = _ensure_alpha(image_file.image, raw)
            _validate_image_dimensions(pil_image.width, pil_image.height)
            if estimated_output is not None:
                estimated_output[0] = _add_bounded_output(
                    estimated_output[0], pil_image.width * pil_image.height * 4,
                    MAX_IMAGE_OUTPUT_BYTES, "Extracted images",
                )
            pil_image.save(asset_path, format="PNG")
        except BulletinImportError:
            raise
        except Exception as exc:  # pypdf can fail on unusual embedded image encodings
            assets.append({
                "asset_path": asset_name,
                "error": f"Could not extract this embedded image: {str(exc)[:MAX_TOOL_DIAGNOSTIC_BYTES]}",
            })
            continue
        assets.append({
            "asset_path": asset_name,
            "sha256": _hash_file(asset_path),
            "width": pil_image.width,
            "height": pil_image.height,
            "mode": pil_image.mode,
            "has_alpha": has_alpha,
            "alpha_expected": alpha_expected,
            "alpha_composite_warning": alpha_expected and not has_alpha,
            "stencil": bool(raw.get("/ImageMask")),
        })
    return assets


def _safe_relative(root: Path, value: Any) -> Path | None:
    """Resolve a path recorded in a (possibly tampered) JSON file, refusing
    an absolute path or one that would escape the church folder rather than
    trusting it -- ``root / value`` silently discards ``root`` when ``value``
    is itself absolute, so that join is never used directly on stored data."""
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        return _confined(root, *candidate.parts)
    except BulletinImportError:
        return None


def _repairable_existing_manifest(
    root: Path, manifest_path: Path, snapshot_path: Path, source_sha256: str,
) -> dict[str, Any] | None:
    """Return the cached manifest only if it and its evidence are intact.

    A hash match in manifest.json is not enough to trust the cache: the
    snapshot or a page's rendered/text evidence could have been deleted,
    corrupted, or the manifest itself tampered with since. Any of that sends
    the caller back to rebuild rather than trusting a damaged cache.
    """
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(existing, dict) or existing.get("source", {}).get("sha256") != source_sha256:
        return None
    if not snapshot_path.is_file():
        return None
    try:
        if _hash_file_bounded(snapshot_path, MAX_PDF_BYTES) != source_sha256:
            return None
    except (OSError, BulletinImportError):
        return None
    try:
        pages = existing.get("pages", [])
        if not isinstance(pages, list):
            return None
        for page in pages:
            if not isinstance(page, dict):
                return None
            render_path = _safe_relative(root, page.get("render_path"))
            text_path = _safe_relative(root, page.get("text_path"))
            if render_path is None or text_path is None or not render_path.is_file() or not text_path.is_file():
                return None
            for image in page.get("images", []):
                if not isinstance(image, dict):
                    return None
                if "sha256" in image:
                    asset_path = _safe_relative(root, image.get("asset_path"))
                    if asset_path is None or not asset_path.is_file():
                        return None
    except (TypeError, AttributeError):
        return None
    return existing


def import_bulletin(
    church_folder: str | Path,
    source_pdf: str | Path,
    *,
    original_filename: str | None = None,
    dpi: int = 150,
    imported_on: str | None = None,
) -> dict[str, Any]:
    """Snapshot ``source_pdf`` into the church folder and extract page evidence.

    Content-addressed and idempotent: re-importing identical bytes returns the
    existing manifest instead of writing a duplicate snapshot.
    """
    _validate_render_dpi(dpi)
    root = _church_root(church_folder)
    source = _owned_source(source_pdf)
    data = _read_source_pdf(source)
    if not data.startswith(b"%PDF-"):
        raise BulletinImportError("Supplied file is not a PDF")
    source_sha256 = _hash_bytes(data)
    import_id = source_sha256[:16]
    manifest_path = _confined(root, IMPORT_ROOT, import_id, "manifest.json")
    snapshot_path = _confined(root, IMPORT_ROOT, import_id, "source.pdf")
    if manifest_path.is_file():
        existing = _repairable_existing_manifest(root, manifest_path, snapshot_path, source_sha256)
        if existing is not None:
            return existing
        # The manifest claimed a match but the snapshot or its evidence is
        # missing or damaged. Fall through and rebuild deterministically
        # rather than trusting a cache that does not match what is on disk.

    pages_dir = _confined(root, IMPORT_ROOT, import_id, "pages")
    text_dir = _confined(root, IMPORT_ROOT, import_id, "text")
    assets_dir = _confined(root, IMPORT_ROOT, import_id, "assets")
    for directory in (pages_dir, text_dir, assets_dir):
        directory.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(data)

    pdftoppm = _native_tool("pdftoppm")
    pdftotext = _native_tool("pdftotext")
    with tempfile.TemporaryDirectory(prefix=".bulletin-parse-", dir=str(root)) as worker_dir:
        worker_assets = Path(worker_dir) / "assets"
        worker_assets.mkdir()
        inspection_path = Path(worker_dir) / "inspection.json"
        inspection = _bounded_pdf_inspection(snapshot_path, worker_assets, dpi, inspection_path)
        for page_number, geometry in enumerate(inspection["geometry"], start=1):
            if geometry.get("image_preflight_error"):
                raise BulletinImportError(
                    f"Page {page_number} has artwork that cannot be processed safely: "
                    + geometry["image_preflight_error"]
                )
        for staged_asset in worker_assets.iterdir():
            os.replace(staged_asset, assets_dir / staged_asset.name)
    page_count = inspection["page_count"]
    total_render_bytes = 0
    total_text_bytes = 0

    pages: list[dict[str, Any]] = []
    for page_number, (geometry, assets) in enumerate(zip(inspection["geometry"], inspection["images"]), start=1):
        render_name = f"page-{page_number:04d}.png"
        render_prefix = pages_dir / f"page-{page_number:04d}"
        _run([pdftoppm, "-png", "-scale-to-x", str(geometry["width"]), "-scale-to-y", str(geometry["height"]),
              "-f", str(page_number), "-l", str(page_number),
              "-singlefile", str(snapshot_path), str(render_prefix)])
        rendered = render_prefix.with_suffix(".png")
        if not rendered.is_file():
            raise BulletinImportError(f"Could not render page {page_number} of the supplied bulletin")
        total_render_bytes += rendered.stat().st_size
        if total_render_bytes > MAX_RENDER_OUTPUT_BYTES:
            raise BulletinImportError("Rendered bulletin pages exceeded the total output limit")

        text_name = f"page-{page_number:04d}.txt"
        text_path = text_dir / text_name
        text_bytes = _run_text([pdftotext, "-f", str(page_number), "-l", str(page_number),
                                str(snapshot_path), "-"], timeout=POPPLER_TIMEOUT_SECONDS,
                               max_bytes=MAX_TEXT_PAGE_BYTES)
        total_text_bytes = _add_bounded_output(total_text_bytes, len(text_bytes),
                                               MAX_TEXT_OUTPUT_BYTES, "Extracted bulletin text")
        text_path.write_bytes(text_bytes)
        text_value = text_bytes.decode("utf-8", errors="replace")

        pages.append({
            "page": page_number,
            "render_path": f"{IMPORT_ROOT}/{import_id}/pages/{render_name}",
            "text_path": f"{IMPORT_ROOT}/{import_id}/text/{text_name}",
            "text_sha256": _hash_bytes(text_value.encode("utf-8")),
            "text_length": len(text_value.strip()),
            "images": [
                {**asset, "asset_path": f"{IMPORT_ROOT}/{import_id}/assets/{asset['asset_path']}"}
                if "asset_path" in asset else asset
                for asset in assets
            ],
        })

    manifest = {
        "schema_version": 1,
        "import_id": import_id,
        "original_filename": original_filename or source.name,
        "imported_on": imported_on or date.today().isoformat(),
        "source": {
            "path": f"{IMPORT_ROOT}/{import_id}/source.pdf",
            "sha256": source_sha256,
            "page_count": page_count,
        },
        "pages": pages,
    }
    _atomic_write_json(manifest_path, manifest)
    return manifest


def read_manifest(church_folder: str | Path, import_id: str) -> dict[str, Any]:
    root = _church_root(church_folder)
    manifest_path = _confined(root, IMPORT_ROOT, _valid_import_id(import_id), "manifest.json")
    if not manifest_path.is_file():
        raise BulletinImportError(f"No import recorded for {import_id}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def list_imports(church_folder: str | Path) -> list[dict[str, Any]]:
    root = _church_root(church_folder)
    imports_root = root / IMPORT_ROOT
    if not imports_root.is_dir():
        return []
    results = []
    for import_dir in sorted(p for p in imports_root.iterdir() if p.is_dir() and _IMPORT_ID_RE.match(p.name)):
        manifest_path = import_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            results.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return results
