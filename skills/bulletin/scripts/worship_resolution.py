#!/usr/bin/env python3
"""Command-line adapter for the worship-profile resolver."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from skills.bulletin.worship_resolution import (  # noqa: E402
    WorshipResolutionError,
    as_error,
    resolve_worship_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--church-folder", required=True)
    parser.add_argument("--weekly-input")
    args = parser.parse_args()
    weekly = {}
    if args.weekly_input:
        weekly = json.loads(Path(args.weekly_input).read_text(encoding="utf-8"))
    try:
        result = resolve_worship_profile(args.church_folder, weekly)
    except WorshipResolutionError as exc:
        print(json.dumps(as_error(exc), indent=2, ensure_ascii=False))
        return 2
    result["status"] = "needs_input" if result["unresolved"] else "resolved"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "resolved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
