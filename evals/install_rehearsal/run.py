"""Rehearse a pastor's first hour: install the plugin, then set up a church.

A real agent on a clean computer gets the message a pastor pastes from
INSTALL.md. It has to install Handbuilt, turn on updates, and hand off. A new
session then gets "Set up my Church Command Center" and works with a stand-in
pastor for an invented church. Nothing is staged for the agent: Claude starts
with no plugin, no settings and no Handbuilt folder.

This runs on a throwaway computer (a CI runner). The agent may install
software and change settings there, as it would for a pastor, so the script
refuses to run anywhere else unless told to.

    handbuilt-python evals/install_rehearsal/run.py --out <folder> \
        --source https://github.com/<owner>/<repo>.git#<ref>

It needs a signed-in `claude` (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY)
and network access.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABS = HERE.parents[1]
sys.path.insert(0, str(LABS / "evals" / "finished_work"))
sys.path.insert(0, str(LABS))

import case_onboarding as O  # noqa: E402
import judges as J  # noqa: E402
import pastor as P  # noqa: E402
from run import read_stream  # noqa: E402

PLUGIN = "handbuilt-church-labs@handbuilt-church-labs"
TOOLS = "Bash,PowerShell,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Skill"

INSTALL_MESSAGE = """Please install the Handbuilt Church Labs plugin from
{source}
and turn on automatic updates so I always have the newest version.
Follow its INSTALL.md, and explain each step to me."""

INSTALL_PERSONA = """You are a parish priest with no technical background, installing Handbuilt Church Labs with an
AI assistant's help. You have never opened a terminal. You say yes to a reasonable step when asked. You cannot
type commands, and you say so plainly if asked to. If you are told to quit and reopen the app, or to start a new
session, say you will do that next, and treat the installation as finished. You do not ask for anything beyond
getting Handbuilt installed."""

INSTALL_RUBRIC = [
    {"id": "says_it_is_installed", "kind": "tell", "text": "Says plainly that Handbuilt is installed."},
    {"id": "says_updates_are_on", "kind": "tell", "text": "Says automatic updates are turned on."},
    {"id": "gives_the_next_step", "kind": "tell",
     "text": "Tells the pastor the one next step: start a new session and ask to set up the Church Command Center."},
    {"id": "no_commands_for_the_pastor", "kind": "avoid",
     "text": "Gives the pastor a command line to type or run, or tells them to install Python."},
    {"id": "church_language", "kind": "avoid",
     "text": "Leaves technical terms such as marketplace, JSON, PATH or repository unexplained for a pastor."},
]

INSTALL_CONTEXT = ("A pastor with no technical background pasted an install request. The assistant did the installing. "
                   "The pastor can only click, approve and read. Naming the app's own buttons is fine. The pastor's request "
                   "named a branch of the plugin to install, so saying which branch was installed is fine.")


def environment(run: Path) -> dict:
    """A computer where Claude and Handbuilt have never been set up."""
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(run / "claude-config")
    env["HANDBUILT_RUNTIME_HOME"] = str(run / "handbuilt-runtime")
    for paid in ("OPENAI_API_KEY", "RECRAFT_API_KEY", "GEMINI_API_KEY"):
        env.pop(paid, None)
    return env


def turn(prompt: str, run: Path, name: str, env: dict, model: str, timeout: int, resume: str = "") -> tuple[dict, bool]:
    """One agent turn in the pastor's home folder. Returns (summary, timed_out)."""
    home = run / "home"
    home.mkdir(exist_ok=True)
    # The message goes in on standard input. On Windows Claude Code is a .cmd
    # file, and a message with line breaks is cut short when passed as an argument.
    command = [J.CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
               "--allowedTools", TOOLS, "--permission-mode", "bypassPermissions",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--add-dir", str(run)]
    if resume:
        command += ["--resume", resume]
    if model:
        command += ["--model", model]
    transcript = run / f"{name}.jsonl"
    timed_out = False
    with transcript.open("w", encoding="utf-8") as out:
        try:
            subprocess.run(command, input=prompt, text=True, encoding="utf-8", errors="replace", cwd=home, env=env,
                           stdout=out, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            timed_out = True
    stream = read_stream(transcript)
    if not timed_out and not str(stream["final"].get("result") or "").strip():
        # Say why in the job log, without the credential.
        raw = transcript.read_text(encoding="utf-8", errors="replace")
        for hidden in (env.get("CLAUDE_CODE_OAUTH_TOKEN"), env.get("ANTHROPIC_API_KEY")):
            if hidden:
                raw = raw.replace(hidden, "[credential removed]")
        print(f"The agent turn {name} produced no answer. Its output began:\n{raw[:600]}", flush=True)
    return stream, timed_out


def converse(first: str, persona: str, run: Path, name: str, env: dict, model: str, judge_model: str,
             timeout: int, exchanges: int) -> tuple[list[dict], dict, bool]:
    history = [{"who": "pastor", "text": first}]
    stream, timed_out = turn(first, run, f"{name}-00", env, model, timeout)
    history.append({"who": "assistant", "text": str(stream["final"].get("result") or "")})
    for number in range(1, exchanges + 1):
        session = stream["final"].get("session_id") or stream["init"].get("session_id")
        if timed_out or not session:
            break
        answer = P.respond(persona, history[:-1], history[-1]["text"], judge_model, run)
        if answer.get("error"):
            history.append({"who": "note", "text": f"The stand-in pastor could not answer: {answer['error']}"})
            break
        if answer["done"]:
            break
        history.append({"who": "pastor", "text": answer["reply"]})
        stream, timed_out = turn(answer["reply"], run, f"{name}-{number:02d}", env, model, timeout, resume=session)
        history.append({"who": "assistant", "text": str(stream["final"].get("result") or "")})
    P.write_conversation(run / f"{name}-conversation.md", history)
    return history, stream, timed_out


def claude_json(arguments: list[str], env: dict) -> object:
    done = subprocess.run([J.CLAUDE, *arguments], env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)
    text = done.stdout.strip()
    # The whole output is the JSON; a notice may come before it.
    for start in sorted({i for i in (text.find("["), text.find("{")) if i >= 0}):
        try:
            return json.loads(text[start:])
        except ValueError:
            continue
    return {"error": (done.stdout + done.stderr)[-500:]}


def check(out: list[dict], name: str, passed: bool, detail: str = "") -> bool:
    out.append({"id": name, "passed": bool(passed), "detail": detail if not passed else ""})
    return bool(passed)


def grade_install(run: Path, env: dict, history: list[dict]) -> list[dict]:
    out: list[dict] = []
    wanted = json.loads((LABS / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    listed = claude_json(["plugin", "list", "--json"], env)
    entries = listed if isinstance(listed, list) else []
    mine = next((e for e in entries if str(e.get("id") or e.get("name") or "").startswith("handbuilt-church-labs")), None)
    check(out, "plugin_installed", mine is not None, json.dumps(listed)[:300])
    if mine:
        check(out, "plugin_enabled", mine.get("enabled") is not False, json.dumps(mine)[:300])
        check(out, "version_is_the_candidate", str(mine.get("version")) == wanted, f"{mine.get('version')} installed; {wanted} expected")
    plugin = Path(env["CLAUDE_CONFIG_DIR"]) / "plugins" / "cache" / "handbuilt-church-labs" / "handbuilt-church-labs" / wanted
    if check(out, "plugin_files_present", (plugin / "tools" / "claude_updates.py").is_file(), str(plugin)):
        launcher = plugin / "bin" / ("handbuilt-python.cmd" if os.name == "nt" else "handbuilt-python")
        status = subprocess.run([str(launcher), str(plugin / "tools" / "claude_updates.py"), "status"], env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        try:
            report = json.loads(status.stdout)
        except ValueError:
            report = {"status": "unreadable", "detail": (status.stdout + status.stderr)[-300:]}
        check(out, "automatic_updates_on", report.get("auto_update_on") is True and report.get("desktop_updates_allowed") is True,
              json.dumps(report)[:300])
    said = "\n".join(t["text"] for t in history if t["who"] == "assistant")
    check(out, "never_told_to_install_python", not re.search(r"(?i)\b(install|download)\b[^.\n]{0,40}\bpython\b[^.\n]{0,40}\b(yourself|you'?ll need|please|python\.org)", said), "")
    check(out, "final_message_present", bool(history[-1]["text"].strip()) if history else False, "")
    # INSTALL.md limits the last message to three plain things. A recap of the workings
    # is what a pastor on camera should never have to read.
    last = history[-1]["text"] if history else ""
    workings = sorted(set(m.lower() for m in re.findall(
        r"(?i)`[^`]+`|settings\.json|\bbranch\b|\bpython\b|\bscript\b|\bgithub\b|\brepository\b|\bbackup\b", last)))
    check(out, "last_message_leaves_out_the_workings", not workings, ", ".join(workings)[:200])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", required=True, help="Git address of the plugin, with #ref for a candidate.")
    parser.add_argument("--model", default="")
    parser.add_argument("--judge-model", default="sonnet")
    parser.add_argument("--on-this-computer", action="store_true",
                        help="Run outside CI. The agent may install software and change settings here.")
    args = parser.parse_args(argv)
    if not (os.environ.get("CI") or args.on_this_computer):
        parser.error("This lets an agent install software freely. Run it on a CI runner, or pass --on-this-computer.")
    run = args.out.resolve()
    if run.exists() and any(run.iterdir()):
        parser.error(f"{run} is not empty")
    run.mkdir(parents=True, exist_ok=True)
    env = environment(run)
    started = time.time()

    # Act one: the pastor pastes the install request into a clean Claude.
    history, _stream, timed_out = converse(INSTALL_MESSAGE.format(source=args.source), INSTALL_PERSONA, run, "install",
                                           env, args.model, args.judge_model, timeout=1500, exchanges=6)
    if re.search(r"(?i)failed to authenticate|invalid bearer token|not logged in", history[-1]["text"]):
        print("Claude rejected the credential, so nothing was rehearsed:", history[-1]["text"][:200])
        return 2
    install_checks = grade_install(run, env, history)
    install_judge = J.rubric_judge("Grade this message an assistant left for a pastor after installing a plugin for them.",
                                   INSTALL_RUBRIC, history[-1]["text"], INSTALL_CONTEXT, args.judge_model, run)

    # Act two: a new session, as the handoff asks, and a stand-in pastor for an invented church.
    setup_checks: list[dict] = []
    setup_judges: dict = {}
    setup_timed_out = False
    if all(c["passed"] for c in install_checks if c["id"] in {"plugin_installed", "plugin_files_present"}):
        church = O.seed(run / O.FOLDER)
        os.environ["HANDBUILT_RUNTIME_HOME"] = env["HANDBUILT_RUNTIME_HOME"]
        setup_history, stream, setup_timed_out = converse(O.prompt(church), O.PERSONA, run, "setup", env, args.model,
                                                          args.judge_model, timeout=2400, exchanges=12)
        # The rehearsal's own folders and records sit beside the church folder. Anything
        # else there was left by the agent, such as a download it did not clean up.
        O.RUN_FILES = set(O.RUN_FILES) | {"claude-config", "handbuilt-runtime", "home", "workflows"} | {
            item.name for item in run.iterdir() if re.fullmatch(r"(install|setup)-(\d+\.jsonl|conversation\.(md|json))", item.name)}
        graded = O.grade(church, stream=stream)
        setup_checks = graded["checks"]
        conversation = (run / "setup-conversation.md").read_text(encoding="utf-8")
        setup_judges = O.judges(church, graded, setup_history[-1]["text"], conversation, args.judge_model, run)

    failed = [c for c in (*install_checks, *setup_checks) if not c["passed"]]
    record = {
        "source": args.source, "system": sys.platform, "minutes": round((time.time() - started) / 60),
        "install": {"timed_out": timed_out, "checks": install_checks, "judge": install_judge},
        "setup": {"ran": bool(setup_checks), "timed_out": setup_timed_out, "checks": setup_checks, "judges": setup_judges},
        "failed_checks": failed,
        "passed": not failed and not timed_out and not setup_timed_out and bool(setup_checks),
    }
    (run / "result.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Install: {sum(c['passed'] for c in install_checks)} of {len(install_checks)} checks")
    print(f"Setup:   {sum(c['passed'] for c in setup_checks)} of {len(setup_checks)} checks" if setup_checks
          else "Setup:   did not run, because the plugin was not installed")
    for item in failed:
        print(f"  failed: {item['id']}: {item['detail']}")
    print("Result:", "passed" if record["passed"] else "did not pass")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
