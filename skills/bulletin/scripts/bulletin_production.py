#!/usr/bin/env python3
"""Command-line adapter for the bulletin-production interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from skills.bulletin.bulletin_production import finalize, orient, produce, revise  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    orient_parser = commands.add_parser("orient")
    orient_parser.add_argument("--church-folder", required=True)
    orient_parser.add_argument("--date", required=True)

    produce_parser = commands.add_parser("produce")
    produce_parser.add_argument("--church-folder", required=True)
    produce_parser.add_argument("--input", required=True)

    revise_parser = commands.add_parser("revise")
    revise_parser.add_argument("--church-folder", required=True)
    revise_parser.add_argument("--prior-run", required=True)
    revise_parser.add_argument("--input", required=True)

    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--receipt", required=True)
    finalize_parser.add_argument("--approval", required=True)

    args = parser.parse_args()
    if args.command == "orient":
        result = orient(args.church_folder, args.date)
    elif args.command == "produce":
        bulletin = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = produce(args.church_folder, bulletin)
    elif args.command == "revise":
        bulletin = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = revise(args.church_folder, args.prior_run, bulletin)
    else:
        approval = json.loads(Path(args.approval).read_text(encoding="utf-8"))
        result = finalize(args.receipt, approval)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"ok", "ready_for_review", "approved"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
