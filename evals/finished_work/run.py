#!/usr/bin/env python3
"""Run Claude through a whole bulletin or sermon brief with the real tools, then grade the files.

Each run gets a fresh invented church and a private copy of the plugin. Nothing here
is a certification: the cases are ours, the sample is small, and judges are fallible.
Results, transcripts and church folders stay outside the repository.

    python3 evals/finished_work/run.py --case bulletin --runs 3 --out /some/new/folder
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABS = HERE.parents[1]
sys.path[:0] = [str(HERE)]
import fixtures as F  # noqa: E402
import grade as G  # noqa: E402
import judges as J  # noqa: E402

PLUGIN_PARTS = ("skills", "tools", "scaffold", "handbook")
TOOLS = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent,Skill"
OFF_LIMITS = ("/Desktop", "/Documents", "/Downloads", "/homebase", "evals/finished_work")
TIMEOUT = {"bulletin": 2400, "brief": 3000}
USER_AGENT = "handbuilt-church-labs-eval/1.0"
# Reported every run, but not a failure until the design decision is made. Readings print
# as long solid blocks by the template's design. That is a choice for the owner.
KNOWN_GAPS = {"prayers_readable"}


def outside_repo(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path == LABS or path.is_relative_to(LABS):
        raise SystemExit("Results must stay outside the public repository.")
    return path


def stage_plugin(destination: Path) -> None:
    """Copy what a pastor installs. The answer key and tests stay out of reach."""
    for name in PLUGIN_PARTS:
        shutil.copytree(LABS / name, destination / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in (".claude-plugin", ".codex-plugin"):
        shutil.copytree(LABS / name, destination / name)
    for name in ("requirements.txt", "requirements.lock", "AGENTS.md", "LICENSE"):
        if (LABS / name).exists():
            shutil.copy2(LABS / name, destination / name)
    # Marks a development copy, so `start` keeps this candidate and does not fetch a release.
    (destination / ".git").mkdir()


def settings(run_dir: Path) -> str:
    deny = [f"{verb}(~/{place}/**)" for verb in ("Read", "Edit", "Write") for place in ("Desktop", "Documents", "Downloads", "homebase", ".claude")]
    return json.dumps({"permissions": {"deny": deny}})


def agent_command(prompt: str, plugin: Path, church: Path, model: str, run_dir: Path) -> list[str]:
    command = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--plugin-dir", str(plugin), "--add-dir", str(run_dir),
               "--allowedTools", TOOLS, "--permission-mode", "dontAsk",
               "--settings", settings(run_dir), *J.ISOLATION]
    if model:
        command += ["--model", model]
    return command


def read_stream(path: Path) -> dict:
    """Summarize a run from its transcript. Anything malformed stays visible."""
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    uses, seen = [], []
    for event in events:
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses.append({"name": block.get("name"), "input": block.get("input")})
            elif block.get("type") == "tool_result":
                seen.append(json.dumps(block.get("content"), ensure_ascii=False))
    return {"init": init, "final": final, "uses": uses, "seen": "\n".join(seen)}


def isolation_problems(stream: dict, plugin: Path) -> list[str]:
    problems = []
    init = stream["init"]
    if not init:
        return ["the run never started"]
    if init.get("mcp_servers"):
        problems.append(f"connectors were loaded: {init['mcp_servers']}")
    # Claude Code's own built-in plugins are part of every install, so they may stay.
    plugins = [str(item.get("path", "")) for item in init.get("plugins") or [] if item.get("path") != "builtin"]
    if [Path(p).resolve() for p in plugins] != [plugin.resolve()]:
        problems.append(f"unexpected plugins: {plugins}")
    # Personal skills would mean the user's own setup leaked into the test.
    foreign = [name for name in init.get("skills") or [] if name in {"fitness", "newsletter", "task-review", "timesheet"}]
    if foreign:
        problems.append(f"personal skills were loaded: {foreign}")
    for use in stream["uses"]:
        text = json.dumps(use["input"])
        hits = [place for place in OFF_LIMITS if place in text]
        if hits:
            problems.append(f"{use['name']} touched {hits}")
    return problems


class PageText:
    """Reopen sources the way any reader could. A refusal is reported, never worked around."""

    def __init__(self) -> None:
        self.refused: dict[str, str] = {}

    def __call__(self, url: str) -> str | None:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                kind = response.headers.get("Content-Type", "")
                body = response.read(8_000_000)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.refused[url] = str(exc)[:120]
            return None
        if "pdf" in kind or url.lower().endswith(".pdf"):
            done = subprocess.run(["pdftotext", "-", "-"], input=body, capture_output=True)
            return done.stdout.decode("utf-8", "replace") or None
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", body.decode("utf-8", "replace"))
        return html.unescape(re.sub(r"<[^>]+>", " ", text))


def bulletin_judges(church: Path, graded: dict, final: str, model: str, run_dir: Path) -> dict:
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


def brief_judges(church: Path, graded: dict, final: str, model: str, run_dir: Path) -> dict:
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


def judge_counts(judged: dict) -> dict:
    passed = total = 0
    failures, ungraded, gaps = [], [], []
    for name, verdict in judged.items():
        if name in {"sources", "recheck"}:
            continue
        if verdict.get("status") != "graded":
            ungraded.append(name)
            continue
        for item in verdict["items"]:
            total += 1
            passed += bool(item["pass"])
            if not item["pass"] and item["id"] in KNOWN_GAPS:
                gaps.append(item["id"])
            elif not item["pass"]:
                failures.append({"judge": name, "id": item["id"], "why": item.get("why"), "quote": item.get("quote")})
    claims = [c for v in judged.get("sources", []) for c in v.get("claims", [])]
    tally = {key: sum(c["verdict"] == key for c in claims) for key in ("supported", "unsupported", "not_in_excerpt")}
    # A flag counts only if it survives a second look with every source in hand.
    unsupported = [c for c in judged.get("recheck", []) if c.get("recheck") != "supported"]
    return {"passed": passed, "total": total, "failures": failures, "ungraded": ungraded, "known_gaps": gaps,
            "claims": tally, "unsupported_claims": unsupported,
            "sources_ungraded": [v["url"] for v in judged.get("sources", []) if v.get("status") != "graded"]}


def one_run(case: str, number: int, out: Path, model: str, judge_model: str) -> dict:
    run_dir = out / f"{case}-{number}"
    run_dir.mkdir(parents=True)
    plugin, church = run_dir / "plugin", run_dir / "riverbend"
    stage_plugin(plugin)
    F.seed_church(church)
    prompt = (F.BULLETIN_PROMPT if case == "bulletin" else F.BRIEF_PROMPT).format(church=church)
    transcript = run_dir / "transcript.jsonl"
    started = time.time()
    timed_out = False
    with transcript.open("w", encoding="utf-8") as sink:
        try:
            subprocess.run(agent_command(prompt, plugin, church, model, run_dir), cwd=run_dir, stdout=sink,
                           stderr=subprocess.STDOUT, timeout=TIMEOUT[case], stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            timed_out = True
    return grade_run(case, number, run_dir, judge_model, seconds=round(time.time() - started), timed_out=timed_out)


def grade_run(case: str, number: int, run_dir: Path, judge_model: str, *, seconds: int, timed_out: bool) -> dict:
    """Grade the files one run left. A corrected grader can reread them without a new agent run."""
    plugin, church = run_dir / "plugin", run_dir / "riverbend"
    stream = read_stream(run_dir / "transcript.jsonl")
    final = str(stream["final"].get("result") or "")
    (run_dir / "final-message.md").write_text(final, encoding="utf-8")
    problems = isolation_problems(stream, plugin)
    fetch = PageText()
    if case == "bulletin":
        graded = G.grade_bulletin(church)
        judged = bulletin_judges(church, graded, final, judge_model, run_dir)
    else:
        graded = G.grade_brief(church, fetch, seen_by_agent=stream["seen"])
        judged = brief_judges(church, graded, final, judge_model, run_dir)
    counts = judge_counts(judged)
    failed_checks = [c for c in graded["checks"] if not c["passed"]]
    record = {"case": case, "run": number, "seconds": seconds, "timed_out": timed_out,
              "cost_estimate_usd": stream["final"].get("total_cost_usd"), "turns": stream["final"].get("num_turns"),
              "isolation_problems": problems, "checks_passed": len(graded["checks"]) - len(failed_checks),
              "checks_total": len(graded["checks"]), "failed_checks": failed_checks, "judges": counts,
              "quotes": graded.get("quotes"), "sources_refused": fetch.refused,
              "edit_pass_used": any(use["name"] in {"Agent", "Task"} for use in stream["uses"])}
    record["clean"] = bool(not problems and not timed_out and not failed_checks and not counts["failures"]
                           and not counts["ungraded"] and not counts["unsupported_claims"] and graded["checks"])
    (run_dir / "judges.json").write_text(json.dumps(judged, indent=1, ensure_ascii=False), encoding="utf-8")
    (run_dir / "result.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    return record


def table(records: list[dict]) -> str:
    rows = ["| Run | Clean | File checks | Judge items | Claims supported / unsupported / unclear | Quotes unfound | Minutes |",
            "|---|---|---|---|---|---|---|"]
    for r in records:
        claims = r["judges"]["claims"]
        quotes = r.get("quotes") or {}
        rows.append(f"| {r['case']} {r['run']} | {'yes' if r['clean'] else 'no'} | {r['checks_passed']}/{r['checks_total']} "
                    f"| {r['judges']['passed']}/{r['judges']['total']} "
                    f"| {claims['supported']} / {claims['unsupported']} / {claims['not_in_excerpt']} "
                    f"| {len(quotes.get('unfound', []))} | {r['seconds'] // 60} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("bulletin", "brief", "both"), default="both")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default="", help="Agent model. Blank uses the account default.")
    parser.add_argument("--judge-model", default="sonnet")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--regrade", action="store_true", help="Grade the runs already in --out again. No agent runs.")
    args = parser.parse_args(argv)
    out = outside_repo(args.out)
    if args.regrade:
        earlier = json.loads((out / "results.json").read_text(encoding="utf-8"))
        records = [grade_run(r["case"], r["run"], out / f"{r['case']}-{r['run']}", args.judge_model,
                             seconds=r["seconds"], timed_out=r["timed_out"]) if args.case in {"both", r["case"]} else r
                   for r in earlier]
        return report(out, records)
    if out.exists():
        raise SystemExit("Choose a new results folder; a rerun never reuses old work.")
    out.mkdir(parents=True)
    cases = ("bulletin", "brief") if args.case == "both" else (args.case,)
    jobs = [(case, n) for case in cases for n in range(1, args.runs + 1)]
    with futures.ThreadPoolExecutor(args.parallel) as pool:
        records = list(pool.map(lambda job: one_run(job[0], job[1], out, args.model, args.judge_model), jobs))
    return report(out, records)


def report(out: Path, records: list[dict]) -> int:
    (out / "results.json").write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")
    summary = table(records)
    (out / "summary.md").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    return 0 if all(r["clean"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
