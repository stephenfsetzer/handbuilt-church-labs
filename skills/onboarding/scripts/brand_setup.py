#!/usr/bin/env python3
"""Small, bounded writer and readiness reader for a church brand file."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class BrandSetupError(ValueError):
    """A safe, actionable brand setup error."""


LOGO_FIELDS = {"banner", "mark", "episcopal_shield"}
COLOR_FIELDS = {"ink", "accent", "accent_deep", "paper", "rubric_red"}
LOGO_STATUSES = {"pending", "provided", "none"}
COLOR_STATUSES = {"pending", "confirmed", "neutral"}
NEUTRAL_COLORS = {
    "ink": "#1a1a1a", "accent": "#4a5d7e", "accent_deep": "#2e3a52",
    "paper": "#ffffff", "rubric_red": "#8B3A3A",
}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _root(value: str | Path) -> Path:
    original = Path(value).expanduser()
    if original.is_symlink():
        raise BrandSetupError("Church folder symlinks are not allowed")
    root = original.resolve()
    if not root.is_dir():
        raise BrandSetupError(f"Church folder does not exist: {root}")
    plugin = Path(__file__).resolve().parents[3]
    def inside(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False
    public = any((ancestor / ".codex-plugin" / "plugin.json").is_file() or ((ancestor / ".git").is_dir() and (ancestor / "skills" / "onboarding").is_dir()) for ancestor in (root, *root.parents))
    caches = (Path.home() / ".codex" / "plugins" / "cache", Path.home() / ".claude" / "plugins" / "cache")
    if inside(root, plugin) or public or any(inside(root, cache) for cache in caches):
        raise BrandSetupError("Church data must live in a private folder outside the Labs repository and plugin cache")
    return root


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _brand_path(root: Path) -> Path:
    path = root / "brand.json"
    if path.is_symlink() or not path.is_file():
        raise BrandSetupError("brand.json must be a regular file inside the church folder")
    return path


def _read(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(_brand_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrandSetupError(f"Could not read brand.json: {exc}") from exc
    if not isinstance(value, dict):
        raise BrandSetupError("brand.json must contain an object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _asset(root: Path, raw: Any, field: str, *, require_valid: bool = True) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BrandSetupError(f"{field} must be a local logo path")
    candidate = Path(raw.strip())
    if candidate.is_absolute() or ".." in candidate.parts or "://" in raw:
        raise BrandSetupError(f"{field} must be a relative local path inside the church folder")
    path = root / candidate
    resolved = path.resolve()
    if not _inside(resolved, root) or path.is_symlink() or not path.is_file():
        raise BrandSetupError(f"{field} must point to a regular file inside the church folder")
    if require_valid:
        try:
            if path.suffix.casefold() == ".svg":
                text = path.read_text(encoding="utf-8")
                lowered = text.casefold()
                if "<!doctype" in lowered or "<!entity" in lowered or "xlink:href=\"http" in lowered or "href=\"http" in lowered:
                    raise ValueError("unsafe SVG resources")
                element = ET.fromstring(text)
                for node in element.iter():
                    for key, value in node.attrib.items():
                        if key.rsplit("}", 1)[-1].casefold() in {"href", "src"} and not value.startswith("#"):
                            raise ValueError("SVG references must stay within the image")
                    if "url(" in " ".join(node.attrib.values()).casefold() or "url(" in (node.text or "").casefold():
                        raise ValueError("Prepare a self-contained SVG without CSS resource URLs")
                if element.tag.rsplit("}", 1)[-1].casefold() != "svg":
                    raise ValueError("not an SVG")
            else:
                from PIL import Image
                with Image.open(path) as image:
                    image.verify()
        except Exception as exc:
            raise BrandSetupError(f"{field} is not a readable image: {raw}") from exc
    return raw.strip()


def _validate_effective(root: Path, value: dict[str, Any]) -> None:
    logo = value.get("logo", {})
    if not isinstance(logo, dict):
        raise BrandSetupError("brand.logo must be an object")
    for field, raw in logo.items():
        if field not in LOGO_FIELDS:
            raise BrandSetupError(f"brand.logo contains an unknown field: {field}")
        if not isinstance(raw, str):
            raise BrandSetupError(f"brand.logo.{field} must be a local logo path or blank")
        if raw.strip():
            _asset(root, raw, f"brand.logo.{field}")
    colors = value.get("colors", {})
    if not isinstance(colors, dict):
        raise BrandSetupError("brand.colors must be an object")
    for field, raw in colors.items():
        if field in COLOR_FIELDS and raw not in (None, "") and (not isinstance(raw, str) or not HEX.fullmatch(raw)):
            raise BrandSetupError(f"brand.colors.{field} must be a six-digit hex color")


def _validate_patch(root: Path, patch: Any, current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict) or not patch:
        raise BrandSetupError("A brand update must be a non-empty object")
    allowed = {"logo_status", "colors_status", "logo", "colors"}
    unknown = set(patch) - allowed
    if unknown:
        raise BrandSetupError(f"Unsupported brand setting: {sorted(unknown)[0]}")
    result = copy.deepcopy(current)
    for key in ("logo_status", "colors_status"):
        if key in patch:
            choices = LOGO_STATUSES if key == "logo_status" else COLOR_STATUSES
            if not isinstance(patch[key], str) or patch[key] not in choices:
                raise BrandSetupError(f"{key} must be one of: {', '.join(sorted(choices))}")
            result[key] = patch[key]
    for key, fields in (("logo", LOGO_FIELDS), ("colors", COLOR_FIELDS)):
        if key in patch:
            value = patch[key]
            if not isinstance(value, dict) or set(value) - fields:
                raise BrandSetupError(f"brand.{key} contains an unknown field")
            target = result.setdefault(key, {})
            if not isinstance(target, dict):
                raise BrandSetupError(f"brand.{key} must be an object")
            target.update(copy.deepcopy(value))
    # A supplied, validated local asset is an obvious choice. Palette values
    # still require an explicit confirmed or neutral choice.
    if "logo_status" not in patch and "logo" in patch:
        if any(isinstance(v, str) and v.strip() for v in (result.get("logo") or {}).values()):
            result["logo_status"] = "provided"
    if result.get("logo_status") == "provided":
        logo = result.get("logo")
        paths = [v for v in (logo or {}).values() if isinstance(v, str) and v.strip()]
        if not paths:
            raise BrandSetupError("logo_status=provided requires a local logo path")
        for field, raw in (logo or {}).items():
            if isinstance(raw, str) and raw.strip():
                _asset(root, raw, f"brand.logo.{field}")
    elif result.get("logo_status") == "none":
        if any(isinstance(v, str) and v.strip() for v in (result.get("logo") or {}).values()):
            raise BrandSetupError("logo_status=none cannot keep a logo path")
    if isinstance(result.get("colors_status"), str) and result.get("colors_status") in {"confirmed", "neutral"}:
        colors = result.get("colors")
        if result.get("colors_status") == "neutral":
            colors = result.setdefault("colors", {})
            for field, fallback in NEUTRAL_COLORS.items():
                colors.setdefault(field, fallback)
        if not isinstance(colors, dict) or any(not isinstance(colors.get(k), str) or not HEX.fullmatch(colors[k]) for k in COLOR_FIELDS):
            raise BrandSetupError(f"colors_status={result['colors_status']} requires all five valid hex colors")
    _validate_effective(root, result)
    return result


def _logo_state(root: Path, brand: dict[str, Any]) -> dict[str, Any]:
    explicit = brand.get("logo_status")
    logo = brand.get("logo") if isinstance(brand.get("logo"), dict) else {}
    paths = [(k, v) for k, v in logo.items() if k in LOGO_FIELDS and isinstance(v, str) and v.strip()]
    if explicit not in (None, *LOGO_STATUSES):
        return {"status": "pending", "ready": False, "unresolved": [{"field": "logo_status", "reason": "Choose pending, provided, or none"}]}
    if explicit == "none":
        if any(v not in (None, "") for v in logo.values()):
            return {"status": "none", "ready": False, "unresolved": [{"field": "logo", "reason": "Remove configured logo paths when choosing no logo"}]}
        return {"status": "none", "ready": True, "unresolved": []}
    if explicit == "provided" or (explicit is None and paths):
        errors = []
        for field, raw in paths:
            try:
                _asset(root, raw, f"brand.logo.{field}")
            except BrandSetupError as exc:
                errors.append({"field": f"logo.{field}", "reason": str(exc)})
        if not paths:
            errors.append({"field": "logo", "reason": "Supply a local logo or explicitly choose no logo"})
        return {"status": "provided", "ready": not errors, "unresolved": errors}
    return {"status": "pending", "ready": False, "unresolved": [{"field": "logo_status", "reason": "Supply a local logo or explicitly choose no logo"}]}


def _colors_state(brand: dict[str, Any]) -> dict[str, Any]:
    explicit = brand.get("colors_status")
    colors = brand.get("colors") if isinstance(brand.get("colors"), dict) else {}
    if explicit not in (None, *COLOR_STATUSES):
        return {"status": "pending", "ready": False, "unresolved": [{"field": "colors_status", "reason": "Choose pending, confirmed, or neutral"}]}
    if explicit in {"confirmed", "neutral"}:
        errors = [{"field": f"colors.{k}", "reason": "Choose a valid six-digit hex color"} for k in COLOR_FIELDS if not isinstance(colors.get(k), str) or not HEX.fullmatch(colors[k])]
        return {"status": explicit, "ready": not errors, "unresolved": errors}
    return {"status": "pending", "ready": False, "unresolved": [{"field": "colors_status", "reason": "Confirm the palette or choose neutral defaults"}]}


def status(church_folder: str | Path) -> dict[str, Any]:
    root = _root(church_folder)
    brand = _read(root)
    logo = _logo_state(root, brand)
    colors = _colors_state(brand)
    unresolved = logo["unresolved"] + colors["unresolved"]
    return {"status": "ok", "church_folder": str(root), "ready": logo["ready"] and colors["ready"], "logo": logo, "colors": colors, "unresolved": unresolved, "next_action": "Brand choices are ready" if not unresolved else unresolved[0]["reason"]}


def update(church_folder: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    root = _root(church_folder)
    path = _brand_path(root)
    current = _read(root)
    effective = _validate_patch(root, patch, current)
    _write(path, effective)
    return {"status": "updated", "changed": sorted(patch), "readiness": status(root)}


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Inspect or update private church brand choices")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "update"):
        item = sub.add_parser(command)
        item.add_argument("--church-folder", required=True)
        if command == "update":
            item.add_argument("--patch-file", required=True)
    args = parser.parse_args()
    try:
        result = status(args.church_folder) if args.command == "status" else update(args.church_folder, json.loads(Path(args.patch_file).read_text(encoding="utf-8")))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BrandSetupError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
