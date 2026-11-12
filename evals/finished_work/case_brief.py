"""Sermon research for one Sunday: real sources, real quotations, and the decision left to the pastor."""
from __future__ import annotations

import concurrent.futures as futures
from pathlib import Path

import fixtures as F
import grade as G
import judges as J
from cases import Case


def grade(church: Path, *, stream: dict, fetch, **_) -> dict:
    return G.grade_brief(church, fetch, seen_by_agent=stream["seen"])


def judges(church: Path, graded: dict, final: str, conversation: str, model: str, run_dir: Path) -> dict:
    writing = graded.get("writing") or {}
    result = {"final_message": J.rubric_judge("Grade this message an assistant left for a pastor about this week's sermon research.",
                                              J.FINAL_MESSAGE_BRIEF, final, "The passage is Matthew 25:14-30.", model, run_dir)}
    brief = writing.get("brief")
    if brief:
        result["quality"] = J.rubric_judge("Grade this sermon research brief for a pastor preparing Matthew 25:14-30.",
                                           J.BRIEF_QUALITY, brief, "The brief prepares the pastor's own discernment.", model, run_dir)
        with futures.ThreadPoolExecutor(4) as pool:
            jobs = [pool.submit(J.source_judge, url, page, brief, model, run_dir) for url, page in graded.get("sources", {}).items()]
            result["sources"] = [job.result() for job in jobs]
        flagged = [c for v in result["sources"] for c in v.get("claims", []) if c["verdict"] == "unsupported"]
        result["recheck"] = [J.recheck_claim(c, graded["sources"], brief, model, run_dir) for c in flagged]
    return result


CASE = Case(name="brief", prompt=F.BRIEF_PROMPT, seed=F.seed_church, grade=grade, judges=judges, timeout=3000)
