#!/usr/bin/env python3
"""Read only the selected entry from the bundled Sunday worship library."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills.bulletin.sunday_library import SundayLibraryError, catalog, lookup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("category", choices=("collects", "prefaces", "psalms"))
    get = commands.add_parser("get")
    get.add_argument("category", choices=("collects", "prefaces", "psalms"))
    get.add_argument("identifier")
    get.add_argument("--verses")
    get.add_argument("--psalm-format", default="responsive_half_verse")
    get.add_argument("--response-start", default="second")
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = catalog(**args) if command == "list" else lookup(**args)
    except SundayLibraryError as exc:
        print(json.dumps({"status": "needs_input", "message": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
