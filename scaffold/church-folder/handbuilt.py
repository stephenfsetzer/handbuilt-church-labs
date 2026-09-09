#!/usr/bin/env python3
"""Open this church's installed Handbuilt workflows without guessing paths."""

import json
from pathlib import Path
import runpy
import sys


def main():
    church = Path(__file__).resolve().parent
    try:
        connection = json.loads((church / ".handbuilt" / "installation.json").read_text())
        plugin = Path(connection["plugin_root"])
        if not plugin.is_absolute():
            raise ValueError("The plugin connection must use an absolute installation path")
        manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text())
        if manifest.get("name") != "handbuilt-church-labs":
            raise ValueError("The saved location is not Handbuilt Church Labs")
        entry = plugin / "tools" / "church_workflow.py"
        if not entry.is_file():
            raise ValueError("The installed Handbuilt workflow is unavailable")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({
            "status": "blocked", "code": "handbuilt_not_connected",
            "message": "This church folder needs its Handbuilt plugin connection repaired.",
            "next_action": "Load the installed Handbuilt onboarding skill and reconnect this existing folder. Do not create another renderer or use a personal sermon skill.",
            "detail": str(exc),
        }, indent=2))
        return 2
    sys.argv = [str(entry), "--church-folder", str(church), *sys.argv[1:]]
    runpy.run_path(str(entry), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
