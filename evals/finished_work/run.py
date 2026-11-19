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
import os
import re
import threading
import signal
import queue
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
sys.path.append(str(HERE.parent / "connector"))
import cases as C  # noqa: E402
import client as K  # noqa: E402
import judges as J  # noqa: E402
import pastor as P  # noqa: E402

CASES = C.load()

PLUGIN_PARTS = ("skills", "tools", "scaffold", "handbook")
TOOLS = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent,Skill"
# The connector path is a pastor's own Claude: web search and the Handbuilt connector, no
# files on this computer and no plugin.
CONNECTOR_NAME = "handbuilt"
CONNECTOR_BUILTINS = "WebFetch,WebSearch"
LOCAL_TOOLS = {"Bash", "Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit", "Skill"}
OFF_LIMITS = ("/Desktop", "/Documents", "/Downloads", "/homebase", "evals/finished_work")
USER_AGENT = "handbuilt-church-labs-eval/1.0"
# A judge item listed here is reported every run but does not fail it. Use it only while an
# owner decision is pending, and record the decision in the README when it is made.
KNOWN_GAPS: set[str] = set()


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


def connector_config(run_dir: Path, url: str) -> Path:
    """The connector as the agent's only MCP server. The token stays in the environment."""
    path = run_dir / "connector.json"
    path.write_text(json.dumps({"mcpServers": {CONNECTOR_NAME: {
        "type": "http", "url": url, "headers": {"Authorization": "Bearer ${%s}" % K.TOKEN_ENV}}}}), encoding="utf-8")
    return path


def agent_command(prompt: str, plugin: Path | None, model: str, run_dir: Path, *, resume: str = "", keep: bool = False,
                  connector: Path | None = None) -> list[str]:
    """One agent turn. A conversation keeps its session so the next turn can resume it.

    With ``connector`` the agent gets the Handbuilt connector and web search only, and no plugin."""
    isolation = [flag for flag in J.ISOLATION if not (keep and flag == "--no-session-persistence")]
    if connector:
        isolation = ["--strict-mcp-config", "--mcp-config", str(connector), "--setting-sources", "",
                     *(["--no-session-persistence"] if not keep else [])]
        reach = ["--tools", CONNECTOR_BUILTINS, "--allowedTools", f"{CONNECTOR_BUILTINS},mcp__{CONNECTOR_NAME}"]
    else:
        reach = ["--plugin-dir", str(plugin), "--add-dir", str(run_dir), "--allowedTools", TOOLS]
    command = [J.CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose", *reach,
               "--permission-mode", "dontAsk", "--settings", settings(run_dir), *isolation]
    if resume:
        command += ["--resume", resume]
    if model:
        command += ["--model", model]
    return command


# Paid services a pastor may have set up. An eval must never spend on them.
PAID_KEYS = ("OPENAI_API_KEY", "RECRAFT_API_KEY", "GEMINI_API_KEY")


def run_environment(run_dir: Path) -> dict:
    """A pastor's computer with Handbuilt installed and no image services set up.

    Handbuilt keeps saved image keys in its support folder, beside the managed
    runtime. Each run gets its own support folder that links only the runtime.
    """
    sys.path.insert(0, str(LABS))
    from tools.handbuilt_runtime import default_runtime_root  # noqa: PLC0415
    real = default_runtime_root()
    support = run_dir / "support"
    support.mkdir(exist_ok=True)
    runtime = support / real.name
    if not runtime.exists():
        runtime.symlink_to(real, target_is_directory=True)
    env = {key: value for key, value in os.environ.items() if key not in PAID_KEYS}
    env["HANDBUILT_RUNTIME_HOME"] = str(runtime)
    return env


# Seconds a turn may keep running after the agent's answer, so background work it started
# (a re-render) can finish. A preview server stops on its own after an hour; this ends sooner.
AFTER_ANSWER = 300


def agent_turn(command: list[str], run_dir: Path, transcript: Path, timeout: int) -> tuple[dict, bool]:
    """One agent turn. It ends at the agent's answer, so a preview server or other
    background process the agent left running cannot turn finished work into a timeout."""
    deadline = time.monotonic() + timeout
    answered_at = None
    with transcript.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(command, cwd=run_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=run_environment(run_dir), text=True, encoding="utf-8", errors="replace",
                                   start_new_session=True)
        lines: "queue.Queue[str | None]" = queue.Queue()

        def pump() -> None:
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        timed_out = False
        while True:
            now = time.monotonic()
            if now > deadline:
                timed_out = True
                break
            if answered_at and now - answered_at > AFTER_ANSWER:
                break
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                break
            sink.write(line)
            if '"type":"result"' in line.replace(" ", ""):
                answered_at = time.monotonic()
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    return read_stream(transcript), timed_out


def converse(case: C.Case, prompt: str, plugin: Path | None, model: str, judge_model: str, run_dir: Path,
             connector: Path | None = None) -> bool:
    """Run the agent, letting the stand-in pastor answer until the work is done. Returns timed_out."""
    history = [{"who": "pastor", "text": prompt}]
    stream, timed_out = agent_turn(agent_command(prompt, plugin, model, run_dir, keep=bool(case.persona), connector=connector),
                                   run_dir, run_dir / "transcript-00.jsonl", case.timeout)
    history.append({"who": "assistant", "text": str(stream["final"].get("result") or "")})
    for number in range(1, case.max_exchanges + 1 if case.persona else 1):
        session = stream["final"].get("session_id") or stream["init"].get("session_id")
        if timed_out or not session:
            break
        answer = P.respond(case.persona, history[:-1], history[-1]["text"], judge_model, run_dir)
        if answer.get("error"):
            history.append({"who": "note", "text": f"The stand-in pastor could not answer: {answer['error']}"})
            break
        if answer["done"]:
            break
        history.append({"who": "pastor", "text": answer["reply"]})
        stream, timed_out = agent_turn(agent_command(answer["reply"], plugin, model, run_dir, resume=session, keep=True, connector=connector),
                                       run_dir, run_dir / f"transcript-{number:02d}.jsonl", case.timeout)
        if not timed_out and not stream["final"].get("num_turns"):
            # A resume can end at once on a leftover background notice; send the message again.
            stream, timed_out = agent_turn(agent_command(answer["reply"], plugin, model, run_dir, resume=session, keep=True, connector=connector),
                                           run_dir, run_dir / f"transcript-{number:02d}b.jsonl", case.timeout)
        history.append({"who": "assistant", "text": str(stream["final"].get("result") or "")})
    with (run_dir / "transcript.jsonl").open("w", encoding="utf-8") as whole:
        for part in sorted(run_dir.glob("transcript-*.jsonl")):
            whole.write(part.read_text(encoding="utf-8", errors="replace"))
    P.write_conversation(run_dir / "conversation.md", history)
    return timed_out


def read_stream(path: Path) -> dict:
    """Summarize a run from its transcript. Anything malformed stays visible."""
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    results = [e for e in events if e.get("type") == "result"]
    final = dict(results[-1]) if results else {}
    if len(results) > 1:
        # A resumed session reports its running cost, so the whole cost is the largest one.
        final["total_cost_usd"] = max(e.get("total_cost_usd") or 0 for e in results)
        final["num_turns"] = sum(e.get("num_turns") or 0 for e in results)
    # A turn that ended with an empty answer does not replace the last real one.
    spoken = [e for e in results if str(e.get("result") or "").strip()]
    if spoken and not str(final.get("result") or "").strip():
        final["result"] = spoken[-1]["result"]
    uses, seen = [], []
    for event in events:
        # Some system events carry a plain string message, such as a denied tool.
        message = event.get("message")
        for block in (message.get("content") if isinstance(message, dict) else None) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses.append({"name": block.get("name"), "input": block.get("input")})
            elif block.get("type") == "tool_result":
                seen.append(json.dumps(block.get("content"), ensure_ascii=False))
    return {"init": init, "final": final, "uses": uses, "seen": "\n".join(seen)}


def connector_problems(stream: dict) -> list[str]:
    """The connector path must look like a pastor's Claude: the connector, no plugin, no local files."""
    problems = []
    init = stream["init"]
    if not init:
        return ["the run never started"]
    servers = [(s.get("name"), s.get("status")) for s in init.get("mcp_servers") or []]
    if servers != [(CONNECTOR_NAME, "connected")]:
        problems.append(f"the connector was not the only connected server: {servers}")
    plugins = [str(item.get("path", "")) for item in init.get("plugins") or [] if item.get("path") != "builtin"]
    if plugins:
        problems.append(f"plugins were loaded: {plugins}")
    local = sorted({use["name"] for use in stream["uses"] if use["name"] in LOCAL_TOOLS})
    if local:
        problems.append(f"local tools were used: {local}")
    return problems


def isolation_problems(stream: dict, plugin: Path | None) -> list[str]:
    if plugin is None:
        return connector_problems(stream)
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


def judge_counts(judged: dict) -> dict:
    passed = total = 0
    failures, ungraded, gaps = [], [], []
    for name, verdict in judged.items():
        if name in {"sources", "recheck"} or not isinstance(verdict, dict) or "status" not in verdict:
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


def one_run(case_name: str, number: int, out: Path, model: str, judge_model: str, connector_url: str = "") -> dict:
    case = CASES[case_name]
    run_dir = out / f"{case_name}-{number}"
    run_dir.mkdir(parents=True)
    church = run_dir / "riverbend"
    case.seed(church)
    if connector_url:
        return connector_run(case, number, run_dir, model, judge_model, connector_url)
    plugin = run_dir / "plugin"
    stage_plugin(plugin)
    started = time.time()
    prompt = case.prompt(church) if callable(case.prompt) else case.prompt.format(church=church)
    timed_out = converse(case, prompt, plugin, model, judge_model, run_dir)
    return grade_run(case_name, number, run_dir, judge_model, seconds=round(time.time() - started), timed_out=timed_out)


def connector_run(case: C.Case, number: int, run_dir: Path, model: str, judge_model: str, url: str) -> dict:
    """The same case through the connector: copy the church up, run, copy it back, grade unchanged."""
    church = run_dir / "riverbend"
    prefix = f"evals/{run_dir.parent.name}/{run_dir.name}"
    (run_dir / "via.json").write_text(json.dumps({"via": "connector", "url": url, "prefix": prefix}), encoding="utf-8")
    started = time.time()
    try:
        connector = K.Connector.from_env(url)
        missing = connector.missing_folder_tools()
        if missing:
            raise K.ConnectorError(f"the connector has no {', '.join(missing)} tool")
        K.push_folder(connector, church, prefix)
    except K.ConnectorError as exc:
        return setup_failed(case.name, number, run_dir, f"Setup: {exc}")
    prompt = case.prompt(church) if callable(case.prompt) else case.prompt.format(church=f"the Handbuilt church folder {prefix}")
    timed_out = converse(case, prompt, None, model, judge_model, run_dir, connector=connector_config(run_dir, url))
    try:
        shutil.rmtree(church)
        church.mkdir()
        K.pull_folder(connector, prefix, church)
    except K.ConnectorError as exc:
        return setup_failed(case.name, number, run_dir, f"Collect: {exc}", seconds=round(time.time() - started))
    return grade_run(case.name, number, run_dir, judge_model, seconds=round(time.time() - started), timed_out=timed_out)


def setup_failed(case: str, number: int, run_dir: Path, problem: str, *, seconds: int = 0) -> dict:
    """A run that could not be set up or collected. It fails, and says why, without grading."""
    record = {"case": case, "run": number, "via": "connector", "seconds": seconds, "timed_out": False,
              "setup_problem": problem, "isolation_problems": [], "checks_passed": 0, "checks_total": 0,
              "failed_checks": [], "judges": judge_counts({}), "quotes": None, "clean": False}
    (run_dir / "result.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    return record


def grade_run(case: str, number: int, run_dir: Path, judge_model: str, *, seconds: int, timed_out: bool) -> dict:
    """Grade the files one run left. A corrected grader can reread them without a new agent run."""
    via = run_dir / "via.json"
    plugin = None if via.exists() else run_dir / "plugin"
    church = run_dir / "riverbend"
    stream = read_stream(run_dir / "transcript.jsonl")
    final = str(stream["final"].get("result") or "")
    (run_dir / "final-message.md").write_text(final, encoding="utf-8")
    problems = isolation_problems(stream, plugin)
    fetch = PageText()
    conversation = (run_dir / "conversation.md").read_text(encoding="utf-8") if (run_dir / "conversation.md").exists() else ""
    spec = CASES[case]
    graded = spec.grade(church, stream=stream, fetch=fetch)
    judged = spec.judges(church, graded, final, conversation, judge_model, run_dir)
    counts = judge_counts(judged)
    failed_checks = [c for c in graded["checks"] if not c["passed"]]
    record = {"case": case, "run": number, "via": "plugin" if plugin else "connector", "seconds": seconds, "timed_out": timed_out,
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
        if r.get("setup_problem"):
            rows.append(f"| {r['case']} {r['run']} | no | {r['setup_problem']} | | | | {r['seconds'] // 60} |")
            continue
        rows.append(f"| {r['case']} {r['run']} | {'yes' if r['clean'] else 'no'} | {r['checks_passed']}/{r['checks_total']} "
                    f"| {r['judges']['passed']}/{r['judges']['total']} "
                    f"| {claims['supported']} / {claims['unsupported']} / {claims['not_in_excerpt']} "
                    f"| {len(quotes.get('unfound', []))} | {r['seconds'] // 60} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=(*CASES, "all"), action="append", help="Repeat to choose several. Default: all.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default="", help="Agent model. Blank uses the account default.")
    parser.add_argument("--judge-model", default="sonnet")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--via", choices=("plugin", "connector"), default="plugin",
                        help="plugin: Claude Code with the plugin (today). connector: only the Handbuilt connector.")
    parser.add_argument("--connector-url", default=os.environ.get(K.URL_ENV, ""),
                        help=f"The connector's address. Its token comes from {K.TOKEN_ENV}.")
    parser.add_argument("--regrade", action="store_true", help="Grade the runs already in --out again. No agent runs.")
    args = parser.parse_args(argv)
    out = outside_repo(args.out)
    url = args.connector_url if args.via == "connector" else ""
    if args.via == "connector" and not url:
        raise SystemExit(f"--via connector needs --connector-url or {K.URL_ENV}.")
    chosen = list(CASES) if not args.case or "all" in args.case else args.case
    if args.regrade:
        earlier = json.loads((out / "results.json").read_text(encoding="utf-8"))
        records = [grade_run(r["case"], r["run"], out / f"{r['case']}-{r['run']}", args.judge_model,
                             seconds=r["seconds"], timed_out=r["timed_out"])
                   if r["case"] in chosen and not r.get("setup_problem") else r
                   for r in earlier]
        return report(out, records)
    if out.exists():
        raise SystemExit("Choose a new results folder; a rerun never reuses old work.")
    out.mkdir(parents=True)
    jobs = [(case, n) for case in chosen for n in range(1, args.runs + 1)]
    with futures.ThreadPoolExecutor(args.parallel) as pool:
        records = list(pool.map(lambda job: one_run(job[0], job[1], out, args.model, args.judge_model, url), jobs))
    return report(out, records)


def report(out: Path, records: list[dict]) -> int:
    (out / "results.json").write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")
    summary = table(records)
    (out / "summary.md").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    return 0 if all(r["clean"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
