#!/usr/bin/env python3
"""The finance report workflow's single entry point for the Handbuilt launcher.

    finance_report.py status --church-folder DIR [--month YYYY-MM]
    finance_report.py setup  --church-folder DIR draft|budget|one-time|apply [options]
    finance_report.py build  --church-folder DIR --month YYYY-MM --prepared YYYY-MM-DD [options]
    finance_report.py render --church-folder DIR REPORT_JSON [--brand FILE --suffix NAME]

Each operation prints one JSON result with a "status". The work itself lives
in the modules beside this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_report_data  # noqa: E402
import finance_report_status  # noqa: E402
import finance_setup  # noqa: E402
import report_renderer  # noqa: E402

OPERATIONS = ("status", "setup", "build", "render")


def split_church(args):
    """Take --church-folder out of the arguments, wherever the launcher put it."""
    church, rest, i = ".", [], 0
    while i < len(args):
        if args[i] == "--church-folder" and i + 1 < len(args):
            church, i = args[i + 1], i + 2
        elif args[i].startswith("--church-folder="):
            church, i = args[i].split("=", 1)[1], i + 1
        else:
            rest.append(args[i])
            i += 1
    return church, rest


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in OPERATIONS:
        sys.exit(f"Choose one of: {', '.join(OPERATIONS)}")
    operation, (church, rest) = argv[0], split_church(argv[1:])
    if operation == "status":
        return finance_report_status.main(["--church-folder", church, *rest])
    if operation == "setup":
        if not rest:
            sys.exit("Choose a setup step: draft, budget, one-time, or apply")
        return finance_setup.main([rest[0], "--church-folder", church, *rest[1:]])
    if operation == "build":
        return build_report_data.main(["--church-folder", church, *rest])
    return report_renderer.main([*rest, "--church-folder", church])


if __name__ == "__main__":
    main()
