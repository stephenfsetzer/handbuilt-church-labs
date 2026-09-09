#!/usr/bin/env python3
"""Create a reviewable September 20 rehearsal without using church data."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "skills" / "sermon-research"))

from sermon_workflow import orient as sermon_orient  # noqa: E402
from sermon_workflow import record as sermon_record  # noqa: E402
from skills.bulletin.bulletin_production import produce  # noqa: E402
from tests.helpers import (  # noqa: E402
    bulletin_input,
    make_church,
    make_nonlectionary_church,
    pastor_selected_reading_metadata,
    pastor_selected_readings_content,
    pastor_selected_research_metadata,
    reading_metadata,
    readings_content,
    research_brief,
    research_metadata,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run both workflows to their defined completion states")
    parser.add_argument(
        "--output",
        help="Optional new directory for the synthetic church folder. Defaults to system temporary storage.",
    )
    parser.add_argument(
        "--sermon-selection-mode",
        choices=("lectionary", "pastor_selected"),
        default="lectionary",
    )
    args = parser.parse_args()
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if output == REPO_ROOT or output.is_relative_to(REPO_ROOT):
            print(json.dumps({
                "status": "blocked",
                "message": "Rehearsal output must stay outside the public repository",
            }, indent=2))
            return 2
        if output.exists():
            print(json.dumps({
                "status": "blocked",
                "message": f"Output already exists: {output}",
            }, indent=2))
            return 2
        output.mkdir(parents=True)
    else:
        output = Path(tempfile.mkdtemp(prefix="handbuilt-church-labs-rehearsal-"))
    church = (
        make_church(output)
        if args.sermon_selection_mode == "lectionary"
        else make_nonlectionary_church(output)
    )
    target_date = "2026-09-20"

    bulletin = produce(church, bulletin_input())
    if bulletin.get("status") != "ready_for_review":
        print(json.dumps({"status": "failed", "bulletin": bulletin}, indent=2))
        return 1

    selected_mode = args.sermon_selection_mode == "pastor_selected"
    readings = sermon_record(
        church,
        target_date,
        "readings",
        pastor_selected_readings_content() if selected_mode else readings_content(),
        pastor_selected_reading_metadata() if selected_mode else reading_metadata(),
    )
    research = sermon_record(
        church,
        target_date,
        "research",
        (
            research_brief(
                citation="Test Gospel 4:1-8",
                selection_mode="pastor_selected",
            )
            if selected_mode
            else research_brief()
        ),
        pastor_selected_research_metadata() if selected_mode else research_metadata(),
        mode="scheduled",
    )
    sermon = sermon_orient(church, target_date)
    expected = (
        readings.get("status") == "recorded"
        and research.get("status") == "recorded"
        and sermon.get("workflow_state") == "research_complete"
    )
    summary = {
        "status": "ready_for_review" if expected else "failed",
        "service_date": target_date,
        "synthetic_data": True,
        "sermon_selection_mode": args.sermon_selection_mode,
        "church_folder": str(church),
        "bulletin": bulletin,
        "sermon": sermon,
        "gate_summary": {
            "bulletin": "ready_for_review",
            "sermon": "research_complete",
        },
    }
    summary_path = output / "workflow-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    print(json.dumps(summary, indent=2))
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
