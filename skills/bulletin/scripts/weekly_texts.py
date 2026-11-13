#!/usr/bin/env python3
"""Copy the Sunday's verified texts into a weekly bulletin file, so no one retypes them."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills.bulletin.weekly_texts import WeeklyTextsError, fill_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fill = commands.add_parser("fill")
    fill.add_argument("--input", required=True, help="The weekly bulletin file to fill in place.")
    fill.add_argument("--lectionary-page", help="This Sunday's page on https://lectionarypage.net/.")
    fill.add_argument("--optional-verses", choices=("include", "omit"),
                      help="What to do with verses the lectionary marks optional.")
    args = parser.parse_args()
    try:
        result = fill_file(args.input, page_url=args.lectionary_page, optional=args.optional_verses)
    except (WeeklyTextsError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "needs_input", "message": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
