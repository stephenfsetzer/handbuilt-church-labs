#!/usr/bin/env python3
"""Fail a pull request that changes what installs receive without a new version.

Claude Code decides whether an installed plugin has an update by comparing
version numbers, and the managed workflow updater installs only tagged
releases. A change merged at an unchanged version therefore never reaches a
pastor whose install already has that version. This check compares the pull
request with its base branch: when any shipped file changed, the plugin
version must be higher than the base's.

Documentation read on GitHub (README, INSTALL), tests, CI configuration and
lane records are not shipped behavior, so they can change at the same version.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ".claude-plugin/plugin.json"
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHIPPED_PREFIXES = (
    "skills/",
    "tools/",
    "scaffold/",
    "handbook/",
    ".claude-plugin/",
    ".codex-plugin/",
    ".agents/",
    ".claude/skills/",
)
SHIPPED_FILES = ("requirements.txt", "requirements.lock")


def shipped(paths: Iterable[str]) -> list[str]:
    """Return the changed paths that installs receive."""
    return sorted(
        path for path in paths
        if path.startswith(SHIPPED_PREFIXES) or path in SHIPPED_FILES
    )


def parse_version(text: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(text)
    if not match:
        raise ValueError(f"Plugin version {text!r} is not X.Y.Z.")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments], check=True, capture_output=True, text=True
    ).stdout


def _version_at(ref: Optional[str]) -> str:
    text = _git("show", f"{ref}:{MANIFEST}") if ref else (ROOT / MANIFEST).read_text(encoding="utf-8")
    return json.loads(text)["version"]


def check(base: str) -> tuple[bool, str]:
    changed = _git("diff", "--name-only", f"{base}...HEAD").split()
    files = shipped(changed)
    if not files:
        return True, "No shipped files changed, so no version bump is needed."
    old, new = _version_at(base), _version_at(None)
    if parse_version(new) > parse_version(old):
        return True, f"Shipped files changed and the version moves from {old} to {new}."
    listed = "\n".join(f"  {path}" for path in files[:20])
    more = f"\n  ...and {len(files) - 20} more" if len(files) > 20 else ""
    return False, (
        f"Shipped files changed but the plugin version is still {new} (base {old}).\n"
        f"{listed}{more}\n"
        "Raise the version in .claude-plugin/plugin.json, .claude-plugin/marketplace.json,\n"
        ".codex-plugin/plugin.json and .agents/plugins/marketplace.json. Without a new\n"
        "version, installs that already have this version never receive the change."
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="Git ref the pull request merges into.")
    arguments = parser.parse_args(argv)
    passed, message = check(arguments.base)
    print(message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
