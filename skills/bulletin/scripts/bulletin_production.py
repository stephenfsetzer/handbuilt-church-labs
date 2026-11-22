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
from skills.bulletin.bulletin_production import standing  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    orient_parser = commands.add_parser("orient")
    orient_parser.add_argument("--church-folder", required=True)
    orient_parser.add_argument("--date", required=True)
    orient_parser.add_argument("--service-id")
    orient_parser.add_argument("--occurrence-id")

    produce_parser = commands.add_parser("produce")
    produce_parser.add_argument("--church-folder", required=True)
    produce_parser.add_argument("--input", required=True)

    revise_parser = commands.add_parser("revise")
    revise_parser.add_argument("--church-folder", required=True)
    revise_parser.add_argument("--prior-run", required=True)
    revise_parser.add_argument("--input", required=True)
    revise_parser.add_argument("--correct-approved", action="store_true")

    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--receipt", required=True)
    finalize_parser.add_argument("--approval", required=True)

    carry = commands.add_parser("carry-forward", help="start this Sunday from the last approved bulletin")
    carry.add_argument("--church-folder", required=True)
    carry.add_argument("--date", required=True)
    carry.add_argument("--service-id")
    carry.add_argument("--occurrence-id")

    kept = commands.add_parser("keep", help="keep an answer for this season or from now on")
    kept.add_argument("--church-folder", required=True)
    kept.add_argument("--date", required=True, help="the Sunday the answer was given for")
    kept.add_argument("--key", required=True)
    kept.add_argument("--question", required=True)
    kept.add_argument("--answer", required=True)
    kept.add_argument("--keep", required=True, choices=standing.KEEPS)

    listed = commands.add_parser("standing", help="the kept answers that apply on a Sunday")
    listed.add_argument("--church-folder", required=True)
    listed.add_argument("--date", required=True)

    adopted = commands.add_parser("adopt", help="record a bulletin approved outside the skill into history, once")
    adopted.add_argument("--church-folder", required=True)
    adopted.add_argument("--bulletin", required=True, help="the week folder that holds its bulletin-config.json")
    adopted.add_argument("--approved-by", required=True)
    adopted.add_argument("--note", default="")

    args = parser.parse_args()
    if args.command in {"carry-forward", "keep", "standing", "adopt"}:
        from datetime import date as _date
        root = Path(args.church_folder).resolve()
        try:
            if args.command == "carry-forward":
                result = standing.carry_forward(root, _date.fromisoformat(args.date),
                                                service_id=args.service_id, occurrence_id=args.occurrence_id)
            elif args.command == "keep":
                result = standing.keep(root, key=args.key, question=args.question, answer=args.answer,
                                       keep=args.keep, sunday=_date.fromisoformat(args.date))
            elif args.command == "standing":
                result = {"status": "ok", "choices": standing.applicable(root, _date.fromisoformat(args.date))}
            else:
                result = standing.adopt(root, root / args.bulletin, approved_by=args.approved_by, note=args.note)
        except (standing.StandingError, ValueError) as exc:
            result = {"status": "failed", "code": getattr(exc, "code", "invalid_input"), "message": str(exc)}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("status") == "ok" else 2
    if args.command == "orient":
        result = orient(args.church_folder, args.date, service_id=args.service_id, occurrence_id=args.occurrence_id)
    elif args.command == "produce":
        bulletin = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = produce(args.church_folder, bulletin)
    elif args.command == "revise":
        bulletin = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = revise(args.church_folder, args.prior_run, bulletin, correct_approved=args.correct_approved)
    else:
        approval = json.loads(Path(args.approval).read_text(encoding="utf-8"))
        result = finalize(args.receipt, approval)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"ok", "ready_for_review", "approved"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
