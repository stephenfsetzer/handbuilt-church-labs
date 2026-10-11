"""Read QuickBooks' own report JSON as the builder reads the connector's.

The QuickBooks connector returns reports in its own shape (`displayColumns`, `reportData`). A church whose
books are read through QuickBooks' Accounting API instead, such as a hosted run, has the API's own report
JSON (`Header`, `Columns`, `Rows`). These functions turn that into the connector's shape, so the builder's
reading, checks and traps stay in one place. Nothing is summed or rounded here: each account's own amount
and each subtotal are carried over as QuickBooks wrote them, and the builder checks them as usual.
"""
import re
from datetime import date

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Top-level profit and loss groups and the section names the connector prints.
PL_SECTIONS = {"Income": "Income", "COGS": "Cost of Goods Sold", "Expenses": "Expenses",
               "OtherIncome": "Other Income", "OtherExpenses": "Other Expenses"}


class NativeReportError(ValueError):
    pass


def is_native(d):
    return isinstance(d, dict) and "Header" in d and "Rows" in d and "Columns" in d


def _amount(text):
    if text in (None, ""):
        return 0.0
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise NativeReportError(f"QuickBooks amount {text!r} is not a number")
    return float(text)


def _meta(column, name):
    for item in column.get("MetaData") or []:
        if item.get("Name") == name:
            return item.get("Value")
    return None


def _money_columns(d):
    """The positions and month labels ('Aug 2026') of the report's money columns, without any Total column."""
    columns = d["Columns"]["Column"]
    if not columns or columns[0].get("ColType") != "Account":
        raise NativeReportError("the first QuickBooks report column must be the account")
    found = []
    for index, column in enumerate(columns[1:], 1):
        key, title = (_meta(column, "ColKey") or "").lower(), column.get("ColTitle") or ""
        if column.get("ColType") != "Money" or key == "total" or title.lower() == "total":
            continue
        end = _meta(column, "EndDate")
        if end:
            day = date.fromisoformat(end)
            label = f"{MONTH_ABBR[day.month - 1]} {day.year}"
        elif re.fullmatch(r"[A-Z][a-z]{2} \d{4}", title):
            label = title
        else:
            raise NativeReportError(f"cannot tell which month the QuickBooks column {title!r} covers")
        found.append((index, label))
    return found


def _cells(row):
    return (row.get("Header") or {}).get("ColData") or row.get("ColData") or []


def balance_sheet(d):
    """A balance sheet summarized by month, as the connector prints it split by month."""
    if d["Header"].get("ReportName") != "BalanceSheet":
        raise NativeReportError("expected a QuickBooks BalanceSheet report")
    columns = _money_columns(d)
    if not columns:
        raise NativeReportError("the balance sheet has no month columns; ask for it summarized by month")
    rows = []

    def add(cells, depth, blank=False):
        values = [0.0 if blank else _amount(cells[i]["value"]) if i < len(cells) else 0.0 for i, _ in columns]
        rows.append({"cells": [{"name": "ACCOUNT_NAME", "value": cells[0]["value"]}]
                     + [{"value": v} for v in values], "depth": depth})

    def walk(row, depth):
        cells = _cells(row)
        heading = row.get("type") == "Section" and not (cells and cells[0].get("id"))
        if cells and cells[0].get("value"):
            # An account; a parent account with its own amount; or a heading such as "Bank Accounts", which
            # the connector prints with no amount.
            add(cells, depth, blank=heading)
        for child in (row.get("Rows") or {}).get("Row") or []:
            walk(child, depth + 1)
        summary = (row.get("Summary") or {}).get("ColData") or []
        if heading and summary and summary[0].get("value"):
            add(summary, depth)  # "Total Bank Accounts", where the connector's bank block ends

    for top in (d["Rows"].get("Row") or []):
        walk(top, 0)
    return {"reportTitle": "Balance Sheet", "splitBy": "month", "source": "quickbooks-api",
            "displayColumns": [{"key": "ACCOUNT_NAME"}] + [{"key": label} for _, label in columns],
            "reportData": {"rows": rows}}


def profit_and_loss(d):
    """A profit and loss for one period, as the connector prints it: numbered rows with their totals."""
    header = d["Header"]
    if header.get("ReportName") != "ProfitAndLoss":
        raise NativeReportError("expected a QuickBooks ProfitAndLoss report")
    columns = _money_columns(d)
    total = next((i for i, c in enumerate(d["Columns"]["Column"]) if i and c.get("ColType") == "Money"
                  and ((_meta(c, "ColKey") or "").lower() == "total" or (c.get("ColTitle") or "").lower() == "total")), None)
    if total is None:
        if len(columns) != 1:
            raise NativeReportError("the profit and loss must be one period; ask for it summarized as a total")
        total = columns[0][0]
    rows = []

    def value(cells):
        return _amount(cells[total]["value"]) if total < len(cells) else 0.0

    def add(rid, parent, kind, name, amount, own=0.0):
        rows.append({"metadata": {"id": rid, "parentId": parent, "type": kind},
                     "cells": [{"name": "ACCOUNT_NAME", "value": name},
                               {"name": "DETAIL_NATURAL_HOME_AMOUNT__TOTAL", "value": round(amount, 2)},
                               {"name": "DETAIL_NATURAL_HOME_AMOUNT__TOTAL_WITHOUT_SUBGROUPS", "value": round(own, 2)}]})

    def walk(row, rid, parent):
        if row.get("type") == "Data":
            cells = row.get("ColData") or []
            add(rid, parent, ["ITEM"], cells[0]["value"], value(cells), value(cells))
            return
        cells, summary = _cells(row), (row.get("Summary") or {}).get("ColData") or []
        name = cells[0]["value"] if cells else ""
        add(rid, parent, ["GROUP", "SUMMARY"], name, value(summary) if summary else value(cells),
            value(cells) if cells else 0.0)
        children = (row.get("Rows") or {}).get("Row") or []
        for index, child in enumerate(children, 1):
            walk(child, f"{rid}.{index}", rid)
        if summary:
            add(f"{rid}.{len(children) + 1}", rid, ["TOTAL"], summary[0].get("value") or f"Total for {name}", value(summary))

    for index, top in enumerate(d["Rows"].get("Row") or [], 1):
        group, rid = top.get("group") or "", str(index)
        summary = (top.get("Summary") or {}).get("ColData") or []
        if group in PL_SECTIONS:
            children = (top.get("Rows") or {}).get("Row") or []
            add(rid, "0", ["GROUP", "SUMMARY"], PL_SECTIONS[group], value(summary) if summary else 0.0)
            for child_index, child in enumerate(children, 1):
                walk(child, f"{rid}.{child_index}", rid)
        elif summary:  # Gross Profit, Net Operating Income, Net Income
            add(rid, "0", ["FORMULA"], summary[0].get("value") or group, value(summary))
        else:
            raise NativeReportError(f"unexpected QuickBooks profit and loss section {group or '(unnamed)'!r}")
    return {"status": "success", "source": "quickbooks-api", "periodStart": header["StartPeriod"],
            "periodEnd": header["EndPeriod"], "reportData": {"data": {"rows": rows}}}
