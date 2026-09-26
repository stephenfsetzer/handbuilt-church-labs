#!/usr/bin/env python3
"""First-time setup for the finance report: draft settings from the books,
add a budget, and save the confirmed settings.

    # 1. Draft every setting from QuickBooks pulls (the agent then walks the
    #    person through the draft, one question at a time)
    finance-report setup draft --church-folder . \
        --balance-sheet PULL.json --pl-12m PULL.json [--pl-year PULL.json ...]

    # 2. Budget: a QuickBooks Budget versus Actuals export, an annual figure,
    #    or none
    finance-report setup budget --church-folder . --year 2026 --csv EXPORT.csv
    finance-report setup budget --church-folder . --year 2026 --annual 12000
    finance-report setup budget --church-folder . --year 2026 --none

    # 3. One-time items found in past years: confirm each, or none
    finance-report setup one-time --church-folder . --year 2023 --amount 111697 \
        --label "loan forgiveness" [--done]
    finance-report setup one-time --church-folder . --none

    # 4. Check the confirmed draft and save it as finance/board/config.json
    finance-report setup apply --church-folder . --approved-by "Pat Example"

The draft is finance/board/setup-draft.json. Nothing is saved as settings
until apply. The script never contacts QuickBooks; the agent makes the pulls.
"""
import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_report_data import load_balance_sheet, load_pl, code, INCOME, EXPENSE  # noqa: E402

PROCESSOR = re.compile(r"stripe|givebutter|paypal|square|venmo|tithe\.?ly|pushpay|vanco|"
                       r"clearing|undeposited|payment", re.I)
INVEST = re.compile(r"invest|trust|endow|fund\b|brokerage|schwab|vanguard|fidelity|\bcd\b|certificate", re.I)
ONE_TIME = re.compile(r"forgiv|bequest|estate|legacy|insurance claim|gain on sale|sale of|\bppp\b|"
                      r"employee retention|\berc\b|one[- ]time", re.I)
OBLIGATIONS = {
    "episcopal": ["Payroll tax filings", "Church Pension Fund", "Diocesan assessment", "Property insurance"],
    "lutheran": ["Payroll tax filings", "Portico benefits", "Synod mission support", "Property insurance"],
}


def plain(name):
    """'6600 Physical Plant' -> 'Physical plant'."""
    n = re.sub(r"^\d+\s*", "", name).strip()
    n = n.replace("&", "and")
    return n[:1].upper() + n[1:].lower() if n.isupper() else n


def draft_path(root):
    return root / "finance/board/setup-draft.json"


def church_info(root):
    text = (root / "church.yaml").read_text() if (root / "church.yaml").exists() else ""
    trad = re.search(r"^\s*tradition:\s*(.+)$", text, re.M)
    name = re.search(r"^\s*name:\s*(.+)$", text, re.M)
    treas = re.search(r"-\s*name:\s*(.+)\n\s*role:\s*Treasurer", text)
    return {"name": name.group(1).strip() if name else "",
            "tradition": (trad.group(1).strip().lower() if trad else ""),
            "treasurer": treas.group(1).strip() if treas else ""}


# --- bank accounts ------------------------------------------------------------

def bank_block(rows):
    """Rows between the 'Bank Accounts' heading and the next asset section."""
    out, inside = [], False
    for name, vals in rows:
        if name == "Bank Accounts":
            inside = True
            continue
        if inside and name in ("Accounts Receivable", "Other Current Assets", "Fixed Assets", "Other Assets",
                               "Total Bank Accounts", "Total for Bank Accounts"):
            break
        if inside:
            out.append((name, vals))
    return out


def draft_accounts(rows):
    balances = {}
    for name, vals in bank_block(rows):
        base = re.sub(r"^\d+\s+", "", name)
        cur = balances.get(base, [0.0] * len(vals))
        balances[base] = [a + b for a, b in zip(cur, vals)]
    accounts = []
    for name, vals in balances.items():
        if re.fullmatch(r"[A-Z &/]+", name) and len(name.split()) <= 2:
            kind = "heading"
        elif PROCESSOR.search(name):
            kind = "payment service"
        elif INVEST.search(name):
            kind = "investments"
        elif all(abs(v) < 0.5 for v in vals):
            kind = "unused"
        else:
            kind = "bank"
        accounts.append({"name": name, "balance_now": round(vals[-1], 2),
                         "held_money_in_history": any(abs(v) >= 0.5 for v in vals), "kind": kind})
    inv = [a for a in accounts if a["kind"] == "investments"]
    endow = [a["name"] for a in inv]
    if len(inv) > 1:  # a parent account whose balance is the sum of its funds
        top = max(inv, key=lambda a: a["balance_now"])
        gap = top["balance_now"] - sum(a["balance_now"] for a in inv if a is not top)
        if abs(gap) >= 1:  # a fund whose name gave no hint, filed as a bank account
            for a in accounts:
                if a["kind"] == "bank" and abs(a["balance_now"] - gap) < 1:
                    a["kind"], a["reason"] = "investments", f"its balance completes {top['name']}"
                    gap = 0
                    break
        if abs(gap) < 1:
            endow = [top["name"]]
    return accounts, [a["name"] for a in accounts if a["kind"] == "bank"], endow


# --- income and spending groups ---------------------------------------------------

def candidates(items, sections):
    """Headings, or a single account when it is most of its heading."""
    heads = {}
    for it in items:
        if it["section"] not in sections:
            continue
        head = it["chain"][-2] if len(it["chain"]) > 2 else it["name"]  # chain ends with the section
        heads.setdefault(head, []).append(it)
    out = []
    for head, its in heads.items():
        total = sum(i["value"] for i in its)
        top = max(its, key=lambda i: i["value"])
        if len(its) > 1 and total and top["value"] / total >= 0.9:
            out.append({"key": code(top["name"]), "label": plain(top["name"]), "amount": top["value"],
                        "children": [top["name"]]})
            rest = [i for i in its if i is not top]
            out.append({"key": code(head), "label": plain(head), "amount": total - top["value"],
                        "children": [i["name"] for i in rest], "minor": True})
        else:
            out.append({"key": code(head), "label": plain(head), "amount": total,
                        "children": [i["name"] for i in sorted(its, key=lambda i: -i["value"])]})
    return sorted(out, key=lambda c: -c["amount"])


def draft_groups(items, sections, keep, other_label):
    cands = [c for c in candidates(items, sections) if c["amount"] > 0 and not c.get("minor")]
    total = sum(c["amount"] for c in candidates(items, sections) if c["amount"] > 0) or 1
    chosen = [c for c in cands[:keep] if c["amount"] / total >= 0.03]
    groups = [{"name": c["label"],
               "note": ", ".join(plain(n) for n in c["children"][:3]),
               "accounts": [c["key"]],
               "twelve_months": round(c["amount"]), "share": round(c["amount"] / total, 3)} for c in chosen]
    groups.append({"name": other_label, "note": "Everything not listed above", "accounts": ["*"],
                   "twelve_months": round(total - sum(c["amount"] for c in chosen)),
                   "share": round(1 - sum(c["amount"] for c in chosen) / total, 3)})
    return groups


def group_total(items, group_list, name, sections):
    from build_report_data import group_items
    return round(group_items(items, group_list, sections)[name])


# --- commands ---------------------------------------------------------------------

def cmd_draft(args, root):
    months, rows = load_balance_sheet(args.balance_sheet)
    accounts, bank, endow = draft_accounts(rows)
    _, _, items12, _ = load_pl(args.pl_12m)
    income = draft_groups(items12, INCOME, 3, "Everything else")
    spending = draft_groups(items12, EXPENSE, 4, "Everything else")
    info = church_info(root)

    # history: first month any everyday bank account held money
    bank_rows = [(re.sub(r"^\d+\s+", "", n), v) for n, v in rows]
    first = None
    for i, m in enumerate(months):
        if any(abs(v[i]) >= 0.5 for n, v in bank_rows if n in bank):
            first = m
            break

    years, one_time_candidates = [], []
    for path in args.pl_year or []:
        start, end, items, sections = load_pl(path)
        inc = sum(sections.get(s, 0) for s in INCOME)
        exp = sum(sections.get(s, 0) for s in EXPENSE)
        year = int(start[:4])
        flagged = [{"name": it["name"], "amount": round(it["value"])} for it in items
                   if it["section"] in INCOME and (ONE_TIME.search(it["name"]) or
                   (it["section"] == "Other Income" and inc and it["value"] > 0.1 * inc))]
        for f in flagged:
            one_time_candidates.append({"year": year, **f})
        years.append({"year": year, "reported": round(inc - exp), "result": round(inc - exp),
                      "pressure": {"income": group_total(items, income, income[0]["name"], INCOME),
                                   "spending": group_total(items, spending, spending[0]["name"], EXPENSE)}})
    years.sort(key=lambda y: y["year"])

    draft = {
        "_status": "draft: confirm each part with the person, then run apply",
        "church": info,
        "report_folder": "finance/board",
        "history_start": first,
        "accounts_found": accounts,
        "bank_accounts": bank,
        "endowment_accounts": endow,
        "payment_accounts": [a["name"] for a in accounts if a["kind"] == "payment service"],
        "labels": {},
        "income_groups": income,
        "spending_groups": spending,
        "budget": {},
        "budget_mode": "ask",
        "metrics": {},
        "cash_note": "",
        "cash_history_note": "",
        "one_time_candidates": one_time_candidates,
        "one_time_reviewed": not one_time_candidates,
        "long_view": {
            "full_years": [{"year": y["year"], "result": y["result"], "reported": y["reported"]} for y in years],
            "pressure": {
                "question": f"Does {income[0]['name'].lower()} cover {spending[0]['name'].lower()}?",
                "answer": "",
                "series": [
                    {"name": income[0]["name"], "role": "positive",
                     "values": {str(y["year"]): y["pressure"]["income"] for y in years}},
                    {"name": spending[0]["name"], "role": "attention",
                     "values": {str(y["year"]): y["pressure"]["spending"] for y in years}}],
                "note": ""}},
        "obligations": OBLIGATIONS.get(info["tradition"], OBLIGATIONS["episcopal"][:1] + ["Pension", "Insurance"]),
        "watch_seed": [],
        "approver": info["treasurer"],
    }
    out = draft_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft, indent=2))
    print(json.dumps({"status": "ok", "draft": str(out), "history_start": first, "bank_accounts": bank,
                      "endowment_accounts": endow,
                      "set_aside": {a["name"]: a["kind"] for a in accounts if a["kind"] != "bank"},
                      "income_groups": [(g["name"], g["twelve_months"]) for g in income],
                      "spending_groups": [(g["name"], g["twelve_months"]) for g in spending],
                      "one_time_candidates": one_time_candidates,
        "one_time_reviewed": not one_time_candidates,
                      "years": [y["year"] for y in years]}, indent=1))


def parse_bva(path):
    """QuickBooks Budget versus Actuals export: four columns per month
    (actual, budget, over budget, percent), then a total."""
    rows = list(csv.reader(open(path, newline="", encoding="utf-8-sig")))
    num = lambda s: float(s.replace("$", "").replace(",", "").strip() or 0)
    out = {}
    for r in rows:
        if r and r[0]:
            try:
                out[r[0]] = [num(r[2 + 4 * m]) for m in range(12)]
            except (ValueError, IndexError):
                continue
    return out


def cmd_budget(args, root):
    path = draft_path(root)
    d = json.loads(path.read_text())
    year = str(args.year)
    if args.none:
        d["budget_mode"] = "none"
        d["budget"].pop(year, None)
        d["metrics"] = {}
    elif args.annual is not None:
        d["budget_mode"] = "annual"
        d["budget"][year] = {"monthly_net": [round(args.annual / 12, 2)] * 12, "_source": "annual figure, spread evenly"}
    else:
        table = parse_bva(args.csv)
        if "Net Income" not in table:
            sys.exit("The export has no Net Income row. Export Budget vs. Actuals by month from QuickBooks.")
        entry = {"monthly_net": table["Net Income"], "_source": f"QuickBooks Budget vs. Actuals export ({Path(args.csv).name})"}
        big = d["spending_groups"][0]
        key = next((k for k in table if k.startswith("Total for ") and code(k[10:]) in big["accounts"]), None) \
            or next((k for k in table if code(k) in big["accounts"]), None)
        if key:
            entry["monthly_largest_cost"] = table[key]
            d["metrics"] = {"largest_cost_over_plan": {"accounts": big["accounts"], "plan": "monthly_largest_cost"}}
            d["watch_seed"] = [{"id": "largest-cost", "title": f"{big['name']} over plan", "status": "New",
                                "metric_key": "largest_cost_over_plan", "better": "down",
                                "latest_template": "{largest_cost_over_plan} {largest_cost_over_plan_word} plan through {month_name}.",
                                "latest": "", "next": "Treasurer to review."}] + \
                [w for w in d.get("watch_seed", []) if w.get("id") != "largest-cost"]
        d["budget_mode"] = "export"
        d["budget"][year] = entry
    path.write_text(json.dumps(d, indent=2))
    print(json.dumps({"status": "ok", "budget_mode": d["budget_mode"], "year": year,
                      "plan_for_year": round(sum(d["budget"].get(year, {}).get("monthly_net", [])) or 0),
                      "metrics": list(d["metrics"])}, indent=1))


def cmd_one_time(args, root):
    """Record a confirmed one-time item (it is taken out of that year's result), or none."""
    path = draft_path(root)
    d = json.loads(path.read_text())
    if not args.none:
        for y in d["long_view"]["full_years"]:
            if y["year"] == args.year:
                y["one_time"] = {"amount": args.amount, "label": args.label}
                y["result"] = round(y["reported"] - args.amount)
                break
        else:
            sys.exit(f"no {args.year} in the draft's full years")
    if args.none or args.done:
        d["one_time_reviewed"] = True
    path.write_text(json.dumps(d, indent=2))
    print(json.dumps({"status": "ok", "full_years": d["long_view"]["full_years"], "reviewed": d["one_time_reviewed"]}, indent=1))


def cmd_apply(args, root):
    d = json.loads(draft_path(root).read_text())
    problems = []
    if d.get("budget_mode") == "ask":
        problems.append("budget not decided: run budget with --csv, --annual, or --none")
    if not d.get("bank_accounts"):
        problems.append("no everyday bank accounts chosen")
    for side in ("income_groups", "spending_groups"):
        g = d.get(side, [])
        if not 2 <= len(g) <= 5:
            problems.append(f"{side}: {len(g)} groups; use 2 to 5")
        if not g or g[-1]["accounts"] != ["*"]:
            problems.append(f"{side}: the last group must be the catch-all ('*')")
        for x in g:
            if not x.get("name") or re.match(r"^\d", x["name"]):
                problems.append(f"{side}: give '{x.get('name')}' a plain name")
    if not d.get("one_time_reviewed"):
        problems.append("one-time items not reviewed: run one-time for each, or one-time --none")
    if not d.get("history_start"):
        problems.append("history start not found")
    if not d.get("approver"):
        problems.append("no approver named for the short answer")
    if problems:
        sys.exit("NOT SAVED:\n  " + "\n  ".join(problems))
    keep = ("report_folder", "history_start", "bank_accounts", "endowment_accounts", "payment_accounts", "labels", "income_groups",
            "spending_groups", "budget", "budget_mode", "metrics", "cash_note", "cash_history_note", "long_view",
            "obligations", "watch_seed", "approver")
    cfg = {"_comment": f"Finance report settings, approved by {args.approved_by} on {date.today().isoformat()}.",
           **{k: d[k] for k in keep if k in d}}
    for side in ("income_groups", "spending_groups"):
        cfg[side] = [{k: v for k, v in g.items() if k in ("name", "note", "accounts", "exclude")} for g in cfg[side]]
    out = root / "finance/board/config.json"
    out.write_text(json.dumps(cfg, indent=2))
    print(json.dumps({"status": "ok", "saved": str(out)}))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draft")
    p.add_argument("--church-folder", default=".")
    p.add_argument("--balance-sheet", required=True)
    p.add_argument("--pl-12m", required=True)
    p.add_argument("--pl-year", action="append")
    b = sub.add_parser("budget")
    b.add_argument("--church-folder", default=".")
    b.add_argument("--year", required=True, type=int)
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--csv")
    g.add_argument("--annual", type=float)
    g.add_argument("--none", action="store_true")
    o = sub.add_parser("one-time")
    o.add_argument("--church-folder", default=".")
    o.add_argument("--year", type=int)
    o.add_argument("--amount", type=float)
    o.add_argument("--label")
    o.add_argument("--none", action="store_true", help="no one-time items to take out")
    o.add_argument("--done", action="store_true", help="this was the last one")
    a = sub.add_parser("apply")
    a.add_argument("--church-folder", default=".")
    a.add_argument("--approved-by", required=True)
    args = ap.parse_args(argv)
    root = Path(args.church_folder).resolve()
    {"draft": cmd_draft, "budget": cmd_budget, "one-time": cmd_one_time, "apply": cmd_apply}[args.cmd](args, root)


if __name__ == "__main__":
    main()
