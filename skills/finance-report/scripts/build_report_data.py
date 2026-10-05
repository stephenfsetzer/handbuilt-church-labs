#!/usr/bin/env python3
"""Build a month's report.json from saved QuickBooks pulls and the church config.

    python3 build_report_data.py --church-folder . --month 2026-08 \
        --balance-sheet PULL.json --pl-ytd PULL.json [--pl-prior PULL.json] \
        [--unrecorded "1500|Hall rent received August 21, not yet recorded"]

Inputs (saved connector responses, JSON):
  --balance-sheet  balance sheet split by month, from config history_start
                   (or earlier) through the report month end
  --pl-ytd         profit and loss, January 1 through the report month end
  --pl-prior       profit and loss, January 1 through the prior month end
                   (omit for January)
  --pl-through     YYYY-MM=PULL.json, repeatable: profit and loss, January 1
                   through that month end. When a year's months are all
                   given (with --pl-ytd and --pl-prior), its monthly results
                   come from them instead of from equity on the balance sheet,
                   for books that close each year into a fund balance

Writes <report_folder>/<month>/report.json. The short answer and any watch
item without a template are drafts for a person to finish. Stops with an
error if a total does not agree with QuickBooks.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from cash_position import cash_summary, signed_money

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}


def fail(msg):
    sys.exit(f"CHECK FAILED: {msg}")


def money(v):
    return f"${abs(round(v)):,}"


# --- account names ------------------------------------------------------------

# An account number at the start of a QuickBooks account name: digits, then any
# hyphen or dot parts, then at most one letter ("6600", "1006-01", "5002A").
ACCOUNT_CODE = r"\d+(?:[-.]\d+)*[A-Za-z]?"


def strip_code(name):
    """'1006-01 Operating Fund' -> 'Operating Fund'; a name with no number is unchanged."""
    return re.sub(rf"^{ACCOUNT_CODE}\s+", "", name)


# --- balance sheet ------------------------------------------------------------

def load_balance_sheet(path):
    d = json.loads(Path(path).read_text())
    cols = [c["key"] for c in d["displayColumns"][1:]]
    months = []
    for c in cols:
        m, y = c.split()
        months.append(f"{y}-{ABBR[m]:02d}")
    rows = []
    for r in d["reportData"]["rows"]:
        name = r["cells"][0]["value"]
        if name is None:
            continue
        rows.append((name, [c.get("value") or 0 for c in r["cells"][1:]]))
    return months, rows


def account_total(rows, names, n):
    """The connector prints each account as an opening row ('1002 Name') and a
    change row ('Name'). The balance is their sum."""
    total = [0.0] * n
    for name, vals in rows:
        base = strip_code(name)
        if base in names:
            total = [a + b for a, b in zip(total, vals)]
    return total


def account_present(rows, name):
    return any(strip_code(n) == name for n, _ in rows)


SET_ASIDE_KINDS = ("restricted", "designated", "investment", "in_transit")


def set_aside_money(cfg, bs, n, idx):
    """Money the church holds that is not everyday cash, by name, at the report month end.

    Read from the same balance sheet and with the same account_total helper as
    the bank figure. It is shown beside the bank figure and never added to or
    taken from it."""
    entries = cfg.get("set_aside_accounts")
    if not entries:
        return None
    bank_accounts = set(cfg["bank_accounts"])
    items = []
    for e in entries:
        account, name, kind = e.get("account"), (e.get("name") or "").strip(), e.get("kind")
        if not account or not name:
            fail("each set_aside_accounts entry needs an account and a name")
        if kind not in SET_ASIDE_KINDS:
            fail(f"set_aside_accounts '{name}': kind must be one of {', '.join(SET_ASIDE_KINDS)}")
        if account in bank_accounts:
            fail(f"set_aside_accounts '{name}' is also in bank_accounts; an account is either everyday cash or set aside")
        if not account_present(bs, account):
            fail(f"balance sheet has no '{account}' row for set-aside money '{name}'")
        items.append({"name": name, "kind": kind, "amount": round(account_total(bs, {account}, n)[idx])})
    return items


def row(rows, name):
    for n, vals in rows:
        if n == name:
            return vals
    fail(f"balance sheet has no '{name}' row")


# --- profit and loss ------------------------------------------------------------

# Section headings as QuickBooks sometimes spells them, read as the names the builder uses.
SECTION_NAMES = {"other expense": "Other Expenses", "other expenses": "Other Expenses", "expense": "Expenses",
                 "expenses": "Expenses", "other income": "Other Income", "income": "Income",
                 "cost of goods sold": "Cost of Goods Sold", "cost of sales": "Cost of Goods Sold"}


def section_name(name):
    return SECTION_NAMES.get((name or "").strip().lower(), name or "")


def load_pl(path):
    d = json.loads(Path(path).read_text())
    rows = d["reportData"]["data"]["rows"]
    by_id = {r["metadata"]["id"]: r for r in rows}
    section_of = {}
    for r in rows:
        rid = r["metadata"]["id"]
        if "." not in rid:
            section_of[rid] = section_name(r["cells"][0]["value"])
    items, sections = [], {}
    for r in rows:
        rid = r["metadata"]["id"]
        name = r["cells"][0]["value"]
        val = r["cells"][1]["value"] or 0
        if "." not in rid and name:
            sections[section_name(name)] = val
        own = (r["cells"][2]["value"] or 0) if len(r["cells"]) > 2 else 0
        if "GROUP" in r["metadata"]["type"] and "." in rid and own:
            val = own  # an amount posted to the heading itself, not a sub-account
        elif "ITEM" not in r["metadata"]["type"] or name is None:
            continue
        chain, parts = [name], rid.split(".")
        for k in range(len(parts) - 1, 0, -1):
            parent = by_id.get(".".join(parts[:k]))
            if parent and parent["cells"][0]["value"]:
                chain.append(parent["cells"][0]["value"])
        sec = section_of.get(parts[0], "")
        items.append({"name": name, "chain": chain, "section": sec, "value": val})
    check_complete(path, rows, items, sections)
    return d["periodStart"], d["periodEnd"], items, sections


# The QuickBooks connector returns at most this many profit and loss rows, with no warning.
CONNECTOR_ROW_LIMIT = 100


def check_complete(path, rows, items, sections):
    """Stop on a profit and loss the connector cut off: rows at its limit, or line rows that do not
    add up to their section's total. Nothing drafted from a partial pull can be trusted."""
    name = Path(path).name
    if len(rows) >= CONNECTOR_ROW_LIMIT:
        fail(f"{name} has {len(rows)} rows, the connector's limit, so it is probably cut off; "
             "pull a shorter period or use the QuickBooks export instead")
    for sec in (*INCOME, *EXPENSE):
        if sec not in sections:
            continue
        lines = sum(it["value"] for it in items if it["section"] == sec)
        if abs(lines - sections[sec]) > 1:
            fail(f"{name}: the {sec} lines add up to {lines:,.2f} but the {sec} total is {sections[sec]:,.2f}, "
                 "so the pull is incomplete; pull it again or use the QuickBooks export instead")


def pl_net(sections):
    """A profit and loss pull's result: income less spending, from its section totals."""
    return sum(sections.get(s, 0) for s in INCOME) - sum(sections.get(s, 0) for s in EXPENSE)


def results_through(args, year, mon):
    """Year-to-date results by month end ('YYYY-MM'), from the profit and loss pulls given."""
    out = {}
    for spec in args.pl_through:
        month, sep, path = spec.partition("=")
        if not sep or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            fail(f"--pl-through takes YYYY-MM=PULL.json, not {spec!r}")
        start, end, _, sections = load_pl(path)
        if not start.startswith(f"{month[:4]}-01") or not end.startswith(month):
            fail(f"--pl-through {month} covers {start} to {end}; it must run January 1 to the end of {month}")
        out[month] = pl_net(sections)
    _, _, _, ytd_sec = load_pl(args.pl_ytd)
    out[f"{year}-{mon:02d}"] = pl_net(ytd_sec)
    if args.pl_prior and mon > 1:
        out[f"{year}-{mon - 1:02d}"] = pl_net(load_pl(args.pl_prior)[3])
    return out


def code(name):
    first = name.split()[0] if name.split() else name
    return first if re.fullmatch(ACCOUNT_CODE, first) else name


def group_items(items, groups, sections_wanted):
    out = {g["name"]: 0.0 for g in groups}
    for it in items:
        if it["section"] not in sections_wanted:
            continue
        codes = [code(n) for n in it["chain"]]
        for g in groups:
            if any(c in codes for c in g.get("exclude", [])):
                continue
            if "*" in g["accounts"] or any(a in codes for a in g["accounts"]):
                out[g["name"]] += it["value"]
                break
    return out


def item_values(items, sections_wanted):
    return {it["name"]: it["value"] for it in items if it["section"] in sections_wanted}


INCOME = ("Income", "Other Income")
EXPENSE = ("Expenses", "Other Expenses", "Cost of Goods Sold")


def metric_total(items, accounts):
    return sum(it["value"] for it in items
               if it["section"] in EXPENSE and any(a in [code(n) for n in it["chain"]] for a in accounts))


# --- main --------------------------------------------------------------------

def watch_status(item, prev_watch):
    """New, No change, Better or Worse against last month's item, as the report prints it."""
    before = next((w for w in prev_watch if w.get("id") == item.get("id")), None)
    if before is None:
        return "New"
    if "metric" in item and "metric" in before:
        if item["metric"] == before["metric"]:
            return "No change"
        improved = item["metric"] < before["metric"] if item.get("better", "down") == "down" else item["metric"] > before["metric"]
        return "Better" if improved else "Worse"
    return "No change"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--church-folder", default=".")
    ap.add_argument("--month", required=True, help="YYYY-MM, the last month of books in the report")
    ap.add_argument("--balance-sheet", required=True)
    ap.add_argument("--pl-ytd", required=True)
    ap.add_argument("--pl-prior")
    ap.add_argument("--pl-through", action="append", default=[], help="'YYYY-MM=PULL.json'")
    ap.add_argument("--unrecorded", action="append", default=[], help="'amount|label'")
    ap.add_argument("--prepared", required=True, help="YYYY-MM-DD")
    ap.add_argument("--sample", action="store_true", help="mark as a sample rebuilt from current books")
    args = ap.parse_args(argv)

    root = Path(args.church_folder).resolve()
    cfg = json.loads((root / "finance/board/config.json").read_text())
    folder = root / cfg["report_folder"]
    year, mon = int(args.month[:4]), int(args.month[5:])
    mname = MONTHS[mon - 1]
    budget = cfg.get("budget", {}).get(str(year))
    if not budget and cfg.get("budget_mode") != "none":
        fail(f"config has no budget for {year}; add one or choose no budget in setup")

    # balance sheet: bank, endowment, monthly results
    months, bs = load_balance_sheet(args.balance_sheet)
    if args.month not in months:
        fail(f"balance sheet does not reach {args.month}")
    n = len(months)
    bank = account_total(bs, set(cfg["bank_accounts"]), n)
    equity = [a + b for a, b in zip(row(bs, "Retained Earnings"), row(bs, "Net Income"))]
    monthly = {months[i]: equity[i] - equity[i - 1] for i in range(1, n)}
    # A year whose month ends all have a profit and loss pull takes its results from them. Books
    # that close each year into a fund balance move equity without a result, so equity alone
    # misreads the months the closing entry falls in.
    ytd = results_through(args, year, mon) if args.pl_through else {}
    for y, upto in ((year - 1, 12), (year, mon)):
        keys = [f"{y}-{m:02d}" for m in range(1, upto + 1)]
        if all(k in ytd for k in keys):
            for m, k in enumerate(keys):
                monthly[k] = ytd[k] - (ytd[keys[m - 1]] if m else 0)
    idx = months.index(args.month)

    def cum(y, upto):
        s, out = 0.0, []
        for m in range(1, upto + 1):
            key = f"{y}-{m:02d}"
            if key not in monthly:
                fail(f"balance sheet must start by December {y - 1} to chart {y}")
            s += monthly[key]
            out.append(round(s))
        return out

    # Short history: the books do not reach back to December two years ago,
    # so there is no full last year to compare with.
    short_history = cfg["history_start"] > f"{year - 2}-12"
    this_year = cum(year, mon)
    last_year = None if short_history else cum(year - 1, 12)
    known = next((y for y in cfg.get("long_view", {}).get("full_years", []) if y["year"] == year - 1), None)
    if last_year and known and abs(last_year[-1] - known["reported"]) > 1:
        fail(f"last year's line ends at {last_year[-1]:,} but {year - 1}'s recorded result is "
             f"{known['reported']:,}; the books for {year - 1} have changed or the settings are out of date")
    plan_cum = [round(sum(budget["monthly_net"][:m])) for m in range(1, 13)] if budget else None

    # profit and loss: groups, this month, checks
    _, end, ytd_items, ytd_sec = load_pl(args.pl_ytd)
    if not end.startswith(args.month):
        fail(f"--pl-ytd ends {end}, expected {args.month}")
    prior_items, prior_sec = [], {}
    if args.pl_prior:
        p_start, p_end, prior_items, prior_sec = load_pl(args.pl_prior)
        want = f"{year}-{mon - 1:02d}"
        if mon == 1 or not p_end.startswith(want) or not p_start.startswith(f"{year}-01"):
            fail(f"--pl-prior covers {p_start} to {p_end}; it must run January 1 to the end of {want}")
    elif mon > 1:
        fail("--pl-prior is required after January")
    inc_ytd = group_items(ytd_items, cfg["income_groups"], INCOME)
    sp_ytd = group_items(ytd_items, cfg["spending_groups"], EXPENSE)
    inc_prior = group_items(prior_items, cfg["income_groups"], INCOME)
    sp_prior = group_items(prior_items, cfg["spending_groups"], EXPENSE)

    total_inc = sum(ytd_sec.get(s, 0) for s in INCOME)
    total_sp = sum(ytd_sec.get(s, 0) for s in EXPENSE)
    if abs(sum(inc_ytd.values()) - total_inc) > 1:
        fail(f"income groups {sum(inc_ytd.values()):,.2f} != QuickBooks income {total_inc:,.2f}")
    if abs(sum(sp_ytd.values()) - total_sp) > 1:
        fail(f"spending groups {sum(sp_ytd.values()):,.2f} != QuickBooks expenses {total_sp:,.2f}")
    if args.pl_prior:
        prior_inc = sum(prior_sec.get(s, 0) for s in INCOME)
        prior_sp = sum(prior_sec.get(s, 0) for s in EXPENSE)
        if abs(sum(inc_prior.values()) - prior_inc) > 1:
            fail("prior income groups do not match QuickBooks income; refresh the prior-period pull")
        if abs(sum(sp_prior.values()) - prior_sp) > 1:
            fail("prior spending groups do not match QuickBooks expenses; refresh the prior-period pull")
        if abs(prior_inc - prior_sp - this_year[-2]) > 1:
            fail("prior profit and loss net does not match the prior balance sheet change; refresh both pulls")
    ytd_net = total_inc - total_sp
    if abs(ytd_net - this_year[-1]) > 1:
        fail(f"profit and loss net {ytd_net:,.2f} != balance sheet change {this_year[-1]:,.2f}; "
             "look for entries posted straight to equity")

    def month_parts(groups, ytd, prior):
        parts = [{"name": g["name"], "note": g["note"], "amount": round(ytd[g["name"]]),
                  "this_month": round(ytd[g["name"]] - prior.get(g["name"], 0)), "catch_all": g["accounts"] == ["*"]}
                 for g in groups]
        kept = [p for p in parts if not (p["catch_all"] and p["amount"] == 0 and p["this_month"] == 0)]
        return [{k: v for k, v in p.items() if k != "catch_all"} for p in kept]

    # largest single lines this month
    labels = cfg.get("labels", {})

    def top(sections):
        now, before = item_values(ytd_items, sections), item_values(prior_items, sections)
        diffs = {k: now.get(k, 0) - before.get(k, 0) for k in dict.fromkeys([*now, *before])}
        if not any(diffs.values()):
            return {"label": "No net change", "amount": 0}
        k = max(diffs, key=lambda key: abs(diffs[key]))
        return {"label": labels.get(code(k), strip_code(k)), "amount": round(diffs[k])}

    came_in = round(sum(inc_ytd.values()) - sum(inc_prior.values()))
    went_out = round(sum(sp_ytd.values()) - sum(sp_prior.values()))

    # metrics for watch items
    metrics = {}
    for key, m in cfg.get("metrics", {}).items():
        actual = metric_total(ytd_items, m["accounts"])
        if m.get("plan"):
            if not budget or m["plan"] not in budget:
                continue
            metrics[key] = round(actual - sum(budget[m["plan"]][:mon]))
        else:
            metrics[key] = round(actual)

    # previous report: watch list and obligations carry forward
    prev_path = folder / f"{year if mon > 1 else year - 1}-{(mon - 2) % 12 + 1:02d}" / "report.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else None
    watch = []
    carried = (prev or {}).get("watch") if prev else [dict(w) for w in cfg.get("watch_seed", [])]
    for w in carried or []:
        if w.get("status") == "Resolved":
            continue
        item = {k: v for k, v in w.items() if k != "status"}
        if w.get("metric_key") in metrics:
            item["metric"] = metrics[w["metric_key"]]
        if w.get("latest_template"):
            words = {f"{k}_word": ("over" if v >= 0 else "under") for k, v in metrics.items()}
            item["latest"] = w["latest_template"].format(
                month_name=mname, **{k: money(v) for k, v in metrics.items()}, **words)
        else:
            item["needs_update"] = True
        item["status"] = watch_status(item, (prev or {}).get("watch") or [])
        watch.append(item)
    unrecorded = []
    for u in args.unrecorded:
        amt, label = u.split("|", 1)
        unrecorded.append({"amount": float(amt), "label": label})
    obligations = [{"name": o, "status": "To confirm"} for o in cfg["obligations"]]

    # books readiness: every onboarding item not met is flagged; data items are re-checked
    readiness = None
    state_file = root / "finance/onboarding-state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        readiness = {r["id"]: {k: r.get(k) for k in ("id", "title", "status", "caveat", "reason")}
                     for r in state.get("readiness", []) if r.get("status") != "met"}
        if budget and "budget" in readiness:
            readiness.pop("budget")
        threshold = cfg.get("clearing_threshold", 1000)
        held = {a: account_total(bs, {a}, n)[idx] for a in cfg.get("payment_accounts", [])}
        big = {a: v for a, v in held.items() if abs(v) >= threshold}
        if big:
            readiness["payment_services"] = {
                "id": "payment_services", "title": "Payment services cleared each month", "status": "open",
                "caveat": "At month end the books show " + ", ".join(f"{money(v)} in {a}" for a, v in big.items()) +
                          ", income received online that is not yet fully recorded.", "reason": None}
        if unrecorded:
            readiness["unrecorded_income"] = {
                "id": "unrecorded_income", "title": "Money received is recorded", "status": "open",
                "caveat": f"About {money(sum(u['amount'] for u in unrecorded))} received is not yet recorded.",
                "reason": None}
        readiness = list(readiness.values())

    # earlier months changed since the last report? (months are not locked)
    history_change = None
    if prev and mon > 1 and prev["meta"]["month"] == f"{year}-{mon - 1:02d}":
        was, now = prev["plan"]["actual"], this_year[-2]
        if abs(now - was) >= 1:
            history_change = {"was": was, "now": now, "month": MONTHS[mon - 2],
                              "caveat": f"Figures for earlier months changed since last month's report: the year "
                                        f"through {MONTHS[mon - 2]} was {money(was)} {'ahead' if was >= 0 else 'short'} "
                                        f"then and is {money(now)} {'ahead' if now >= 0 else 'short'} now."}
    if history_change:
        readiness = (readiness or []) + [{"id": "history_changed", "title": "Earlier months changed",
                                          "status": "open", "caveat": history_change["caveat"], "reason": None}]

    # accounts that fell into a catch-all group; new ones need a person to look
    def catch_all(groups, sections_wanted):
        named = [g for g in groups if g["accounts"] != ["*"]]
        out = []
        for it in ytd_items:
            if it["section"] not in sections_wanted:
                continue
            codes = [code(x) for x in it["chain"]]
            if not any(any(a in codes for a in g["accounts"]) and not any(c in codes for c in g.get("exclude", []))
                       for g in named):
                out.append(it["name"])
        return sorted(set(out))
    in_catch_all = catch_all(cfg["income_groups"], INCOME) + catch_all(cfg["spending_groups"], EXPENSE)
    new_in_catch_all = sorted(set(in_catch_all) - set((prev or {}).get("catch_all_accounts", in_catch_all)))

    average_spending = round(total_sp / mon, 2)
    ly_now, ly_end = (last_year[mon - 1], last_year[-1]) if last_year else (None, None)
    t_out = top(EXPENSE)
    # Name the month's largest bill only when it is unusual for that account
    ytd_out = item_values(ytd_items, EXPENSE)
    prior_out = item_values(prior_items, EXPENSE)
    expense_keys = dict.fromkeys([*ytd_out, *prior_out])
    t_key = max(expense_keys, key=lambda k: abs(ytd_out.get(k, 0) - prior_out.get(k, 0))) if expense_keys else None
    account_ytd = ytd_out.get(t_key, 0)
    unusual = t_key is not None and t_out["amount"] > 0 and account_ytd > 0 and t_out["amount"] > 1.25 * (account_ytd / mon)
    # A month with no income recorded at all is not a bad month: the bookkeeper has not posted
    # it yet. Say so, and anchor the year on the month before, where the books are complete.
    unrecorded_month = came_in <= 0
    if unrecorded_month:
        before_name = MONTHS[mon - 2] if mon > 1 else None
        s1 = (f"{mname} is not yet recorded: no income has been entered and "
              + ("only some bills" if went_out > 0 else "no bills")
              + (f", so read the year through {before_name}." if before_name else "."))
        if before_name:
            through = this_year[-2]
            word = "ahead" if through >= 0 else "short"
            if last_year:
                ly_then = last_year[mon - 2]
                cmp = "better" if through >= ly_then else "worse"
                s2 = (f"The year through {before_name} is {money(through)} {word}, {cmp} than this point last "
                      f"year ({money(ly_then)} {'ahead' if ly_then >= 0 else 'short'}), and last year ended "
                      f"{money(ly_end)} {'ahead' if ly_end >= 0 else 'short'}.")
            else:
                s2 = f"The year through {before_name} is {money(through)} {word}."
        else:
            s2 = f"Last year ended {money(ly_end)} {'ahead' if ly_end >= 0 else 'short'}." if last_year else ""
    else:
        s1 = (f"{mname}: {signed_money(came_in)} recorded income and "
              f"{signed_money(went_out)} recorded spending"
              + (f", including {money(t_out['amount'])} for {t_out['label'].lower()}." if unusual else "."))
        word = "ahead" if this_year[-1] >= 0 else "short"
        cmp = ("better" if this_year[-1] >= ly_now else "worse") if last_year else ""
        if last_year:
            s2 = (f"That leaves us {money(this_year[-1])} {word} for the year, {cmp} than this point last year "
                  f"({money(ly_now)} {'ahead' if ly_now >= 0 else 'short'}), and last year ended "
                  f"{money(ly_end)} {'ahead' if ly_end >= 0 else 'short'}.")
        else:
            s2 = f"That leaves us {money(this_year[-1])} {word} for the year."
    s3 = cash_summary(round(bank[idx]), average_spending)
    if unrecorded_month:
        readiness = (readiness or []) + [{
            "id": "month_unrecorded", "title": f"{mname} not yet recorded", "status": "open",
            "caveat": f"No income has been entered for {mname} yet, so this month's figures and the year so far "
                      f"are incomplete until the books catch up.", "reason": None}]

    approval = cfg.get("approval")
    if approval not in (None, "none"):
        fail("config approval must be \"none\" or left out")
    set_aside = set_aside_money(cfg, bs, n, idx)

    hist = [[months[i], round(bank[i])] for i in range(n)
            if cfg["history_start"] <= months[i] <= args.month]
    report = {
        "meta": {"report": "Finance report",
                 "meeting_date": f"{MONTHS[mon % 12]} {year if mon < 12 else year + 1}",
                 "month": args.month, "month_name": mname,
                 "period_label": f"January to {mname} {year}",
                 "through": f"{mname} {[31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mon - 1]}, {year}",
                 "months": mon, "status": "draft", "prepared": args.prepared,
                 "reconstructed": args.sample,
                 "previous_report": f"../{prev_path.parent.name}/report.json"},
        "sources": [{"name": "QuickBooks Online", "pulled": args.prepared,
                     "method": "monthly balance sheet and profit and loss line rows; read-only"}],
        "short_answer": " ".join(part for part in (s1, s2, s3) if part),
        "short_answer_status": "draft: the treasurer approves or edits",
        "cash": {"bank": round(bank[idx]), "as_of": "",
                 "monthly_spending": average_spending, "status": "settled", "note": cfg.get("cash_note", "")},
        "this_month": {"came_in": came_in, "went_out": went_out, "top_in": top(INCOME), "top_out": t_out},
        "plan": {"budget": plan_cum[mon - 1] if plan_cum else None, "actual": round(ytd_net), "status": "settling",
                 "unrecorded": unrecorded,
                 "running": {"plan": plan_cum, "last_year": last_year, "this_year": this_year,
                             "last_year_label": str(year - 1), "this_year_label": str(year)}},
        "income": {"headline": f"Mostly {cfg['income_groups'][0]['name'].lower()}",
                   "parts": month_parts(cfg["income_groups"], inc_ytd, inc_prior)},
        "spending": {"headline": f"Mostly {cfg['spending_groups'][0]['name'].lower()}",
                     "parts": month_parts(cfg["spending_groups"], sp_ytd, sp_prior)},
        "watch": watch,
        "readiness": readiness,
        "history_change": history_change,
        "catch_all_accounts": in_catch_all,
        "obligations": obligations,
        "metrics": metrics,
        "cash_history": hist,
        "cash_history_note": cfg.get("cash_history_note", ""),
        "short_history": short_history,
        "full_years": cfg.get("long_view", {}).get("full_years", []),
        "full_years_note": cfg.get("long_view", {}).get("note", ""),
        "pressure": cfg.get("long_view", {}).get("pressure"),
    }
    if not prev:
        before = idx - 1
        report["previous"] = {"as_of": f"{MONTHS[(mon - 2) % 12]} end", "bank": round(bank[before]),
                              "ytd": this_year[-2] if mon > 1 else 0}
    report["cash"]["as_of"] = report["meta"]["through"]
    if unrecorded_month:
        report["this_month"]["unrecorded"] = True
    if approval:
        report["meta"]["approval"] = approval
    if set_aside is not None:
        report["cash"]["set_aside"] = set_aside
        report["cash"]["set_aside_total"] = sum(i["amount"] for i in set_aside)
    out = folder / args.month
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    todo = [w["title"] for w in watch if w.get("needs_update")]
    if new_in_catch_all:
        todo.append("New accounts in 'Everything else' since last report (confirm the grouping): " + ", ".join(new_in_catch_all))
    if history_change:
        todo.append(history_change["caveat"])
    if unrecorded_month:
        todo.append(f"{mname} looks unrecorded (no income entered); rebuild once the bookkeeper has posted it")
    print(json.dumps({"status": "ok", "written": str(out / "report.json"), "ytd_net": round(ytd_net),
                      "bank": round(bank[idx]), "came_in": came_in, "went_out": went_out,
                      "metrics": metrics, "needs_a_person": todo,
                      "previous_report": str(prev_path) if prev else None}, indent=1))


if __name__ == "__main__":
    main()
