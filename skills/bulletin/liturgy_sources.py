"""Bind a private worship text to retained source evidence and verification.

This records a source comparison performed by the agent or church. It cannot
prove that an external publisher is authoritative; the workflow must check
that before recording the comparison.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


class LiturgySourceError(ValueError):
    pass


def _church_root(church_folder: str | Path) -> Path:
    root = Path(church_folder).expanduser().resolve()
    if not all((root / name).is_file() for name in ("church.yaml", "brand.json")) or any(
        (parent / ".codex-plugin" / "plugin.json").is_file() for parent in (root, *root.parents)
    ):
        raise LiturgySourceError("Use an initialized private church folder outside the plugin")
    return root


def _owned(root: Path, raw: str | Path) -> Path:
    candidate = Path(raw)
    path = candidate if candidate.is_absolute() else root / candidate
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise LiturgySourceError("Worship text and its source must be regular files inside the church folder")
    return resolved


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_source(church_folder: str | Path, file: str | Path, *, source_file: str | Path,
                  label: str, location: str, verified_on: str, method: str) -> dict:
    """Record a completed comparison, without changing either source file."""
    root = _church_root(church_folder)
    text = _owned(root, file)
    source = _owned(root, source_file)
    if method not in ("public_source", "church_supplied"):
        raise LiturgySourceError("Choose public_source or church_supplied as the verification method")
    if not isinstance(label, str) or not label.strip() or not isinstance(location, str) or not location.strip():
        raise LiturgySourceError("Record the source name and its location")
    try:
        date.fromisoformat(verified_on)
    except (TypeError, ValueError) as exc:
        raise LiturgySourceError("Record the verification date as YYYY-MM-DD") from exc
    if method == "public_source":
        url = urlparse(location)
        if url.scheme not in ("http", "https") or not url.netloc or source == text:
            raise LiturgySourceError("A public source needs its URL and a separate retained original source file")
    record = {
        "schema_version": 1, "method": method,
        "text": {"path": str(text.relative_to(root)), "sha256": _hash(text)},
        "source": {"path": str(source.relative_to(root)), "sha256": _hash(source),
                   "label": label.strip(), "location": location.strip(), "verified_on": verified_on},
    }
    sidecar = Path(str(text) + ".source.json")
    if sidecar.is_symlink():
        raise LiturgySourceError("The source record cannot be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".source-", dir=text.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, sidecar)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"status": "recorded", "record": str(sidecar), "verification": record}


def require_verified_source(church_folder: str | Path, file: str | Path) -> dict:
    """Reject missing, incomplete, or stale evidence before a text is printed."""
    root = _church_root(church_folder)
    text = _owned(root, file)
    try:
        sidecar = _owned(root, str(text) + ".source.json")
        record = json.loads(sidecar.read_text())
        source = record["source"]
        target = record["text"]
        original = _owned(root, source["path"])
        if record.get("schema_version") != 1 or record.get("method") not in ("public_source", "church_supplied"):
            raise ValueError("Unknown source record")
        if _owned(root, target["path"]) != text or target["sha256"] != _hash(text) or source["sha256"] != _hash(original):
            raise ValueError("The text or retained original changed after verification")
        if not source["label"].strip() or not source["location"].strip():
            raise ValueError("Missing source identity")
        date.fromisoformat(source["verified_on"])
        if record["method"] == "public_source":
            url = urlparse(source["location"])
            if original == text or url.scheme not in ("http", "https") or not url.netloc:
                raise ValueError("Missing original public source")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LiturgySourceError(
            f"Verify {text.name} against its source and record the comparison before using it; "
            "the source record is missing, incomplete, or no longer matches"
        ) from exc
    return record


def inspect_source(church_folder: str | Path, file: str | Path) -> dict:
    try:
        return {"status": "verified", "verification": require_verified_source(church_folder, file)}
    except LiturgySourceError as exc:
        return {"status": "needs_input", "message": str(exc)}
