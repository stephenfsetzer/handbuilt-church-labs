"""Synthetic church books, in the QuickBooks connector's own shapes, for the finance evals.

A church is a plain Python dict (see churches/*.py). This module turns it into what the
QuickBooks connector would return for that church: a balance sheet split by month and a
profit and loss for any period. Every church is fictional and every figure is generated.

The balance sheet always balances: the main checking account is the plug, so assets equal
liabilities plus equity in every month, and equity moves by exactly each month's result
unless the church closes its year into a fund (the fund close moves money inside equity).

Account spec, profit and loss side:
    {"name": "4010 Plate Offerings", "section": "Income", "under": ["4000 GIVING"],
     "base": 2200, "swing": 0.3, "trend": 0.04,          # monthly amount, seasonal wave, yearly growth
     "posts": {"2025-05": 25000},                         # one-off amounts on top
     "from": "2025-01", "to": "2026-08"}                  # months the account is used
An account whose name is also a heading in another account's "under" is an amount posted
to the heading itself.

Account spec, balance sheet side:
    {"name": "1010 Checking", "kind": "bank", "plug": True}
    {"name": "Gatherpay Clearing", "kind": "bank", "balance": 37.5, "at": {"2026-08": 1250}}
    kind: bank, other_asset, investment, liability, equity
    "not_cash": True marks an account filed among the banks that is not everyday cash.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SECTION_ORDER = ["Income", "Cost of Goods Sold", "Expenses", "Other Income", "Other Expenses"]
SECTION_ID = {"Income": "1", "Cost of Goods Sold": "2", "Expenses": "3", "Other Income": "5", "Other Expenses": "6"}
INCOME_SIDE = ("Income", "Other Income")
CODE = re.compile(r"^\d+(?:[-.]\d+)*[A-Za-z]?\s+")
# The QuickBooks connector returns at most this many profit and loss rows, with no warning.
CONNECTOR_ROW_LIMIT = 100


def key(y, m):
    return f"{y}-{m:02d}"


def months_between(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def parse(month):
    return int(month[:4]), int(month[5:7])


def strip_code(name):
    return CODE.sub("", name)


class Books:
    def __init__(self, church):
        self.church = church
        self.first = parse(church["books_start"])       # first month with activity
        self.last = parse(church["last_month"])         # the last complete month
        self.fiscal_start = church.get("fiscal_start", 1)
        # the month the connector restarts Net Income on the balance sheet; it need not be the
        # fiscal year start (the connector has been seen resetting in August for a calendar-year church)
        self.connector_reset = church.get("connector_reset", self.fiscal_start)
        self.pl_accounts = church["pl"]
        self.bs_accounts = church["balance"]
        self.opening_retained = church.get("opening_retained", 0.0)
        if "cash_end" in church:  # choose the opening balance so everyday cash ends where the church says
            self.opening_retained = 0.0
            _, bal = self.balances(self.last)
            now = sum(bal[a["name"]][-1] for a in self.bs_accounts if a["kind"] == "bank" and not a.get("not_cash"))
            self.opening_retained = church["cash_end"] - now

    # --- profit and loss ------------------------------------------------------------

    def amount(self, acct, y, m):
        k = key(y, m)
        if (y, m) < self.first or ("from" in acct and k < acct["from"]) or ("to" in acct and k > acct["to"]):
            return 0.0
        base = acct.get("base", 0)
        value = 0.0
        if base:
            salt = sum(map(ord, acct["name"])) % 12
            wave = math.sin((m + salt) / 12 * 2 * math.pi)
            trend = 1 + acct.get("trend", 0.03) * (y - 2025)
            value = base * trend * (1 + acct.get("swing", 0) * wave)
        value += acct.get("posts", {}).get(k, 0)
        return round(value, 2)

    def month_result(self, y, m):
        net = 0.0
        for a in self.pl_accounts:
            v = self.amount(a, y, m)
            net += v if a["section"] in INCOME_SIDE else -v
        return net

    def period_totals(self, start, end):
        tot = {a["name"]: 0.0 for a in self.pl_accounts}
        for y, m in months_between(start, end):
            for a in self.pl_accounts:
                tot[a["name"]] += self.amount(a, y, m)
        return tot

    def period_result(self, start, end):
        return sum(self.month_result(y, m) for y, m in months_between(start, end))

    def pl(self, start, end, limit=None):
        """Profit and loss from month start through month end, as the connector returns it."""
        tot = self.period_totals(start, end)
        rows = []

        def r(rid, typ, name, total, own=0.0):
            rows.append({"metadata": {"id": rid, "parentId": rid.rpartition(".")[0] or "0", "type": typ},
                         "cells": [{"name": "ACCOUNT_NAME", "value": name},
                                   {"name": "DETAIL_NATURAL_HOME_AMOUNT__TOTAL", "value": round(total, 2)},
                                   {"name": "DETAIL_NATURAL_HOME_AMOUNT__TOTAL_WITHOUT_SUBGROUPS",
                                    "value": round(own, 2)}]})

        section_totals = {}
        for sec in SECTION_ORDER:
            # QuickBooks leaves out accounts with nothing in the period
            accts = [a for a in self.pl_accounts if a["section"] == sec and abs(tot[a["name"]]) > 0.004]
            if not accts:
                continue
            # a tree of headings; leaves are accounts; a heading may carry its own amount
            tree = {}
            for a in accts:
                node = tree
                for h in a.get("under", []):
                    node = node.setdefault(h, {})
                node.setdefault(a["name"], {})
            own = {a["name"]: tot[a["name"]] for a in accts}

            def total(name, children):
                return own.get(name, 0.0) + sum(total(c, cc) for c, cc in children.items())

            sid = SECTION_ID[sec]
            sec_total = sum(total(c, cc) for c, cc in tree.items())
            section_totals[sec] = sec_total
            r(sid, ["GROUP", "SUMMARY"], sec, sec_total)

            def emit(prefix, children):
                for i, (name, sub) in enumerate(children.items(), 1):
                    rid = f"{prefix}.{i}"
                    if sub:
                        r(rid, ["GROUP", "SUMMARY"], name, total(name, sub), own.get(name, 0.0))
                        emit(rid, sub)
                        r(f"{rid}.{len(sub) + 1}", ["TOTAL"], f"Total for {name}", total(name, sub))
                    else:
                        r(rid, ["ITEM"], name, own.get(name, 0.0), own.get(name, 0.0))

            emit(sid, tree)
            if sec == "Expenses":
                inc = section_totals.get("Income", 0) - section_totals.get("Cost of Goods Sold", 0)
                r("4", ["FORMULA"], "Net Operating Income", inc - sec_total)
        r("7", ["FORMULA"], "Net Income", self.period_result(start, end))
        if limit and len(rows) > limit:
            rows = rows[:limit]  # the connector stops silently
        last_day = [31, 29 if end[0] % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][end[1] - 1]
        report = {"status": "success", "periodStart": f"{key(*start)}-01", "periodEnd": f"{key(*end)}-{last_day}",
                  "totalExpenses": 0, "netIncome": 0,  # the connector's summary fields are unreliable
                  "reportData": {"data": {"rows": rows}}}
        if self.church.get("connector", {}).get("double_monthly"):
            # Deliberately bad convenience data: expenses under a heading are counted
            # once at the parent and again at the children. Authoritative report rows
            # above remain correct. This is a connector error, not a ledger entry.
            monthly = []
            for y, m in months_between(start, end):
                income = sum(self.amount(a, y, m) for a in self.pl_accounts if a["section"] in INCOME_SIDE)
                expenses = sum(self.amount(a, y, m) * (2 if a.get("under") else 1)
                               for a in self.pl_accounts if a["section"] not in INCOME_SIDE)
                monthly.append({"month": key(y, m), "totalIncome": round(income, 2),
                                "totalExpenses": round(expenses, 2), "netIncome": round(income - expenses, 2)})
            report["monthlyBreakdown"] = monthly
        return report

    def snapshot(self, pull=1):
        """A consistent ledger after late postings, without modifying the original books.

        ``pull`` is the repeated-query ordinal, starting at one. Revisions are visible
        at ``after_pull`` and later. Both balance sheet and P&L from this snapshot share
        the revision, while the opening cash/equity stays fixed.
        """
        if pull < 1:
            raise ValueError("pull must start at one")
        revisions = [r for r in self.church.get("connector", {}).get("revisions", [])
                     if pull >= r.get("after_pull", 2)]
        if not revisions:
            return self
        church = deepcopy(self.church)
        church.pop("cash_end", None)
        church["opening_retained"] = self.opening_retained
        church.setdefault("connector", {}).pop("revisions", None)
        accounts = {a["name"]: a for a in church["pl"]}
        for revision in revisions:
            account = accounts[revision["account"]]
            posts = account.setdefault("posts", {})
            month = revision["month"]
            posts[month] = posts.get(month, 0) + revision["amount"]
        return Books(church)

    def connector_pl(self, start, end, split_by=None, pull=1, limit=CONNECTOR_ROW_LIMIT):
        """The connector's bounded P&L at a reproducible revision of the books."""
        if split_by not in (None, "", "month"):
            raise ValueError("unsupported profit and loss split")
        return self.snapshot(pull).pl(start, end, limit=limit)

    # --- balance sheet -----------------------------------------------------------------

    def balances(self, end):
        """Every balance sheet account's balance at each month end from the month before the books start."""
        before = (self.first[0] - 1, 12) if self.first[1] == 1 else (self.first[0], self.first[1] - 1)
        cols = list(months_between(before, end))
        fund_close = self.church.get("fund_close")  # {"into": name, "month": 1}
        re_name = "Retained Earnings"
        out = {a["name"]: [] for a in self.bs_accounts}
        out[re_name], out["Net Income"] = [], []
        retained, fiscal_ni, moved = self.opening_retained, 0.0, 0.0
        for i, (y, m) in enumerate(cols):
            if m == self.connector_reset and i:
                retained += fiscal_ni
                fiscal_ni = 0.0
            if fund_close and m == fund_close["month"] and i and retained:
                moved += retained  # the treasurer's closing entry: last year's result into the fund balance
                retained = 0.0
            fiscal_ni += self.month_result(y, m) if i else 0.0
            for a in self.bs_accounts:
                if a.get("plug"):
                    continue
                v = a.get("at", {}).get(key(y, m))
                if v is None and callable(a.get("balance")):
                    v = a["balance"](y, m, i)
                elif v is None:
                    v = a.get("balance", 0.0)
                if fund_close and a["name"] == fund_close["into"]:
                    v += moved
                out[a["name"]].append(round(v, 2))
            out[re_name].append(round(retained, 2))
            out["Net Income"].append(round(fiscal_ni, 2))
        # the plug: liabilities plus equity less every other asset
        plug = next(a for a in self.bs_accounts if a.get("plug"))
        for i in range(len(cols)):
            claims = sum(out[a["name"]][i] for a in self.bs_accounts if a["kind"] in ("liability", "equity"))
            claims += out[re_name][i] + out["Net Income"][i]
            others = sum(out[a["name"]][i] for a in self.bs_accounts
                         if a["kind"] in ("bank", "other_asset", "investment") and not a.get("plug"))
            out[plug["name"]].append(round(claims - others, 2))
        return cols, out

    def balance_sheet(self, end):
        cols, bal = self.balances(end)
        n = len(cols)

        def cell(v):
            return {"name": "x", "value": round(v, 2), "localizedValue": f"{v:,.2f}"}

        rows = []

        def row(name, vals, depth=0):
            rows.append({"cells": [{"id": "1", "name": "ACCOUNT_NAME", "value": name}] + [cell(v) for v in vals],
                         "depth": depth})

        def account(a):
            vals = bal[a["name"]]
            if CODE.match(a["name"]):
                # the connector prints a numbered account twice: its opening balance under the
                # number, and the change since then under the bare name
                opening = vals[0]
                row(a["name"], [opening] * n, 2)
                row(strip_code(a["name"]), [v - opening for v in vals], 2)
            else:
                row(a["name"], vals, 2)

        def block(kinds):
            for a in self.bs_accounts:
                if a["kind"] in kinds:
                    for h in a.get("headings_before", []):
                        row(h, [0.0] * n, 1)
                    account(a)

        row("Assets", [0.0] * n)
        row("Bank Accounts", [0.0] * n)
        block(("bank",))
        row("Other Current Assets", [0.0] * n)
        block(("other_asset", "investment"))
        row("Liabilities", [0.0] * n)
        block(("liability",))
        row("Equity", [0.0] * n)
        block(("equity",))
        row("Retained Earnings", bal["Retained Earnings"], 2)
        row("Net Income", bal["Net Income"], 2)
        return {"reportTitle": "Balance Sheet", "splitBy": "month",
                "displayColumns": [{"key": "ACCOUNT_NAME"}] + [{"key": f"{MON[m - 1]} {y}"} for y, m in cols],
                "reportData": {"rows": rows}}

    def company_info(self):
        months = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                  "October", "November", "December"]
        return {"companyName": self.church["company"], "legalName": self.church["company"], "country": "US",
                "fiscalYearStartMonth": months[self.fiscal_start - 1]}


def fiscal_year_start(books, y, m):
    """The first month of the fiscal year that month (y, m) falls in."""
    fs = books.fiscal_start
    return (y, fs) if m >= fs else (y - 1, fs)
