#!/usr/bin/env python3
"""Turn on and check automatic Handbuilt updates in Claude Code.

``enable`` merges three settings into Claude Code's user settings file and
keeps every other setting:

- ``extraKnownMarketplaces.handbuilt-church-labs.autoUpdate = true``: Claude
  Code leaves automatic updates off for marketplaces outside Anthropic's own.
- ``env.FORCE_AUTOUPDATE_PLUGINS = "1"``: the Claude desktop app starts Code
  sessions with ``DISABLE_AUTOUPDATER=1``, which switches the plugin update
  pass off entirely unless this is set.
- ``enabledPlugins["handbuilt-church-labs@handbuilt-church-labs"] = true``,
  only when the entry is missing. A pastor's explicit ``false`` is kept.

A backup of the previous file is saved beside it before any change.

``status`` reports the installed version, the latest published release, and
whether automatic updates are on. Both commands print one JSON object.
Standard library only, so it runs on the Python that ships with macOS.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


NAME = "handbuilt-church-labs"
PLUGIN_ID = f"{NAME}@{NAME}"
REPOSITORY_URL = "https://github.com/stephenfsetzer/handbuilt-church-labs.git"
LATEST_RELEASE_API = "https://api.github.com/repos/stephenfsetzer/handbuilt-church-labs/releases/latest"
FORCE_VARIABLE = "FORCE_AUTOUPDATE_PLUGINS"


class SettingsError(ValueError):
    """Raised when the settings file cannot be merged safely."""


def config_dir(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def _read_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SettingsError(f"{path} is not valid JSON, so it was left unchanged.") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path} does not hold a settings object, so it was left unchanged.")
    return data


def _section(data: Dict[str, Any], key: str, path: Path) -> Dict[str, Any]:
    value = data.setdefault(key, {})
    if not isinstance(value, dict):
        raise SettingsError(f"{key} in {path} is not an object, so the file was left unchanged.")
    return value


def merged(data: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """Return a copy of ``data`` with Handbuilt's automatic updates turned on."""
    result = json.loads(json.dumps(data))
    marketplaces = _section(result, "extraKnownMarketplaces", path)
    entry = marketplaces.get(NAME)
    if entry is None:
        entry = {"source": {"source": "git", "url": REPOSITORY_URL}}
    if not isinstance(entry, dict):
        raise SettingsError(f"The {NAME} marketplace entry in {path} is not an object.")
    entry.setdefault("source", {"source": "git", "url": REPOSITORY_URL})
    entry["autoUpdate"] = True
    marketplaces[NAME] = entry
    _section(result, "env", path)[FORCE_VARIABLE] = "1"
    _section(result, "enabledPlugins", path).setdefault(PLUGIN_ID, True)
    return result


def _write_atomically(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        json.loads(Path(temporary).read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enable(directory: Path) -> Dict[str, Any]:
    path = directory / "settings.json"
    current = _read_settings(path)
    updated = merged(current, path)
    disabled = updated["enabledPlugins"].get(PLUGIN_ID) is False
    if updated == current:
        return {"status": "already_on", "settings": str(path), "plugin_disabled": disabled,
                "message": "Automatic Handbuilt updates were already on."}
    backup = None
    if path.exists():
        backup = path.with_name(f"settings.json.before-handbuilt-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_bytes(path.read_bytes())
    _write_atomically(path, updated)
    return {"status": "turned_on", "settings": str(path), "backup": str(backup) if backup else None,
            "plugin_disabled": disabled,
            "message": "Automatic Handbuilt updates are on. New versions install in the background "
                       "and load in the next session."}


def _installed_version(directory: Path) -> Optional[str]:
    record = directory / "plugins" / "installed_plugins.json"
    try:
        installs = json.loads(record.read_text(encoding="utf-8"))["plugins"].get(PLUGIN_ID) or []
    except (OSError, ValueError, KeyError, AttributeError):
        return None
    versions = [item.get("version") for item in installs if isinstance(item, dict)]
    return next((version for version in versions if version), None)


def _synced_version(directory: Path) -> Optional[str]:
    for manifest in sorted((directory / "plugins" / "synced").glob(f"*/{NAME}/.claude-plugin/plugin.json")):
        try:
            return json.loads(manifest.read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            continue
    return None


def _latest_release(timeout: float = 10.0) -> Tuple[Optional[str], Optional[str]]:
    request = urllib.request.Request(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            tag = json.load(response).get("tag_name") or ""
    except (OSError, ValueError) as exc:
        return None, f"The latest release could not be checked ({exc.__class__.__name__})."
    return (tag[1:] if tag.startswith("v") else tag) or None, None


def status(directory: Path, offline: bool = False) -> Dict[str, Any]:
    path = directory / "settings.json"
    settings = _read_settings(path)
    entry = (settings.get("extraKnownMarketplaces") or {}).get(NAME) or {}
    auto_update = isinstance(entry, dict) and entry.get("autoUpdate") is True
    forced = str((settings.get("env") or {}).get(FORCE_VARIABLE, "")).lower() in {"1", "true"}
    installed = _installed_version(directory)
    latest, problem = (None, "Offline; the latest release was not checked.") if offline else _latest_release()
    result: Dict[str, Any] = {
        "settings": str(path),
        "installed_version": installed,
        "synced_app_copy_version": _synced_version(directory),
        "latest_release": latest,
        "auto_update_on": auto_update,
        "desktop_updates_allowed": forced,
        "plugin_enabled": (settings.get("enabledPlugins") or {}).get(PLUGIN_ID) is True,
    }
    if problem:
        result["release_check"] = problem
    gaps = []
    if installed is None:
        gaps.append("Handbuilt is not installed in Claude Code here")
    if not auto_update:
        gaps.append("automatic updates are off for the Handbuilt marketplace")
    if not forced:
        gaps.append(f"{FORCE_VARIABLE} is not set, so desktop app sessions skip plugin updates")
    if installed and latest and installed != latest:
        gaps.append(f"version {installed} is installed and {latest} is the latest release")
    result["status"] = "current" if not gaps else "needs_attention"
    summary = "; ".join(gaps)
    result["message"] = ("Handbuilt is installed, current, and set to update itself."
                         if not gaps else summary[:1].upper() + summary[1:] + ".")
    return result


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("enable", "status"))
    parser.add_argument("--config-dir", help="Claude Code settings folder (default: $CLAUDE_CONFIG_DIR or ~/.claude).")
    parser.add_argument("--offline", action="store_true", help="status: skip the latest-release check.")
    arguments = parser.parse_args(argv)
    directory = config_dir(arguments.config_dir)
    try:
        result = enable(directory) if arguments.command == "enable" else status(directory, arguments.offline)
    except SettingsError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"turned_on", "already_on", "current"} else 1


if __name__ == "__main__":
    sys.exit(main())
