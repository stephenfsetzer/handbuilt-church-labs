#!/usr/bin/env python3
"""Finance onboarding: four stages that lead to the monthly finance report.

    orient     where this church is and what comes next
    look       stage 1 findings from QuickBooks pulls (for the finance overview)
    readiness  set a readiness item to met, waived (with a reason), or open
    calendar   the monthly calendar and approver (stage 4)
    stage      mark a stage done; each stage has conditions

State lives in finance/onboarding-state.json. Read-only everywhere: this
script reads saved pulls and writes only in the church folder.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT_SCRIPTS = HERE.parents[1] / "finance-report" / "scripts"
sys.path.insert(0, str(REPORT_SCRIPTS))
from build_report_data import load_balance_sheet, load_pl, code, strip_code, INCOME, EXPENSE  # noqa: E402
from finance_setup import draft_accounts, draft_groups, plain  # noqa: E402

STAGES = {
    1: ("Look", "Pull the books read-only and write the finance overview for the pastor."),
    2: ("First report", "Run first-time setup and build a sample edition."),
    3: ("Make the books report-ready", "Work through the readiness checklist with the treasurer; fix or waive each item."),
    4: ("Lock the monthly report", "Set the calendar and approver, and have the treasurer approve the first real edition."),
}

# The readiness checklist. "check" says how it is known; "caveat" is what a
# report prints while the item is open or waived.
READINESS = [
    {"id": "payment_services", "title": "Payment services cleared each month", "check": "data",
     "caveat": "Online payments are not yet matched to income each month, so some income appears late."},
    {"id": "unrecorded_income", "title": "Money received is recorded", "check": "data",
     "caveat": "Some money received is not yet recorded."},
    {"id": "reconciliation", "title": "Bank accounts reconciled monthly", "check": "ask",
     "caveat": "Not every bank account is reconciled each month."},
    {"id": "month_lock", "title": "Months locked after checking", "check": "ask",
     "caveat": "Months are not locked after they are checked, so recent figures can change."},
    {"id": "restricted_funds", "title": "Restricted funds confirmed", "check": "ask + data",
     "caveat": "Money set aside for restricted purposes is not yet confirmed, so not all bank cash may be spendable."},
    {"id": "budget", "title": "A budget for the year, or a decision to go without", "check": "setup",
     "caveat": "There is no budget for this year."},
]


def state_path(root):
    return root / "finance/onboarding-state.json"


def load_state(root):
    p = state_path(root)
    if p.exists():
        st = json.loads(p.read_text())
        sync_from_settings(root, st)
        return st
    return {"stage": 1, "stages": {}, "readiness": [dict(r, status="open", reason=None) for r in READINESS],
            "calendar": {}, "locked": False, "log": []}


def sync_from_settings(root, st):
    """Items that setup settles: a saved budget, or a decision to go without one."""
    cfg_path = root / "finance/board/config.json"
    if not cfg_path.exists():
        return
    cfg = json.loads(cfg_path.read_text())
    if cfg.get("budget") or cfg.get("budget_mode") == "none":
        for r in st["readiness"]:
            if r["id"] == "budget" and r["status"] == "open":
                r["status"] = "met"
                log(st, "Readiness: budget settled in setup.")


def save_state(root, st):
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=2))


def log(st, text):
    st["log"].append({"date": date.today().isoformat(), "note": text})


def largest_source(items, top, income):
    """The largest source of income: the top group, or, when one heading holds most of the
    income (more than 80%), the largest account or heading directly under it."""
    if top["share"] <= 0.8 or not income or top["accounts"] == ["*"]:
        return top
    under = {}
    for it in items:
        if it["section"] not in INCOME:
            continue
        chain = [code(n) for n in it["chain"]]
        if top["accounts"][0] not in chain[1:]:
            continue
        at = chain.index(top["accounts"][0])
        child = it["chain"][at - 1]
        under[child] = under.get(child, 0) + it["value"]
    if len(under) < 2:
        return top
    name, amount = max(under.items(), key=lambda kv: kv[1])
    return {"name": plain(name), "share": round(amount / income, 3)}


def balances(rows, n):
    """Sum each account's opening row and change row by name."""
    out = {}
    for name, vals in rows:
        base = strip_code(name)
        cur = out.get(base, [0.0] * n)
        out[base] = [a + b for a, b in zip(cur, vals)]
    return out


def section(rows, start, stop):
    names = [n for n, _ in rows]
    if start not in names:
        return []
    i = names.index(start)
    j = next((k for k in range(i + 1, len(names)) if names[k] in stop), len(names))
    return rows[i + 1:j]


def money(v):
    return f"${abs(round(v)):,}"


# --- commands ---------------------------------------------------------------------

def cmd_look(args, root):
    months, rows = load_balance_sheet(args.balance_sheet)
    n = len(months)
    accounts, bank, endow = draft_accounts(rows)
    start, end, items, sections = load_pl(args.pl_12m)
    period_months = (int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7]) + 1
    inc = sum(sections.get(s, 0) for s in INCOME)
    exp = sum(sections.get(s, 0) for s in EXPENSE)
    groups = draft_groups(items, INCOME, 3, "Everything else")
    bal = balances(rows, n)
    cash_now = sum(bal[a][-1] for a in bank if a in bal)
    findings, st = [], load_state(root)

    def add(fid, level, text, why, question=None, readiness=None):
        findings.append({"id": fid, "level": level, "finding": text, "why": why, "question": question,
                         "readiness": readiness})

    add("cash", "info", f"{money(cash_now)} in everyday bank accounts, about {cash_now / (exp / period_months):.1f} months of spending.",
        "The first thing a board asks: can we pay our bills?")
    add("result", "info", f"Over the {period_months} months pulled, {money(inc)} came in and {money(exp)} went out, "
        f"{money(inc - exp)} {'ahead' if inc >= exp else 'short'}.", "The year's direction, before any detail.")
    top = largest_source(items, groups[0], inc)
    if top and top["share"] >= 0.5:
        add("concentration", "watch", f"{top['name']} is {top['share']:.0%} of income.",
            "Heavy reliance on one source is the main financial risk to name for the board.",
            f"How secure is {top['name']} over the next two years?")
    procs = [a for a in accounts if a["kind"] == "payment service"]
    open_procs = [a for a in procs if abs(a["balance_now"]) >= args.clearing_threshold]
    if open_procs:
        add("payment_services", "fix", "Payment services carry balances in the books: " +
            ", ".join(f"{a['name']} {money(a['balance_now'])}" for a in open_procs) + ".",
            "A balance here usually means income received online was not recorded in full, or was recorded late.",
            "When are online payments recorded, and are they recorded in full, with fees as an expense?",
            "payment_services")
    liab = balances(section(rows, "Liabilities", {"Equity"}), n)
    neg = {k: v[-1] for k, v in liab.items() if v[-1] < -500}
    if neg:
        add("negative_liabilities", "fix", "Liabilities below zero: " +
            ", ".join(f"{k} {money(v)}" for k, v in neg.items()) + ".",
            "A liability cannot normally be negative; it usually means income or payments were recorded in the wrong place.",
            "What should these accounts hold?")
    eq = balances(section(rows, "Equity", {"Retained Earnings", "Net Income"}), n)
    obe = next((v[-1] for k, v in eq.items() if "opening bal" in k.lower()), 0)
    if abs(obe) >= 1:
        add("opening_balance_equity", "tidy", f"Opening Balance Equity holds {money(obe)}.",
            "This account should be zero after setup; a balance hides an old correction.", "What is in Opening Balance Equity?")
    span = min(12, n - 1)
    # Restricted funds should move; permanent endowment corpus and group headings are expected not to
    stale = [k for k, v in eq.items() if re.search(r"fund", k, re.I) and abs(v[-1]) >= 1 and
             not re.search(r"funds$|perm|corpus|endow|^DIT\b", k, re.I) and
             all(abs(x - v[-1]) < 1 for x in v[-1 - span:])]
    if stale:
        add("restricted_funds", "fix", "Fund balances unchanged for a year: " + ", ".join(stale) + ".",
            "If these hold restricted money, their balances should move as money comes in and is spent; "
            "unchanged balances mean the books cannot say how much cash is truly spendable.",
            "Which funds are donor-restricted, and what is each one's true balance?", "restricted_funds")
    headings = [it for it in items if it["name"] in {c for i2 in items for c in i2["chain"][1:-1]}]
    if headings:
        add("heading_postings", "tidy", "Amounts posted to account headings: " +
            ", ".join(f"{h['name']} {money(h['value'])}" for h in headings[:3]) + ".",
            "Posting to a heading instead of an account makes reports harder to read.", None)
    used = len({it["name"] for it in items})
    add("accounts_used", "info", f"{used} income and expense accounts were used in the last twelve months.",
        "A useful measure of how complicated the books are for a church this size.")
    for q in ("Are all bank accounts reconciled each month, and through which month?",
              "Are months locked in QuickBooks after they are checked? (Settings, Advanced, Close the books)",
              "Is there a budget for this year in QuickBooks?",
              "Who has access to QuickBooks and the bank, and are any logins shared?"):
        findings.append({"id": "ask", "level": "ask", "finding": None, "why": None, "question": q, "readiness": None})

    out = root / "finance/onboarding"
    out.mkdir(parents=True, exist_ok=True)
    (out / "findings.json").write_text(json.dumps(
        {"pulled_through": months[-1], "bank_accounts": bank, "endowment_accounts": endow,
         "accounts": accounts, "income_groups": groups, "findings": findings}, indent=2))
    # data-checked readiness items start from what the books show
    flagged = {f["readiness"] for f in findings if f["readiness"]}
    for r in st["readiness"]:
        if r["id"] == "payment_services":
            r["status"] = "open" if "payment_services" in flagged else "met"
    st["stages"]["1"] = {"started": date.today().isoformat(), "findings": "finance/onboarding/findings.json"}
    log(st, f"Stage 1 findings from books through {months[-1]}.")
    save_state(root, st)
    print(json.dumps({"status": "ok", "findings": str(out / "findings.json"),
                      "summary": [f["finding"] for f in findings if f["finding"]],
                      "questions_for_treasurer": [f["question"] for f in findings if f["question"]]}, indent=1))


def cmd_readiness(args, root):
    st = load_state(root)
    item = next((r for r in st["readiness"] if r["id"] == args.item), None)
    if not item:
        sys.exit(f"unknown item '{args.item}'; one of: {', '.join(r['id'] for r in st['readiness'])}")
    if args.status == "waived" and not args.reason:
        sys.exit("a waiver needs a reason, in plain words")
    item["status"], item["reason"] = args.status, args.reason
    if args.caveat:
        item["caveat"] = args.caveat
    log(st, f"Readiness: {item['title']} set to {args.status}" + (f" ({args.reason})" if args.reason else ""))
    save_state(root, st)
    print(json.dumps({"status": "ok", "readiness": {r["id"]: r["status"] for r in st["readiness"]}}, indent=1))


def cmd_calendar(args, root):
    st = load_state(root)
    st["calendar"] = {"books_closed_by": args.books_closed_by, "report_by": args.report_by,
                      "meeting": args.meeting, "approver": args.approver}
    log(st, "Monthly calendar set.")
    save_state(root, st)
    print(json.dumps({"status": "ok", "calendar": st["calendar"]}, indent=1))


def stage_problems(root, st, n):
    board = root / "finance/board"
    if n == 1:
        p = []
        if not (root / "finance/onboarding/findings.json").exists():
            p.append("run look first")
        if not (root / "finance/finance-overview.md").exists():
            p.append("write finance/finance-overview.md from the findings and show it to the pastor")
        return p
    if n == 2:
        p = [] if (board / "config.json").exists() else ["first-time setup not saved (finance report workflow, first-time setup)"]
        if not any(board.glob("*/report.json")):
            p.append("no sample edition built yet")
        return p
    if n == 3:
        return [f"{r['title']}: still open (fix it, or waive it with a reason)" for r in st["readiness"] if r["status"] == "open"]
    if n == 4:
        p = []
        cal = st.get("calendar", {})
        for k in ("books_closed_by", "report_by", "approver"):
            if not cal.get(k):
                p.append(f"calendar: {k} not set")
        finals = [f for f in board.glob("*/report.json") if json.loads(f.read_text())["meta"]["status"] == "final"]
        if not finals:
            p.append("no edition approved as final by the treasurer yet")
        return p
    return [f"unknown stage {n}"]


def cmd_stage(args, root):
    st = load_state(root)
    n = args.done
    if n != st["stage"]:
        sys.exit(f"the current stage is {st['stage']} ({STAGES[st['stage']][0]}), not {n}")
    problems = stage_problems(root, st, n)
    if problems:
        print(json.dumps({"status": "blocked", "code": "stage_not_finished", "stage": n, "missing": problems}))
        sys.exit(2)
    st["stages"].setdefault(str(n), {})["done"] = date.today().isoformat()
    if n == 4:
        st["locked"] = True
        log(st, "Monthly finance report locked in; the monthly finance report takes over.")
    else:
        st["stage"] = n + 1
        log(st, f"Stage {n} done.")
    save_state(root, st)
    print(json.dumps({"status": "ok", "stage": st["stage"], "locked": st["locked"]}))


def cmd_orient(args, root):
    st = load_state(root)
    if st["locked"]:
        nxt = "Onboarding is complete. Use the finance report workflow each month."
    else:
        name, what = STAGES[st["stage"]]
        nxt = f"Stage {st['stage']}, {name}: {what}"
    open_items = [r["title"] for r in st["readiness"] if r["status"] == "open"]
    waived = [f"{r['title']} ({r['reason']})" for r in st["readiness"] if r["status"] == "waived"]
    print(json.dumps({"status": "ok", "stage": st["stage"], "locked": st["locked"], "next": nxt,
                      "blocking_this_stage": stage_problems(root, st, st["stage"]) if not st["locked"] else [],
                      "readiness_open": open_items, "readiness_waived": waived,
                      "started_fresh": not state_path(root).exists()}, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--church-folder", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("orient", parents=[common])
    lk = sub.add_parser("look", parents=[common])
    lk.add_argument("--balance-sheet", required=True)
    lk.add_argument("--pl-12m", required=True)
    lk.add_argument("--clearing-threshold", type=float, default=1000)
    rd = sub.add_parser("readiness", parents=[common])
    rd.add_argument("--item", required=True)
    rd.add_argument("--status", required=True, choices=["met", "waived", "open"])
    rd.add_argument("--reason")
    rd.add_argument("--caveat", help="replace the sentence reports print for this item")
    cl = sub.add_parser("calendar", parents=[common])
    cl.add_argument("--books-closed-by", required=True, help="for example, the 15th")
    cl.add_argument("--report-by", required=True, help="for example, the 20th")
    cl.add_argument("--meeting", default="")
    cl.add_argument("--approver", required=True)
    sg = sub.add_parser("stage", parents=[common])
    sg.add_argument("--done", type=int, required=True)
    args = ap.parse_args(argv)
    root = Path(args.church_folder).resolve()
    {"orient": cmd_orient, "look": cmd_look, "readiness": cmd_readiness, "calendar": cmd_calendar,
     "stage": cmd_stage}[args.cmd](args, root)


if __name__ == "__main__":
    main()
