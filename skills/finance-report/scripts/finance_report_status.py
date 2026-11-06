#!/usr/bin/env python3
"""Readiness check for the finance report. Reports what is set up and what is missing.

    python3 finance_report_status.py --church-folder . [--month YYYY-MM]

It cannot see the agent's connectors: the agent checks the QuickBooks
connection and company name itself (see references/quickbooks.md).
Prints JSON; "ready" is true only when nothing blocks a monthly run.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_report_data import MONTHS, fiscal_month, year_start_of  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--church-folder", default=".")
    ap.add_argument("--month")
    args = ap.parse_args(argv)
    root = Path(args.church_folder).resolve()
    checks, blocking = [], False

    def add(name, ok, detail, blocks=True):
        nonlocal blocking
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok and blocks:
            blocking = True

    church = root / "church.yaml"
    text = church.read_text() if church.exists() else ""
    add("church.yaml", bool(text), "found" if text else "missing: run onboarding first")
    tradition = re.search(r"^\s*tradition:\s*(.+)$", text, re.M)
    body = re.search(r"governing_body:\s*\n\s*label:\s*(.+)$", text, re.M)
    add("tradition", bool(tradition), tradition.group(1).strip() if tradition else "missing: ask the pastor")
    add("governing body", bool(body), body.group(1).strip() if body else "missing: ask (Vestry, Church Council)")

    brand = root / "brand.json"
    add("brand", True, "brand.json found; the report follows it" if brand.exists()
        else "no brand.json yet; the report uses the neutral theme until one exists", blocks=False)

    cfg_path = root / "finance/board/config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else None
    add("finance settings", cfg is not None, "found" if cfg else "missing: run first-time setup")
    if cfg:
        for key in ("bank_accounts", "income_groups", "spending_groups", "obligations", "history_start"):
            add(f"setting: {key}", bool(cfg.get(key)), "set" if cfg.get(key) else "missing")
        fs = fiscal_month(cfg.get("fiscal_year_start"))
        add("setting: the month the church's year starts", True,
            f"{MONTHS[fs - 1]}" if fs else "not saved yet: pull company info this month and build with "
            "--company-info; the build saves it", blocks=False)
        if args.month:
            pulls = root / cfg.get("report_folder", "finance/board") / args.month / "pulls"
            if not fs:
                ok = (pulls / "company-info.json").exists()
                add("pull: company-info.json", ok, "saved" if ok else "not yet pulled: needed once, to learn "
                    "the month the church's year starts")
            start = year_start_of(args.month, fs or 1)
            year = start[:4]
            has_budget = year in cfg.get("budget", {}) or cfg.get("budget_mode") == "none"
            add(f"budget {year}", has_budget, "set" if has_budget
                else "missing: upload a Budget versus Actuals export or choose no budget")
            first_month = args.month == start
            for f in ("balance-sheet.json", "pl-ytd.json") + (("pl-prior.json",) if not first_month else ()):
                add(f"pull: {f}", (pulls / f).exists(), "saved" if (pulls / f).exists() else "not yet pulled")

    checks.append({"check": "QuickBooks connection", "ok": None,
                   "detail": "the agent checks: tools present, company info matches the church name"})
    print(json.dumps({"status": "ready" if not blocking else "blocked", "ready": not blocking,
                      "checks": checks}, indent=1))


if __name__ == "__main__":
    main()
