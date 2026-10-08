#!/usr/bin/env python3
"""Command line interface for the Build My Brand workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from brand_workflow import (  # noqa: E402
    LEGACY_STAGES, STAGES, approve, check_marks, explore, orient, record, redirect, render_guide, restart, stage_brand,
)


class _Parser(argparse.ArgumentParser):
    """Help and usage errors answer in JSON, so a launcher never mistakes help for a failed run."""

    def print_help(self, file=None):  # noqa: D401
        print(json.dumps({"status": "help", "usage": self.format_help()}, indent=2))

    def error(self, message):
        print(json.dumps({"status": "blocked", "errors": [{"code": "invalid_arguments", "message": message}],
                          "usage": self.format_usage().strip()}, indent=2))
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Inspect or advance a church's Build My Brand workflow")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    item = sub.add_parser("orient", help="Where the run stands and what comes next")
    item.add_argument("--church-folder", required=True)

    item = sub.add_parser("record", help="Record a stage into the guide with its decision and why")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--stage", required=True, choices=STAGES + tuple(LEGACY_STAGES))
    item.add_argument("--content-file", required=True)
    item.add_argument("--metadata-file")
    item.add_argument("--replace", action="store_true")

    item = sub.add_parser("explore", help="Lay a round of internal exploration out on a contact sheet")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--round", required=True, help="A short name for the round, for example sketches-1")
    item.add_argument("--files", nargs="+", required=True, help="SVG or PNG sketches inside the church folder")
    item.add_argument("--maker", default="maker")
    item.add_argument("--dark", help="The dark color for the reversed render, six-digit hex")

    item = sub.add_parser("redirect", help="The creative director stops an exploration round, says why, and re-briefs")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--round", required=True)
    item.add_argument("--reason", required=True)
    item.add_argument("--rebrief-file", help="A Markdown file with the new brief")

    item = sub.add_parser("check-marks", help="Run the pass/fail survival checks on the marks")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--primary", help="The primary mark SVG under brand/staging/ (defaults to the staged system)")
    item.add_argument("--small", help="The derived small-size variant SVG under brand/staging/")
    item.add_argument("--dark", help="The dark color for the reversal check, six-digit hex")

    item = sub.add_parser("stage-brand", help="Validate the built system and stage it for approval")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--patch-file", required=True)

    item = sub.add_parser("approve", help="Replace the live brand with the staged one; archives the old")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--approved-by", default="pastor")

    item = sub.add_parser("render-guide", help="Render the brand guide to PDF in the church's own brand")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--out")

    item = sub.add_parser("restart", help="Archive an unfinished run and begin again")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--reason", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "orient":
        result = orient(args.church_folder)
    elif args.command == "record":
        content = Path(args.content_file).read_text(encoding="utf-8")
        metadata = json.loads(Path(args.metadata_file).read_text(encoding="utf-8")) if args.metadata_file else {}
        result = record(args.church_folder, args.stage, content, metadata, replace=args.replace)
    elif args.command == "explore":
        result = explore(args.church_folder, args.round, args.files, maker=args.maker, dark=args.dark)
    elif args.command == "redirect":
        rebrief = Path(args.rebrief_file).read_text(encoding="utf-8") if args.rebrief_file else None
        result = redirect(args.church_folder, args.round, args.reason, rebrief=rebrief)
    elif args.command == "check-marks":
        result = check_marks(args.church_folder, primary=args.primary, small=args.small, dark=args.dark)
    elif args.command == "stage-brand":
        result = stage_brand(args.church_folder, json.loads(Path(args.patch_file).read_text(encoding="utf-8")))
    elif args.command == "approve":
        result = approve(args.church_folder, approved_by=args.approved_by)
    elif args.command == "restart":
        result = restart(args.church_folder, reason=args.reason)
    else:
        result = render_guide(args.church_folder, args.out)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") not in {"blocked", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
