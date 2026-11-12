"""This Sunday's bulletin from a pastor's message, with one hymn undecided and a blank left in."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import fixtures as F
import grade as G
import judges as J
from cases import Case


def grade(church: Path, **_) -> dict:
    return G.grade_bulletin(church)


def judges(church: Path, graded: dict, final: str, conversation: str, model: str, run_dir: Path) -> dict:
    writing = graded.get("writing") or {}
    receipt = writing.get("receipt") or {}
    context = F.BULLETIN_PROMPT.format(church="(the church folder)") + "\n\nCalendar facts and saved church settings are not invented.\n\n" + json.dumps(
        {"fit_summary": receipt.get("fit_summary"),
         "warnings": [w for w in receipt.get("warnings", []) if w.get("code") != "music_title_fallback"],
         "open_items": receipt.get("open_items")}, indent=1)
    result = {"final_message": J.rubric_judge("Grade this message an assistant left for a pastor about this week's bulletin.",
                                              J.FINAL_MESSAGE_BULLETIN, final, context, model, run_dir)}
    if writing.get("pdf"):
        pages = run_dir / "pages"
        shutil.rmtree(pages, ignore_errors=True)
        pages.mkdir()
        subprocess.run(["pdftoppm", "-r", "100", "-png", writing["pdf"], str(pages / "page")], check=True)
        result["visual"] = J.visual_judge(sorted(pages.glob("*.png")), model, pages)
    return result


CASE = Case(name="bulletin", prompt=F.BULLETIN_PROMPT, seed=F.seed_church, grade=grade, judges=judges, timeout=2400)
