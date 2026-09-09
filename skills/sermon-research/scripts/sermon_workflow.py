#!/usr/bin/env python3
"""Command line interface for the sermon research workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from sermon_workflow import orient, record  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or advance a sermon research workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("orient")
    inspect_parser.add_argument("--church-folder", required=True)
    inspect_parser.add_argument("--date", required=True)
    inspect_parser.add_argument("--mode", choices=("manual", "scheduled"), default="manual")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--church-folder", required=True)
    record_parser.add_argument("--date", required=True)
    record_parser.add_argument(
        "--stage",
        required=True,
        choices=("readings", "research"),
    )
    record_parser.add_argument("--content-file", required=True)
    record_parser.add_argument("--metadata-file")
    record_parser.add_argument("--replace", action="store_true")
    record_parser.add_argument("--mode", choices=("manual", "scheduled"), default="manual")

    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "orient":
        result = orient(args.church_folder, args.date, mode=args.mode)
    elif args.command == "record":
        content = Path(args.content_file).read_text(encoding="utf-8")
        metadata = {}
        if args.metadata_file:
            metadata = json.loads(Path(args.metadata_file).read_text(encoding="utf-8"))
        result = record(
            args.church_folder,
            args.date,
            args.stage,
            content,
            metadata,
            replace=args.replace,
            mode=args.mode,
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") not in {"blocked", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
