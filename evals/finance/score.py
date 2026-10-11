#!/usr/bin/env python3
"""Score the finance scripts against the eval churches. No model, no network, no cost.

    python3 evals/finance/score.py                 # every church, a readable table
    python3 evals/finance/score.py --json          # the same, as JSON
    python3 evals/finance/score.py cedar_hollow    # one church

For each church this writes the church folder and the QuickBooks pulls the skill would make,
runs the same operations the skill runs (finance onboarding `look`, finance report `setup` and
`build`), and checks each result against what a careful bookkeeper knows about those books
(the church's TRUTH).

A check marked with a gap is a known weakness: it is expected to fail today. When one starts
passing, the test suite says so, so the gap note comes out and the check guards the fix.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import books as B  # noqa: E402
from churches import ALL  # noqa: E402

ONBOARDING = ROOT / "skills/finance-onboarding/scripts/finance_onboarding.py"
REPORT = ROOT / "skills/finance-report/scripts/finance_report.py"
MONEY = re.compile(r"(-)?\$([0-9][0-9,]*)")


def money_values(text):
    return [(-1 if m.group(1) else 1) * int(m.group(2).replace(",", "")) for m in MONEY.finditer(text or "")]


# --- the church folder and its pulls ---------------------------------------------------

def write_church(module, root: Path) -> dict:
    """Lay out the church folder and every pull. Returns the pull paths."""
    c = module.CHURCH
    books = B.Books(c)
    root.mkdir(parents=True, exist_ok=True)
    (root / "church.yaml").write_text(
        f"church:\n  name: {c['name']}\n  tradition: {c['tradition'] or 'none'}\n"
        f"leadership:\n  governing_body:\n    label: {c['governing_body']}\n    officers:\n"
        "    - name: Pat Example\n      role: Treasurer\n")
    pulls = root / "pulls"
    pulls.mkdir(exist_ok=True)
    last = books.last
    y, m = last
    start12 = (y - 1, m + 1) if m < 12 else (y, 1)
    paths = {}

    def save(name, data):
        p = pulls / name
        p.write_text(json.dumps(data))
        paths[name] = p
        return p

    save("balance-sheet.json", books.balance_sheet(last))
    save("pl-12m.json", books.pl(start12, last))
    save("pl-12m-connector.json", books.pl(start12, last, limit=B.CONNECTOR_ROW_LIMIT))
    for year in range(y - 4, y):
        if (year, 12) >= books.first:
            save(f"pl-{year}.json", books.pl((year, 1), (year, 12)))
    save("pl-ytd.json", books.pl((y, 1), last))
    if m > 1:
        save("pl-prior.json", books.pl((y, 1), (y, m - 1)))
    # month-by-month pulls for books that close into a fund: every month end of last year,
    # and this year's before the two that pl-prior and pl-ytd cover
    through_end = (y, m - 2) if m > 2 else (y - 1, 12)
    for yy, mm in B.months_between((y - 1, 1), through_end):
        if (yy, mm) >= books.first:
            save(f"pl-through-{B.key(yy, mm)}.json", books.pl((yy, 1), (yy, mm)))
    return paths


def call(script, root, *args):
    done = subprocess.run([sys.executable, str(script), *args[:1], "--church-folder", str(root), *args[1:]],
                          capture_output=True, text=True, cwd=root)
    try:
        out = json.loads(done.stdout)
    except ValueError:
        out = {}
    return out, done.returncode, (done.stderr + done.stdout)[-1500:]


# --- what is true about the books ------------------------------------------------------

def truth_figures(module):
    c, t = module.CHURCH, module.TRUTH
    books = B.Books(c)
    y, m = books.last
    start12 = (y - 1, m + 1) if m < 12 else (y, 1)
    _, bal = books.balances(books.last)
    by_plain = {}
    for name, vals in bal.items():
        by_plain[B.strip_code(name)] = vals[-1]
    cash = sum(by_plain[a] for a in t["everyday_bank"])
    tot = books.period_totals(start12, books.last)
    side = {a["name"]: a["section"] for a in c["pl"]}
    inc = sum(v for k, v in tot.items() if side[k] in B.INCOME_SIDE)
    exp = sum(v for k, v in tot.items() if side[k] not in B.INCOME_SIDE)
    covered = sum(1 for ym in B.months_between(start12, books.last) if ym >= books.first)
    last_year = books.period_result((y - 1, 1), (y - 1, 12)) if (y - 1, 1) >= books.first else None
    return {"cash": round(cash), "income_12m": round(inc), "spending_12m": round(exp),
            "result_12m": round(inc - exp), "months_covered": covered,
            "months_of_spending": cash / (exp / covered) if exp else None, "last_year_result": last_year}


# --- the checks --------------------------------------------------------------------------

class Run:
    """Every script result for one church, made once and shared by its checks."""

    def __init__(self, module, root: Path):
        self.module, self.root = module, root
        self.truth = truth_figures(module)
        self.pulls = write_church(module, root)
        p = self.pulls
        self.look, self.look_code, self.look_err = call(
            ONBOARDING, root, "look", "--balance-sheet", str(p["balance-sheet.json"]), "--pl-12m", str(p["pl-12m.json"]))
        findings = root / "finance/onboarding/findings.json"
        self.findings = json.loads(findings.read_text())["findings"] if findings.exists() and self.look_code == 0 else []
        years = [a for k in sorted(p) if re.fullmatch(r"pl-\d{4}\.json", k) for a in ("--pl-year", str(p[k]))]
        self.draft, self.draft_code, self.draft_err = call(
            REPORT, root, "setup", "draft", "--balance-sheet", str(p["balance-sheet.json"]),
            "--pl-12m", str(p["pl-12m.json"]), *years)
        draft_file = root / "finance/board/setup-draft.json"
        self.draft_file = json.loads(draft_file.read_text()) if draft_file.exists() else {}
        self._built = {}

    def finding(self, fid):
        return next((f for f in self.findings if f["id"] == fid), None)

    def all_text(self):
        return " ".join(" ".join(str(f.get(k) or "") for k in ("finding", "why", "question")) for f in self.findings)

    def build(self, pl_through: bool):
        if pl_through in self._built:
            return self._built[pl_through]
        root, p = self.root, self.pulls
        if not (root / "finance/board/config.json").exists():
            y = B.Books(self.module.CHURCH).last[0]
            call(REPORT, root, "setup", "budget", "--year", str(y), "--none")
            call(REPORT, root, "setup", "one-time", "--none")
            saved, code, err = call(REPORT, root, "setup", "apply", "--approved-by", "Pat Example")
            if code:
                self._built[pl_through] = ({}, code, "setup apply: " + err)
                return self._built[pl_through]
        month = self.module.CHURCH["last_month"]
        extra = [a for k in sorted(p) if k.startswith("pl-through-")
                 for a in ("--pl-through", f"{k[11:18]}={p[k]}")] if pl_through else []
        prior = ["--pl-prior", str(p["pl-prior.json"])] if "pl-prior.json" in p else []
        out, code, err = call(REPORT, root, "build", "--month", month, "--prepared", "2026-09-10",
                              "--balance-sheet", str(p["balance-sheet.json"]), "--pl-ytd", str(p["pl-ytd.json"]),
                              *prior, *extra)
        report = root / "finance/board" / month / "report.json"
        result = (json.loads(report.read_text()) if code == 0 and report.exists() else {}, code, err)
        if report.exists():
            report.unlink()
        self._built[pl_through] = result
        return result


def check(run: Run, spec: dict) -> tuple[bool, str]:
    """(passed, what was seen)."""
    t, truth, kind = run.module.TRUTH, run.truth, spec["kind"]
    if kind.startswith("look") and kind != "look_refuses_truncated" and run.look_code:
        return False, f"look stopped: {run.look_err.strip()[-300:]}"
    if kind == "look_cash":
        f = run.finding("cash")
        seen = money_values(f["finding"])[0] if f else None
        text = (f or {}).get("finding", "")
        signed_ok = truth["cash"] >= 0 or seen is not None and seen < 0 or re.search(r"overdrawn|below zero", text, re.I)
        ok = seen is not None and abs(abs(seen) - abs(truth["cash"])) <= 1 and bool(signed_ok)
        return ok, f"look said {text!r}; everyday cash is {truth['cash']:,}"
    if kind == "look_result":
        f = run.finding("result")
        vals = money_values(f["finding"]) if f else []
        text = (f or {}).get("finding", "")
        short = "short" in text
        ok = len(vals) >= 3 and abs(vals[0] - truth["income_12m"]) <= 1 and abs(vals[1] - truth["spending_12m"]) <= 1 \
            and abs((-vals[2] if short else vals[2]) - truth["result_12m"]) <= 1
        return ok, (f"look said {text!r}; truth in {truth['income_12m']:,}, out {truth['spending_12m']:,}, "
                    f"result {truth['result_12m']:,}")
    if kind == "look_months_of_spending":
        f = run.finding("cash")
        got = re.search(r"about (-?[0-9.]+) months", (f or {}).get("finding", ""))
        want = truth["months_of_spending"]
        ok = bool(got) and abs(float(got.group(1)) - want) <= max(0.15 * abs(want), 0.1)
        return ok, f"look said {got.group(0) if got else None!r}; truth about {want:.1f} months"
    if kind == "look_concentration":
        f = run.finding("concentration")
        ok = bool(f) and t["largest_source"].lower() in f["finding"].lower()
        return ok, f"look said {(f or {}).get('finding')!r}; largest source is {t['largest_source']}"
    if kind == "look_concentration_not":
        f = run.finding("concentration")
        ok = not f or spec["name"].lower() not in f["finding"].lower()
        return ok, f"look said {(f or {}).get('finding')!r}"
    if kind == "look_flag":
        f = run.finding(spec["flag"])
        text = " ".join(str((f or {}).get(k) or "") for k in ("finding", "question"))
        missing = [w for w in spec.get("mentions", []) if w.lower() not in text.lower()]
        return bool(f) and not missing, f"{spec['flag']}: {text!r}" + (f"; missing {missing}" if missing else "")
    if kind == "look_no_flag":
        f = run.finding(spec["flag"])
        return f is None, f"{spec['flag']}: {(f or {}).get('finding')!r}"
    if kind == "look_mentions":
        text = run.all_text().lower()
        hit = [w for w in spec["terms"] if w.lower() in text]
        return bool(hit), f"findings mention {hit or 'none'} of {spec['terms']}"
    if kind == "look_refuses_truncated":
        p = run.pulls
        _, code, err = call(ONBOARDING, run.root, "look", "--balance-sheet", str(p["balance-sheet.json"]),
                            "--pl-12m", str(p["pl-12m-connector.json"]))
        return code != 0 and "cut off" in err, f"exit {code}: {err.strip()[-200:]!r}"
    if kind.startswith("draft") and run.draft_code:
        return False, f"setup draft stopped: {run.draft_err.strip()[-300:]}"
    if kind == "draft_bank":
        got = set(run.draft_file.get("bank_accounts", []))
        want = set(t["everyday_bank"])
        return got == want, f"drafted {sorted(got)}; everyday cash is {sorted(want)}"
    if kind == "draft_bank_includes":
        got = run.draft_file.get("bank_accounts", [])
        return spec["account"] in got, f"drafted {sorted(got)}"
    if kind == "draft_plain_names":
        names = [g["name"] for side in ("income_groups", "spending_groups") for g in run.draft_file.get(side, [])]
        bad = [n for n in names if re.match(r"^[-\d.]|^[A-Za-z]\s", n) or re.search(r"-\d\d\b", n)]
        return not bad and bool(names), f"group names {names}" + (f"; not plain: {bad}" if bad else "")
    if kind == "draft_one_time":
        got = {(c["year"], c["name"]) for c in run.draft_file.get("one_time_candidates", [])}
        want = {(o["year"], o["account"]) for o in t["one_time"]}
        return got == want, f"candidates {sorted(got)}; one-time items {sorted(want)}"
    if kind == "draft_obligations":
        got = run.draft_file.get("obligations", [])
        return len(got) >= spec["expect_count_at_least"], f"obligations {got}"
    if kind == "build_last_year":
        report, code, err = run.build(pl_through=spec.get("pl_through", False))
        if code:
            return False, f"build stopped: {err.strip()[-300:]}"
        line = report["plan"]["running"]["last_year"]
        want = truth["last_year_result"]
        return bool(line) and abs(line[-1] - want) <= 1, f"last year's line ends {line[-1] if line else None}; truth {round(want)}"
    if kind == "build_refuses_without_pl_through":
        _, code, err = run.build(pl_through=False)
        return code != 0 and "CHECK FAILED" in err, f"exit {code}: {err.strip()[-200:]!r}"
    if kind == "build_fiscal_year":
        report, code, err = run.build(pl_through=False)
        if code:
            return False, f"build stopped: {err.strip()[-300:]}"
        months = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                  "October", "November", "December"]
        first = months[run.module.CHURCH.get("fiscal_start", 1) - 1]
        label = report["meta"]["period_label"]
        return label.startswith(first), f"period label {label!r}; the fiscal year starts in {first}"
    raise ValueError(f"unknown check kind {kind}")


def score_church(cid: str) -> dict:
    module = ALL[cid]
    with tempfile.TemporaryDirectory() as tmp:
        run = Run(module, Path(tmp) / cid)
        results = []
        for spec in module.TRUTH["checks"]:
            passed, seen = check(run, spec)
            results.append({"church": cid, "check": spec["id"], "passed": passed, "gap": spec.get("gap"),
                            "why": spec.get("why", ""), "seen": seen})
    return {"church": cid, "name": module.CHURCH["name"], "truth": run.truth, "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("churches", nargs="*", default=list(ALL))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    scores = [score_church(c) for c in args.churches]
    if args.json:
        print(json.dumps(scores, indent=1, default=str))
        return 0
    unexpected = 0
    for s in scores:
        print(f"\n{s['name']}")
        for r in s["results"]:
            state = "PASS" if r["passed"] else ("GAP " if r["gap"] else "FAIL")
            if r["passed"] and r["gap"]:
                state = "NOW PASSES (remove the gap note)"
            unexpected += (not r["passed"] and not r["gap"]) or (r["passed"] and bool(r["gap"]))
            print(f"  {state:5} {r['check']}: {r['seen']}")
    print(f"\n{sum(len(s['results']) for s in scores)} checks, {unexpected} unexpected")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
