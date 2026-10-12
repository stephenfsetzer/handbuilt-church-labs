#!/usr/bin/env python3
"""Create a synthetic church folder for testing, with no real church's data.

Riverbend Lutheran Church is fictional. Its QuickBooks responses are
generated in the connector's exact shapes (opening and change rows on the
balance sheet, the connector's August-to-July fiscal reset, an amount posted
to an account heading) so the builder's traps are exercised.

    python3 make_fixture.py OUT_DIR
"""
import json
import math
import sys
from pathlib import Path

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# account: (section, parent heading, monthly base, seasonal swing)
INCOME = {
    "4010 Plate Offerings": ("4000 GIVING", 2200, 0.30),
    "4020 Pledge Payments": ("4000 GIVING", 7800, 0.10),
    "4030 Online Gifts": ("4000 GIVING", 1400, 0.20),
    "4110 Preschool Rent": ("4100 BUILDING USE", 3500, 0.0),
    "4510 Dividends": ("4500 INVESTMENT INCOME", 350, 0.5),
}
EXPENSE = {
    "6010 Pastor Compensation": ("6000 STAFF", 6900, 0.0),
    "6020 Musician": ("6000 STAFF", 1100, 0.0),
    "6510 Utilities": ("6500 BUILDING", 1900, 0.6),
    "6520 Repairs": ("6500 BUILDING", 1300, 0.9),
    "7010 Synod Mission Support": ("7000 MISSION", 1200, 0.0),
    "7510 Office Supplies": ("7500 OFFICE", 300, 0.3),
}
HEADING_OWN = ("7500 OFFICE", 450)  # posted to the heading itself, every month


def amount(base, swing, y, m, salt):
    wave = math.sin((m + salt) / 12 * 2 * math.pi)
    trend = 1 + 0.04 * (y - 2025)
    return round(base * trend * (1 + swing * wave), 2)


ESTATE_GIFT = ((2025, 5), "4910 Estate Gift", 25000.0)  # a one-time item, in Other Income


def other_income(y, m):
    return {ESTATE_GIFT[1]: ESTATE_GIFT[2]} if (y, m) == ESTATE_GIFT[0] else {}


def month_values(y, m):
    inc = {a: amount(b, s, y, m, i) for i, (a, (_, b, s)) in enumerate(INCOME.items())}
    exp = {a: amount(b, s, y, m, i + 3) for i, (a, (_, b, s)) in enumerate(EXPENSE.items())}
    if (y, m) == (2026, 3):
        exp["6520 Repairs"] += 9000  # a boiler repair
    return inc, exp


def months_between(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def cell(v):
    return {"name": "x", "value": round(v, 2), "localizedValue": f"{v:,.2f}"}


def balance_sheet(end):
    cols = list(months_between((2024, 12), end))
    opening_checking, opening_savings, opening_endow = 48000.0, 25000.0, 90000.0
    cum, rows_vals = 0.0, {"chk": [], "sav": [], "end": [], "re": [], "ni": []}
    fiscal_ni, re = 0.0, 150000.0
    for y, m in cols:
        if (y, m) != (2024, 12):
            inc, exp = month_values(y, m)
            net = sum(inc.values()) + sum(other_income(y, m).values()) - sum(exp.values()) - HEADING_OWN[1]
        else:
            net = 0.0
        if m == 8:  # the connector's fiscal year resets each August
            re += fiscal_ni
            fiscal_ni = 0.0
        fiscal_ni += net
        cum += net
        rows_vals["chk"].append(cum)
        rows_vals["sav"].append(0.5 * len(rows_vals["sav"]))
        rows_vals["end"].append(120.0 * len(rows_vals["end"]))
        rows_vals["re"].append(re)
        rows_vals["ni"].append(fiscal_ni)
    n = len(cols)

    def row(name, vals, depth):
        return {"cells": [{"id": "1", "name": "ACCOUNT_NAME", "value": name}] + [cell(v) for v in vals], "depth": depth}

    rows = [
        row("Assets", [0] * n, 0), row("Bank Accounts", [0] * n, 0),
        row("CASH", rows_vals["chk"], 0),
        row("Checking - First Bank 1111", rows_vals["chk"], 3),
        row("Stripe", [37.5 * (i % 3) for i in range(n - 1)] + [1250.0], 0),  # uncleared at the last month
        row("Old Checking 9999", [0.0] * n, 0),
        row("Savings - First Bank 2222", rows_vals["sav"], 3),
        row("1010 Checking - First Bank 1111", [opening_checking] * n, 3),
        row("1020 Savings - First Bank 2222", [opening_savings] * n, 3),
        row("ELCA Endowment Fund", rows_vals["end"], 3),
        row("1500 ELCA Endowment Fund", [opening_endow] * n, 3),
        row("Accounts Receivable", [0] * n, 0),
        row("Retained Earnings", rows_vals["re"], 2),
        row("Net Income", rows_vals["ni"], 2),
    ]
    return {"reportTitle": "Balance Sheet", "splitBy": "month",
            "displayColumns": [{"key": "ACCOUNT_NAME"}] + [{"key": f"{MON[m - 1]} {y}"} for y, m in cols],
            "reportData": {"rows": rows}}


def pl(year, upto, start=None):
    """Profit and loss from start (default January of year) through month upto of year."""
    start = start or (year, 1)
    inc_tot, exp_tot, oth_tot, count = {}, {}, {}, 0
    for y, m in months_between(start, (year, upto)):
        inc, exp = month_values(y, m)
        for k, v in inc.items():
            inc_tot[k] = inc_tot.get(k, 0) + v
        for k, v in exp.items():
            exp_tot[k] = exp_tot.get(k, 0) + v
        for k, v in other_income(y, m).items():
            oth_tot[k] = oth_tot.get(k, 0) + v
        count += 1
    own = HEADING_OWN[1] * count
    rows = []

    def r(rid, parent, typ, name, total, own_amt=0):
        rows.append({"metadata": {"id": rid, "parentId": parent, "type": typ},
                     "cells": [{"name": "ACCOUNT_NAME", "value": name},
                               {"name": "DETAIL_NATURAL_HOME_AMOUNT__TOTAL", "value": round(total, 2)},
                               {"name": "DETAIL_NATURAL_HOME_AMOUNT__TOTAL_WITHOUT_SUBGROUPS", "value": round(own_amt, 2)}]})

    def section(sid, title, accounts, table, own_heading=None):
        heads = {}
        for a, (h, _, _) in accounts.items():
            heads.setdefault(h, []).append(a)
        sec_total = sum(table.values()) + (own if own_heading else 0)
        r(sid, "0", ["GROUP", "SUMMARY"], title, sec_total)
        for gi, (h, accts) in enumerate(heads.items(), 1):
            gid = f"{sid}.{gi}"
            h_own = own if own_heading == h else 0
            r(gid, sid, ["GROUP", "SUMMARY"], h, sum(table[a] for a in accts) + h_own, h_own)
            for ai, a in enumerate(accts, 1):
                r(f"{gid}.{ai}", gid, ["ITEM"], a, table[a], table[a])
            r(f"{gid}.{len(accts) + 1}", gid, ["TOTAL"], f"Total for {h}", sum(table[a] for a in accts) + h_own)
        return sec_total

    ti = section("1", "Income", INCOME, inc_tot)
    te = section("3", "Expenses", EXPENSE, exp_tot, own_heading=HEADING_OWN[0])
    r("4", "0", ["FORMULA"], "Net Operating Income", ti - te)
    if oth_tot:
        r("5", "0", ["GROUP", "SUMMARY"], "Other Income", sum(oth_tot.values()))
        for i, (k, v) in enumerate(oth_tot.items(), 1):
            r(f"5.{i}", "5", ["ITEM"], k, v, v)
    last = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][upto - 1]
    return {"status": "success", "periodStart": f"{start[0]}-{start[1]:02d}-01", "periodEnd": f"{year}-{upto:02d}-{last}",
            "totalExpenses": 0, "netIncome": 0,  # the connector's summary fields are unreliable
            "reportData": {"data": {"rows": rows}}}


# --- the same books in QuickBooks' own report JSON (the Accounting API, as a hosted run reads them) ------------

def _money(v):
    return f"{v:.2f}"


def native_balance_sheet(end):
    """The balance sheet summarized by month, as QuickBooks' Reports API returns it: one row per account
    with its true balance, nested sections with subtotals, and Net Income resetting each January."""
    cols = list(months_between((2024, 12), end))
    connector = {r["cells"][0]["value"]: [c["value"] for c in r["cells"][1:]]
                 for r in balance_sheet(end)["reportData"]["rows"]}
    cum = connector["Checking - First Bank 1111"]  # the change row carries the running result
    december = {y: cum[i] for i, (y, m) in enumerate(cols) if m == 12}
    net_income = [cum[i] - december.get(y - 1, cum[i]) for i, (y, m) in enumerate(cols)]
    retained = [150000.0 + c - ni for c, ni in zip(cum, net_income)]

    def both(name):  # the connector's opening row plus its change row: the account's balance
        return [a + b for a, b in zip(connector[name], connector[name.split(" ", 1)[1]])]
    accounts = {"1010 Checking - First Bank 1111": both("1010 Checking - First Bank 1111"),
                "1020 Savings - First Bank 2222": both("1020 Savings - First Bank 2222"),
                "1500 ELCA Endowment Fund": both("1500 ELCA Endowment Fund"),
                "Stripe": connector["Stripe"], "Old Checking 9999": connector["Old Checking 9999"]}

    def data(name, values, ident=None):
        first = {"value": name, **({"id": ident} if ident else {})}
        return {"type": "Data", "ColData": [first] + [{"value": _money(v)} for v in values]}

    def section(title, group, rows, values):
        return {"type": "Section", "group": group,
                "Header": {"ColData": [{"value": title}] + [{"value": ""} for _ in values]},
                "Rows": {"Row": rows},
                "Summary": {"ColData": [{"value": f"Total {title}"}] + [{"value": _money(v)} for v in values]}}

    def add(*series):
        return [sum(parts) for parts in zip(*series)]
    bank = [data(name, accounts[name], str(i)) for i, name in enumerate(accounts, 1)]
    bank_total = add(*accounts.values())
    assets = section("Assets", "TotalAssets", [section("Bank Accounts", "BankAccounts", bank, bank_total)], bank_total)
    equity_total = add(retained, net_income)
    equity = section("Equity", "Equity", [data("Retained Earnings", retained, "40"), data("Net Income", net_income)],
                     equity_total)
    other = [a - e for a, e in zip(bank_total, equity_total)]  # what the fixture's liabilities hold
    liabilities = section("Liabilities", "Liabilities", [data("Other Liabilities", other, "30")], other)
    both_sides = section("Liabilities and Equity", "TotalLiabilitiesAndEquity", [liabilities, equity], bank_total)
    columns = [{"ColTitle": "", "ColType": "Account", "MetaData": [{"Name": "ColKey", "Value": "account"}]}]
    for y, m in cols:
        last = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        columns.append({"ColTitle": f"{MON[m - 1]} {y}", "ColType": "Money",
                        "MetaData": [{"Name": "StartDate", "Value": f"{y}-{m:02d}-01"},
                                     {"Name": "EndDate", "Value": f"{y}-{m:02d}-{last}"},
                                     {"Name": "ColKey", "Value": f"{MON[m - 1]} {y}"}]})
    return {"Header": {"ReportName": "BalanceSheet", "StartPeriod": "2024-12-01",
                       "EndPeriod": f"{end[0]}-{end[1]:02d}-{[31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][end[1] - 1]}",
                       "SummarizeColumnsBy": "Month", "ReportBasis": "Accrual", "Currency": "USD",
                       "Option": [{"Name": "NoReportData", "Value": "false"}]},
            "Columns": {"Column": columns}, "Rows": {"Row": [assets, both_sides]}}


def native_pl(year, upto, start=None):
    """Profit and loss for one period, as QuickBooks' Reports API returns it with a Total column."""
    start = start or (year, 1)
    totals, count = {}, 0
    for y, m in months_between(start, (year, upto)):
        inc, exp = month_values(y, m)
        for k, v in {**inc, **exp, **other_income(y, m)}.items():
            totals[k] = totals.get(k, 0) + v
        count += 1
    own = HEADING_OWN[1] * count
    ids = iter(range(100, 1000))

    def data(name):
        return {"type": "Data", "ColData": [{"value": name, "id": str(next(ids))}, {"value": _money(totals[name])}]}

    def group(heading, names, heading_own=0.0):
        value = sum(totals[n] for n in names) + heading_own
        return value, {"type": "Section",
                       "Header": {"ColData": [{"value": heading, "id": str(next(ids))},
                                              {"value": _money(heading_own) if heading_own else ""}]},
                       "Rows": {"Row": [data(n) for n in names]},
                       "Summary": {"ColData": [{"value": f"Total {heading}"}, {"value": _money(value)}]}}

    def section(title, key, accounts, own_heading=None):
        heads = {}
        for name, (heading, _, _) in accounts.items():
            heads.setdefault(heading, []).append(name)
        made = [group(h, names, own if h == own_heading else 0.0) for h, names in heads.items()]
        value = sum(v for v, _ in made)
        return value, {"type": "Section", "group": key, "Header": {"ColData": [{"value": title}, {"value": ""}]},
                       "Rows": {"Row": [row for _, row in made]},
                       "Summary": {"ColData": [{"value": f"Total {title}"}, {"value": _money(value)}]}}

    def formula(key, title, value):
        return {"type": "Section", "group": key, "Summary": {"ColData": [{"value": title}, {"value": _money(value)}]}}
    income, income_row = section("Income", "Income", INCOME)
    expenses, expense_row = section("Expenses", "Expenses", EXPENSE, own_heading=HEADING_OWN[0])
    rows = [income_row, formula("GrossProfit", "Gross Profit", income), expense_row,
            formula("NetOperatingIncome", "Net Operating Income", income - expenses)]
    others = {k: v for k, v in totals.items() if k == ESTATE_GIFT[1]}
    other = sum(others.values())
    if others:
        rows.append({"type": "Section", "group": "OtherIncome",
                     "Header": {"ColData": [{"value": "Other Income"}, {"value": ""}]},
                     "Rows": {"Row": [data(k) for k in others]},
                     "Summary": {"ColData": [{"value": "Total Other Income"}, {"value": _money(other)}]}})
        rows.append(formula("NetOtherIncome", "Net Other Income", other))
    rows.append(formula("NetIncome", "Net Income", income - expenses + other))
    last = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][upto - 1]
    return {"Header": {"ReportName": "ProfitAndLoss", "StartPeriod": f"{start[0]}-{start[1]:02d}-01",
                       "EndPeriod": f"{year}-{upto:02d}-{last}", "SummarizeColumnsBy": "Total",
                       "ReportBasis": "Accrual", "Currency": "USD",
                       "Option": [{"Name": "NoReportData", "Value": "false"}]},
            "Columns": {"Column": [{"ColTitle": "", "ColType": "Account", "MetaData": [{"Name": "ColKey", "Value": "account"}]},
                                   {"ColTitle": "Total", "ColType": "Money", "MetaData": [{"Name": "ColKey", "Value": "total"}]}]},
            "Rows": {"Row": rows}}


def main(out, short=False):
    """Write the synthetic church. short=True: books that start in January 2026."""
    out = Path(out)
    board = out / "finance/board"
    board.mkdir(parents=True, exist_ok=True)
    (out / "church.yaml").write_text(
        "church:\n  name: Riverbend Lutheran Church\n  short_name: Riverbend\n  tradition: Lutheran\n"
        "leadership:\n  governing_body:\n    label: Church Council\n    officers:\n"
        "    - name: Pat Example\n      role: Treasurer\n")
    budget_net = [1100.0] * 12
    config = {
        "report_folder": "finance/board", "history_start": "2024-12",
        "bank_accounts": ["Checking - First Bank 1111", "Savings - First Bank 2222"],
        "endowment_accounts": ["ELCA Endowment Fund"],
        "labels": {"4020": "Pledge payments", "6520": "Repairs"},
        "income_groups": [
            {"name": "Member giving", "note": "Plate, pledges, and online gifts", "accounts": ["4000"]},
            {"name": "Preschool rent", "note": "Weekday use of the building", "accounts": ["4100"]},
            {"name": "Investments", "note": "Endowment dividends", "accounts": ["*"]}],
        "spending_groups": [
            {"name": "Staff", "note": "Pastor and musician", "accounts": ["6000"]},
            {"name": "The building", "note": "Utilities and repairs", "accounts": ["6500"]},
            {"name": "Mission support", "note": "Shared with the synod", "accounts": ["7000"]},
            {"name": "Everything else", "note": "Office and other", "accounts": ["*"]}],
        "budget": {"2026": {"monthly_net": budget_net, "monthly_building": [3300.0] * 12}},
        "metrics": {"building_over_plan": {"accounts": ["6500"], "plan": "monthly_building"}},
        "cash_note": "", "cash_history_note": "Synthetic test data.",
        "long_view": {"full_years": [{"year": 2025, "result": 25200, "reported": 50200,
                                      "one_time": {"amount": 25000, "label": "estate gift"}}],
                      "pressure": {"question": "Does giving cover staff?", "answer": "Yes, with room to spare.",
                                   "series": [{"name": "Member giving", "role": "positive", "values": {"2025": 138000}},
                                              {"name": "Staff", "role": "attention", "values": {"2025": 96000}}],
                                   "note": "Synthetic test data."}},
        "obligations": ["Payroll tax filings", "Portico benefits", "Synod mission support", "Property insurance"],
    }
    if short:
        config["history_start"] = "2026-01"
        config["long_view"] = {}
    (board / "config.json").write_text(json.dumps(config, indent=2))
    for month in (7, 8):
        pulls = board / f"2026-{month:02d}" / "pulls"
        pulls.mkdir(parents=True, exist_ok=True)
        (pulls / "balance-sheet.json").write_text(json.dumps(balance_sheet((2026, month))))
        (pulls / "pl-ytd.json").write_text(json.dumps(pl(2026, month)))
        (pulls / "pl-prior.json").write_text(json.dumps(pl(2026, month - 1)))
    setup = out / "setup-pulls"
    setup.mkdir(exist_ok=True)
    (setup / "pl-12m.json").write_text(json.dumps(pl(2026, 8, start=(2025, 9))))
    (setup / "pl-2025.json").write_text(json.dumps(pl(2025, 12)))
    (setup / "budget-vs-actuals-2026.csv").write_text(bva_csv())
    return out


def bva_csv():
    """A QuickBooks Budget vs. Actuals export: four columns per month, then a total."""
    months = [f"{m} 2026" for m in MON]
    head = [""] + [x for m in months for x in (m, "", "", "")] + ["Total", "", "", ""]
    sub = [""] + ["Actual", "Budget", "Over budget by", "Percent of budget"] * 13
    def line(name, monthly):
        cells = [name]
        for v in monthly:
            cells += ["", f"{v:,.2f}", "", ""]
        return cells + ["", f"{sum(monthly):,.2f}", "", ""]
    rows = [["Budget vs. Actuals: FY26"], ["January-December, 2026"], [], head, sub,
            line("Total for 6000 STAFF", [8300.0] * 12),
            line("Total for 6500 BUILDING", [3300.0] * 12),
            line("Net Income", [1100.0] * 12)]
    import csv, io
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


if __name__ == "__main__":
    print(main(sys.argv[1], short="--short" in sys.argv))
