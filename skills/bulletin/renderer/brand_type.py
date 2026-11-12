"""Typefaces from a church's approved brand, ready for a renderer.

An approved brand records its type in brand.json under ``brand_system.type``:
``display`` for headlines, ``text`` for details and labels, and, for a church
that prints liturgy, an optional ``reading`` face for prayers and psalms.
Each role has a descriptive ``family`` label, which may carry settings such
as "Fraunces (tailored: weight 700, ...)", ``files`` relative to the church
folder, and optional ``variation`` axis settings for a variable font, such
as {"opsz": 12, "SOFT": 30}.

Renderers never use the descriptive label as a CSS name. They register the
files under the fixed names below and use those, so the brand's own faces
are embedded in every PDF. The bulletin, the finance report and the brand
guide all read the brand's type through ``brand_faces``.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

DISPLAY = "Brand Display"
TEXT = "Brand Text"
READING = "Brand Reading"
ROLES = {"display": DISPLAY, "text": TEXT, "reading": READING}

# File keys used in brand_system.type.<role>.files, mapped to CSS weight and style.
FACES = {
    "regular": ("400", "normal"),
    "italic": ("400", "italic"),
    "medium": ("500", "normal"),
    "semibold": ("600", "normal"),
    "semibold_italic": ("600", "italic"),
    "bold": ("700", "normal"),
    "bold_italic": ("700", "italic"),
}


def is_variable_font(path: Path) -> bool:
    """True when the font file carries a variation table (an fvar table)."""
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
            if len(header) < 12:
                return False
            num_tables = struct.unpack(">H", header[4:6])[0]
            directory = handle.read(16 * num_tables)
    except OSError:
        return False
    return any(directory[i:i + 4] == b"fvar" for i in range(0, len(directory), 16))


def brand_type(brand: dict[str, Any]) -> dict[str, Any]:
    system = brand.get("brand_system") if isinstance(brand.get("brand_system"), dict) else {}
    found = system.get("type")
    return found if isinstance(found, dict) else {}


def variation_settings(brand: dict[str, Any], role: str) -> str:
    """CSS font-variation-settings for a role, or "normal".

    Renderers put this on the elements that use the face; WeasyPrint does
    not read it from @font-face.
    """
    entry = brand_type(brand).get(role)
    axes = entry.get("variation") if isinstance(entry, dict) else None
    if not isinstance(axes, dict):
        return "normal"
    parts = [f'"{tag}" {value:g}' for tag, value in axes.items()
             if isinstance(tag, str) and len(tag) == 4 and isinstance(value, (int, float))]
    return ", ".join(parts) or "normal"


# The same ceiling the image tools use for one file.
MAX_FONT_BYTES = 16 * 1024 * 1024


def _safe_font(church_root: Path, rel: str, label: str) -> Path | None:
    """One brand font file, or None when it is not there.

    Every renderer embeds these files in a PDF, so a file must be a regular
    file inside the church folder and of a sane size. A link, a path that
    leaves the folder, or an oversized file is refused, not skipped.
    """
    original = church_root / rel
    if original.is_symlink():
        raise ValueError(f"Font file for {label} must be a regular file inside the church folder")
    path = original.resolve()
    if church_root.resolve() not in path.parents:
        raise ValueError(f"Font file for {label} must stay inside the church folder")
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_FONT_BYTES:
        raise ValueError(f"Font file for {label} exceeds the {MAX_FONT_BYTES // (1024 * 1024)} MiB limit")
    return path


def brand_faces(brand: dict[str, Any], church_root: Path) -> tuple[str, dict[str, str]]:
    """Return (@font-face CSS, {role: CSS family}) for the brand's type roles.

    Only roles whose font files exist are returned. A brand with no type, or
    files that are missing, returns empty values and the renderer keeps its
    own faces. A style's one variable font covers its whole weight range, up
    to the lightest static file of the same style, so a static bold (for
    example a tailored headline cut) is used for bold and the variable font
    for everything lighter. Several files of one style keep their own weights.
    """
    css: list[str] = []
    families: dict[str, str] = {}
    for role, family in ROLES.items():
        entry = brand_type(brand).get(role)
        files = entry.get("files") if isinstance(entry, dict) else None
        if not isinstance(files, dict):
            continue
        present = []
        for key, rel in files.items():
            if not isinstance(rel, str) or key not in FACES:
                continue
            path = _safe_font(church_root, rel, f"{role}.{key}")
            if path is not None:
                present.append((key, path, is_variable_font(path)))
        if not present:
            continue
        for key, path, variable in present:
            weight, style = FACES[key]
            same_style = [(FACES[k][0], v) for k, _, v in present if FACES[k][1] == style]
            if variable and sum(1 for _, v in same_style if v) == 1:
                statics = [int(w) for w, v in same_style if not v]
                weight = f"100 {min(statics) - 1}" if statics else "100 900"
            css.append(
                f'@font-face {{ font-family: "{family}"; src: url("{path.as_uri()}"); '
                f"font-weight: {weight}; font-style: {style}; }}"
            )
        families[role] = family
    return "\n".join(css), families
