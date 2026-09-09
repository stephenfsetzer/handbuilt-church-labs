#!/usr/bin/env python3
"""Record or inspect verification of one private worship text."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills.bulletin.liturgy_sources import LiturgySourceError, inspect_source, record_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "record"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--church-folder", required=True)
        cmd.add_argument("--file", required=True)
        if name == "record":
            for field in ("source-file", "label", "location", "verified-on"):
                cmd.add_argument("--" + field, required=True)
            cmd.add_argument("--method", required=True, choices=("public_source", "church_supplied"))
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = record_source(**args) if command == "record" else inspect_source(**args)
    except (LiturgySourceError, OSError) as exc:
        result = {"status": "needs_input", "message": str(exc)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("recorded", "verified") else 2


if __name__ == "__main__":
    raise SystemExit(main())
