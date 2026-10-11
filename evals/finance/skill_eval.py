#!/usr/bin/env python3
"""Run finance onboarding's first stage with Claude on an eval church, and grade what it wrote.

The scripts evals (score.py) check the arithmetic. This checks the part a model does: what
Claude tells a pastor about messy books. Claude runs the finance-onboarding skill as written,
reading QuickBooks only through a read-only stand-in connector that serves the church's
synthetic books (quickbooks_stub.py). Nobody is at the keyboard, so the run writes its
questions for the pastor and treasurer to a file instead of asking them.

    # one run: writes OUT/<church>/ and OUT/<church>-run.json
    python3 evals/finance/skill_eval.py run cedar_hollow --model claude-opus-5-5 --out ~/evals/2026-10-12

    # grade it: figures checked against the books, the rubric read by a judge model
    python3 evals/finance/skill_eval.py grade ~/evals/2026-10-12/cedar_hollow --judge claude-opus-5-5

    # every church, on each model, then one table
    python3 evals/finance/skill_eval.py all --model claude-sonnet-5-5 --model claude-opus-5-5 --out DIR
    python3 evals/finance/skill_eval.py table DIR

Needs Claude Code (`claude`) signed in or ANTHROPIC_API_KEY set, so it runs on a computer with a
model key, not in CI. Runs and grades are test results: keep them outside this repository.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABS = HERE.parents[1]
sys.path.insert(0, str(HERE))
import books as B  # noqa: E402
import score  # noqa: E402
from churches import ALL  # noqa: E402

TODAY = "2026-09-10"
BUDGET_USD = 5.0

PROMPT = """Set up this church's finances with the handbuilt-church-labs:finance-onboarding skill, stage 1
(Look) only. Follow its SKILL.md exactly, as you would on the pastor's computer.

- Today is {today}. The church folder is the current directory.
- QuickBooks is connected through the QuickBooks connector tools. They only read.
- Nobody is at the keyboard. Wherever the skill says to ask the pastor or the treasurer, add the
  question, with its options if it has any, to finance/onboarding/questions.json (a JSON list of
  objects with "for", "question" and "why") and carry on with what you can do without the answer.
  Do not invent an answer, a fact, or a figure the books do not show.
- Finish when finance/finance-overview.md is written for the pastor. Do not mark the stage done.
"""

JUDGE_PROMPT = """You are grading what an AI assistant wrote for a pastor about their church's books.
The pastor is not an accountant. Below are the assistant's overview for the pastor, its questions for the
pastor and treasurer, and a rubric written by someone who knows the true state of these (synthetic) books.

For each rubric item, decide whether the writing meets it. "tell" items pass when the overview says it
plainly enough that the pastor would understand. "ask" items pass when the overview or the questions ask
it. "avoid" items pass when the writing does NOT do the thing described. Quote the words that decided it
(an empty quote when nothing applies).

Then rate clarity from 1 to 5: could this pastor say, after one reading, whether the church can pay its
bills, which way the year is going, and what to ask the treasurer? 5 means yes to all three, in plain words.

Answer with JSON only, no prose:
{{"items": [{{"id": "...", "pass": true, "quote": "..."}}], "clarity": 4, "clarity_reason": "..."}}

RUBRIC
{rubric}

OVERVIEW (finance/finance-overview.md)
{overview}

QUESTIONS (finance/onboarding/questions.json)
{questions}
"""


# --- the church folder ---------------------------------------------------------------------

def church_folder(cid: str, root: Path) -> Path:
    """A church folder as onboarding leaves it: identity filled in, no finance work yet, no pulls."""
    c = ALL[cid].CHURCH
    shutil.copytree(LABS / "scaffold/church-folder", root, dirs_exist_ok=True)
    text = (root / "church.yaml").read_text()
    text = re.sub(r'(?m)^  name: ""', f'  name: "{c["name"]}"', text, count=1)
    text = re.sub(r'(?m)^  tradition: ""', f'  tradition: "{c["tradition"]}"', text, count=1)
    text = re.sub(r'(?m)^    label: ""', f'    label: "{c["governing_body"]}"', text, count=1)
    (root / "church.yaml").write_text(text)
    return root


def run(cid: str, model: str, out: Path, budget: float = BUDGET_USD) -> dict:
    root = church_folder(cid, out / cid)
    log = out / f"{cid}-quickbooks-calls.jsonl"
    mcp = {"mcpServers": {"Intuit_QuickBooks": {
        "command": sys.executable, "args": [str(HERE / "quickbooks_stub.py"), cid],
        "env": {"EVAL_QBO_LOG": str(log)}}}}
    command = ["claude", "-p", PROMPT.format(today=TODAY), "--plugin-dir", str(LABS), "--model", model,
               "--output-format", "json", "--max-budget-usd", str(budget),
               "--permission-mode", "bypassPermissions", "--mcp-config", json.dumps(mcp), "--strict-mcp-config"]
    began = time.monotonic()
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60 * 60)
    result = json.loads(done.stdout) if done.stdout.strip().startswith("{") else {"error": done.stderr[-2000:]}
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    summary = {"church": cid, "model": model, "cost_usd": result.get("total_cost_usd"),
               "turns": result.get("num_turns"), "wall_seconds": round(time.monotonic() - began, 1),
               "error": result.get("error") or (result.get("result") if result.get("is_error") else None),
               "final_text": (result.get("result") or "")[-1500:], "quickbooks_calls": calls}
    (out / f"{cid}-run.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# --- grading -------------------------------------------------------------------------------------

def known_figures(cid: str) -> set[int]:
    """Every figure the books can support: balances, period totals, results, and the truth figures."""
    c = ALL[cid].CHURCH
    books = B.Books(c)
    y, m = books.last
    _, bal = books.balances(books.last)
    figures = {round(v) for vals in bal.values() for v in vals}
    windows = [((y - 1, m + 1) if m < 12 else (y, 1), books.last), ((y, 1), books.last)]
    windows += [((yy, 1), (yy, 12)) for yy in range(y - 4, y)]
    for start, end in windows:
        tot = books.period_totals(start, end)
        figures |= {round(v) for v in tot.values()}
        side = {a["name"]: a["section"] for a in c["pl"]}
        inc = sum(v for k, v in tot.items() if side[k] in B.INCOME_SIDE)
        exp = sum(v for k, v in tot.items() if side[k] not in B.INCOME_SIDE)
        figures |= {round(inc), round(exp), round(inc - exp)}
        heads = {}
        for a in c["pl"]:
            for h in a.get("under", []):
                heads[h] = heads.get(h, 0) + tot[a["name"]]
        figures |= {round(v) for v in heads.values()}
    t = score.truth_figures(ALL[cid])
    figures |= {t["cash"], t["income_12m"], t["spending_12m"], t["result_12m"]}
    return {abs(f) for f in figures}


def supported(value: int, known: set[int]) -> bool:
    """A figure is supported when it is a known figure, or one rounded to the nearest 10, 100 or 1,000."""
    v = abs(value)
    if any(abs(v - k) <= 1 for k in known):
        return True
    for unit in (10, 100, 1000):
        if v % unit == 0 and any(abs(round(k / unit) * unit - v) < 1 for k in known):
            return True
    return False


def figures_in(text: str) -> list[int]:
    out = []
    for m in re.finditer(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)\s*([kKmM])?", text):
        v = float(m.group(1).replace(",", ""))
        v *= {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)
        out.append(round(v))
    return out


def rubric(cid: str) -> list[dict]:
    t = score.truth_figures(ALL[cid])
    words = {"cash": f"${abs(t['cash']):,}", "result": f"${abs(t['result_12m']):,}"}
    items = []
    for kind in ("tell", "ask", "avoid"):
        for i, text in enumerate(ALL[cid].TRUTH["skill"].get(kind, []), 1):
            items.append({"id": f"{kind}-{i}", "kind": kind, "text": text.format(**words)})
    return items


def judge(prompt: str, model: str) -> dict:
    done = subprocess.run(["claude", "-p", prompt, "--model", model, "--output-format", "json",
                           "--tools", ""], capture_output=True, text=True, timeout=600)
    outer = json.loads(done.stdout) if done.stdout.strip().startswith("{") else {}
    text = outer.get("result", "")
    found = re.search(r"\{.*\}", text, re.S)
    return {**(json.loads(found.group(0)) if found else {"error": text[-500:] or done.stderr[-500:]}),
            "judge_cost_usd": outer.get("total_cost_usd")}


def grade(folder: Path, judge_model: str | None) -> dict:
    cid = folder.name
    overview_path = folder / "finance/finance-overview.md"
    questions_path = folder / "finance/onboarding/questions.json"
    overview = overview_path.read_text() if overview_path.exists() else ""
    questions = questions_path.read_text() if questions_path.exists() else "[]"
    known = known_figures(cid)
    figures = figures_in(overview)
    unsupported = sorted({f for f in figures if f >= 100 and not supported(f, known)})
    items = rubric(cid)
    result = {"church": cid, "overview_written": bool(overview),
              "used_the_scripts": (folder / "finance/onboarding/findings.json").exists(),
              "figures": len(figures), "unsupported_figures": unsupported, "rubric": items}
    if judge_model and overview:
        listed = "\n".join(f"- {i['id']} ({i['kind']}): {i['text']}" for i in items)
        verdict = judge(JUDGE_PROMPT.format(rubric=listed, overview=overview, questions=questions), judge_model)
        by_id = {v.get("id"): v for v in verdict.get("items", [])}
        for i in items:
            i["pass"], i["quote"] = by_id.get(i["id"], {}).get("pass"), by_id.get(i["id"], {}).get("quote")
        result.update({"judge": judge_model, "clarity": verdict.get("clarity"),
                       "clarity_reason": verdict.get("clarity_reason"), "judge_cost_usd": verdict.get("judge_cost_usd"),
                       "judge_error": verdict.get("error")})
    result["rubric_passed"] = sum(1 for i in items if i.get("pass") is True)
    (folder.parent / f"{cid}-grade.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def table(out: Path) -> str:
    lines = ["| Church | Model | Rubric | Clarity | Unsupported figures | Cost | Minutes |", "|---|---|---|---|---|---|---|"]
    for model_dir in sorted(p for p in out.iterdir() if p.is_dir()):
        for g in sorted(model_dir.glob("*-grade.json")):
            gr = json.loads(g.read_text())
            r = json.loads((model_dir / f"{gr['church']}-run.json").read_text())
            lines.append(f"| {gr['church']} | {r['model']} | {gr['rubric_passed']}/{len(gr['rubric'])} | "
                         f"{gr.get('clarity', '')} | {len(gr['unsupported_figures'])} | "
                         f"${(r['cost_usd'] or 0):.2f} | {r['wall_seconds'] / 60:.1f} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("church", choices=list(ALL))
    r.add_argument("--model", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--budget", type=float, default=BUDGET_USD)
    g = sub.add_parser("grade")
    g.add_argument("folder", type=Path)
    g.add_argument("--judge", help="model that reads the rubric; leave out to check figures only")
    a = sub.add_parser("all")
    a.add_argument("--model", action="append", required=True)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--judge", default="claude-opus-5-5")
    a.add_argument("--church", action="append", choices=list(ALL))
    t = sub.add_parser("table")
    t.add_argument("out", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        args.out.mkdir(parents=True, exist_ok=True)
        print(json.dumps({k: v for k, v in run(args.church, args.model, args.out.resolve(), args.budget).items()
                          if k != "quickbooks_calls"}, indent=1))
    elif args.cmd == "grade":
        print(json.dumps(grade(args.folder.resolve(), args.judge), indent=1))
    elif args.cmd == "all":
        for model in args.model:
            out = (args.out / model).resolve()
            out.mkdir(parents=True, exist_ok=True)
            for cid in args.church or list(ALL):
                run(cid, model, out)
                grade(out / cid, args.judge)
        print(table(args.out))
    else:
        print(table(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
