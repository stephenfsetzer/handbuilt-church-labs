#!/usr/bin/env python3
"""Read installation identities without selecting, updating, or repairing them."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


_MANIFESTS = (
    ("codex", ".codex-plugin/plugin.json"),
    ("claude", ".claude-plugin/plugin.json"),
)


def inspect_installation(
    loaded_root: Path, church_root: Path, latest: Optional[dict] = None
) -> dict:
    """Return identities for one loaded plugin root and one church connection.

    This function deliberately does not search plugin caches, fetch releases, or
    modify either root.  ``latest`` is optional injected release metadata so its
    status remains independent from the app-loaded installation and the private
    church connection.
    """
    root = Path(loaded_root).expanduser().resolve()
    church = Path(church_root).expanduser().resolve()
    loaded = _inspect_loaded(root)
    connection = _inspect_connection(church, root, loaded)
    return {
        "schema_version": 1,
        "loaded": loaded,
        "connection": connection,
        "latest": _inspect_latest(latest),
    }


def _inspect_loaded(root: Path) -> dict:
    manifests: Dict[str, dict] = {}
    errors: List[dict] = []
    for host, relative in _MANIFESTS:
        manifest, error = _read_manifest(root / relative, host)
        manifests[host] = manifest
        if error:
            errors.append(error)

    codex = manifests["codex"]
    claude = manifests["claude"]
    name = None
    version = None
    manifest_sha256 = None
    if not errors:
        if codex["name"] != claude["name"] or codex["version"] != claude["version"]:
            errors.append({"code": "manifest_identity_mismatch"})
        else:
            name = codex["name"]
            version = codex["version"]
            # church_workflow.installation records the Codex manifest hash.
            manifest_sha256 = codex["sha256"]

    return {
        "status": "ready" if not errors else "invalid",
        "root": str(root),
        "origin": _classify_origin(root),
        "name": name,
        "version": version,
        "manifest_sha256": manifest_sha256,
        "manifests": manifests,
        "errors": errors,
    }


def _read_manifest(path: Path, host: str) -> Tuple[dict, Optional[dict]]:
    empty = {"status": "unknown", "name": None, "version": None, "sha256": None}
    try:
        contents = path.read_bytes()
    except FileNotFoundError:
        return empty, {"code": "manifest_missing", "manifest": host}
    except OSError:
        return empty, {"code": "manifest_unreadable", "manifest": host}
    try:
        data = json.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return empty, {"code": "manifest_malformed", "manifest": host}
    if not isinstance(data, Mapping):
        return empty, {"code": "manifest_invalid", "manifest": host}
    name = data.get("name")
    version = data.get("version")
    if name != "handbuilt-church-labs" or not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        return empty, {"code": "manifest_invalid", "manifest": host}
    return {
        "status": "ready",
        "name": name,
        "version": version,
        "sha256": hashlib.sha256(contents).hexdigest(),
    }, None


def _inspect_connection(church: Path, loaded_root: Path, loaded: Mapping[str, Any]) -> dict:
    result = {
        "status": "unknown",
        "connection_matches": None,
        "root_matches": None,
        "name_matches": None,
        "version_matches": None,
        "manifest_sha256_matches": None,
        "development_connection": False,
        "version": None,
        "root": None,
        "errors": [],
    }
    path = church / ".handbuilt" / "installation.json"
    if path.is_symlink() or not path.resolve().is_relative_to(church):
        result["status"] = "invalid"
        result["errors"].append({"code": "connection_symlink"})
        return result
    try:
        contents = path.read_bytes()
    except FileNotFoundError:
        result["status"] = "missing"
        result["errors"].append({"code": "connection_missing"})
        return result
    except OSError:
        result["status"] = "invalid"
        result["errors"].append({"code": "connection_unreadable"})
        return result
    try:
        data = json.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result["status"] = "invalid"
        result["errors"].append({"code": "connection_malformed"})
        return result
    if not isinstance(data, Mapping):
        result["status"] = "invalid"
        result["errors"].append({"code": "connection_invalid"})
        return result

    saved_root = data.get("plugin_root")
    saved_name = data.get("plugin_name")
    saved_version = data.get("plugin_version")
    saved_sha = data.get("manifest_sha256")
    if not _nonempty_string(saved_root) or not Path(saved_root).is_absolute():
        result["errors"].append({"code": "connection_plugin_root_invalid"})
    if not _nonempty_string(saved_name):
        result["errors"].append({"code": "connection_plugin_name_invalid"})
    if not _nonempty_string(saved_version):
        result["errors"].append({"code": "connection_plugin_version_invalid"})
    if not _nonempty_string(saved_sha):
        result["errors"].append({"code": "connection_manifest_sha256_invalid"})
    if result["errors"]:
        result["status"] = "invalid"
        return result

    resolved_saved_root = Path(saved_root).expanduser().resolve()
    result["root"] = str(resolved_saved_root)
    result["version"] = saved_version
    result["development_connection"] = _classify_origin(resolved_saved_root) == "development"
    if loaded.get("status") != "ready":
        result["status"] = "connected"
        result["errors"].append({"code": "loaded_identity_unavailable"})
        return result

    result["root_matches"] = resolved_saved_root == loaded_root
    result["name_matches"] = saved_name == loaded.get("name")
    result["version_matches"] = saved_version == loaded.get("version")
    result["manifest_sha256_matches"] = saved_sha == loaded.get("manifest_sha256")
    result["connection_matches"] = all(
        result[field]
        for field in ("root_matches", "name_matches", "version_matches", "manifest_sha256_matches")
    )
    result["status"] = "connected"
    return result


def _inspect_latest(latest: Optional[dict]) -> dict:
    if latest is None:
        return {"status": "unknown", "name": None, "version": None, "manifest_sha256": None,
                "errors": []}
    if not isinstance(latest, Mapping):
        return {"status": "invalid", "name": None, "version": None, "manifest_sha256": None,
                "errors": [{"code": "latest_invalid"}]}
    name = latest.get("name")
    version = latest.get("version")
    sha = latest.get("manifest_sha256")
    errors = []
    if not _nonempty_string(name):
        errors.append({"code": "latest_name_invalid"})
    if not _nonempty_string(version):
        errors.append({"code": "latest_version_invalid"})
    if sha is not None and not _nonempty_string(sha):
        errors.append({"code": "latest_manifest_sha256_invalid"})
    return {
        "status": "available" if not errors else "invalid",
        "name": name if _nonempty_string(name) else None,
        "version": version if _nonempty_string(version) else None,
        "manifest_sha256": sha if _nonempty_string(sha) else None,
        "errors": errors,
    }


def _classify_origin(root: Path) -> str:
    parts = root.parts
    if _contains_parts(parts, (".codex", "plugins", "cache")):
        return "codex"
    if _contains_parts(parts, (".claude", "plugins", "cache")):
        return "claude-code"
    if _contains_parts(parts, ("Claude", "local-agent-mode-sessions")) and "rpm" in parts:
        return "claude-desktop"
    # Host-installed caches can retain Git metadata from their source clone.
    if (root / ".git").exists():
        return "development"
    return "unknown"


def is_development_root(root: Path) -> bool:
    return _classify_origin(Path(root).expanduser().resolve()) == "development"


def _contains_parts(parts: Tuple[str, ...], sequence: Tuple[str, ...]) -> bool:
    length = len(sequence)
    return any(parts[index:index + length] == sequence for index in range(len(parts) - length + 1))


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
