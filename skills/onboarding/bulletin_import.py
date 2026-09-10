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
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader


class BulletinImportError(ValueError):
    """A safe, actionable bulletin-import error."""


IMPORT_ROOT = "onboarding/imports"
_IMPORT_ID_RE = re.compile(r"^[0-9a-f]{16}$")


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise BulletinImportError(
            f"{name} is not on PATH. Run the runtime doctor's native install plan, then retry the import."
        )
    return found


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode != 0:
        raise BulletinImportError(f"{Path(args[0]).name} failed: {completed.stderr.strip() or completed.stdout.strip()}")


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


def _extract_page_assets(page: Any, page_number: int, assets_dir: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for asset_index, image_file in enumerate(page.images, start=1):
        asset_name = f"page-{page_number:04d}-image-{asset_index:02d}.png"
        asset_path = assets_dir / asset_name
        try:
            raw = image_file.indirect_reference.get_object() if image_file.indirect_reference else {}
            pil_image, has_alpha, alpha_expected = _ensure_alpha(image_file.image, raw)
            pil_image.save(asset_path, format="PNG")
        except Exception as exc:  # pypdf can fail on unusual embedded image encodings
            assets.append({
                "asset_path": asset_name,
                "error": f"Could not extract this embedded image: {exc}",
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
        if _hash_file(snapshot_path) != source_sha256:
            return None
    except OSError:
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
    root = _church_root(church_folder)
    source = _owned_source(source_pdf)
    data = source.read_bytes()
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
    reader = PdfReader(snapshot_path)
    pdf_pages = reader.pages
    page_count = len(pdf_pages)

    pages: list[dict[str, Any]] = []
    for page_number, pdf_page in enumerate(pdf_pages, start=1):
        render_name = f"page-{page_number:04d}.png"
        render_prefix = pages_dir / f"page-{page_number:04d}"
        _run([pdftoppm, "-png", "-r", str(dpi), "-f", str(page_number), "-l", str(page_number),
              "-singlefile", str(snapshot_path), str(render_prefix)])
        rendered = render_prefix.with_suffix(".png")
        if not rendered.is_file():
            raise BulletinImportError(f"Could not render page {page_number} of the supplied bulletin")

        text_name = f"page-{page_number:04d}.txt"
        text_path = text_dir / text_name
        _run([pdftotext, "-f", str(page_number), "-l", str(page_number), str(snapshot_path), str(text_path)])
        text_value = text_path.read_text(encoding="utf-8", errors="replace") if text_path.is_file() else ""

        assets = _extract_page_assets(pdf_page, page_number, assets_dir)

        pages.append({
            "page": page_number,
            "render_path": f"{IMPORT_ROOT}/{import_id}/pages/{render_name}",
            "text_path": f"{IMPORT_ROOT}/{import_id}/text/{text_name}",
            "text_sha256": _hash_bytes(text_value.encode("utf-8")),
            "text_length": len(text_value.strip()),
            "images": [
                {**asset, "asset_path": f"{IMPORT_ROOT}/{import_id}/assets/{asset['asset_path']}"}
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
