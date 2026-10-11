"""Lantern Hill Episcopal Church: a July-to-June year and a checking account in the red.

What makes these books hard to read:
- The fiscal year runs July to June, so "the year so far" in August is two months, not eight.
- The property insurance premium is paid once a year, in July, so July always looks terrible.
- Everyday cash dipped below zero at the end of August: checking is overdrawn.
"""

CHURCH = {
    "id": "lantern_hill",
    "name": "Lantern Hill Episcopal Church",
    "company": "Lantern Hill Episcopal Church",
    "tradition": "Episcopal",
    "governing_body": "Vestry",
    "books_start": "2024-07",
    "last_month": "2026-08",
    "fiscal_start": 7,
    "cash_end": -2300,  # everyday cash at the end of the last month
    "pl": [
        {"name": "4010 Pledges", "section": "Income", "under": ["4000 OFFERINGS"], "base": 8000, "swing": 0.25},
        {"name": "4020 Plate", "section": "Income", "under": ["4000 OFFERINGS"], "base": 900, "swing": 0.3},
        {"name": "4400 Diocesan Grant", "section": "Income", "base": 1000},
        {"name": "6010 Priest in Charge", "section": "Expenses", "under": ["6000 CLERGY"], "base": 4200},
        {"name": "6020 Church Pension Fund", "section": "Expenses", "under": ["6000 CLERGY"], "base": 750},
        {"name": "6510 Utilities", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 1300, "swing": 0.5},
        {"name": "6520 Repairs", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 600, "swing": 0.7},
        {"name": "6550 Property Insurance", "section": "Expenses", "under": ["6500 PROPERTY"],
         "posts": {"2024-07": 13500, "2025-07": 14000, "2026-07": 14600}},
        {"name": "7010 Diocesan Assessment", "section": "Expenses", "under": ["7000 DIOCESE"], "base": 900},
        {"name": "7510 Office", "section": "Expenses", "under": ["7500 OFFICE"], "base": 300},
    ],
    "balance": [
        {"name": "1010 Checking", "kind": "bank", "plug": True},
        {"name": "1020 Savings", "kind": "bank", "balance": 1500},
        {"name": "2100 Line of Credit", "kind": "liability", "balance": lambda y, m, i: 0.0 if i < 20 else 4000.0},
        {"name": "3100 Unrestricted Net Assets", "kind": "equity", "balance": 0.0},
    ],
}

TRUTH = {
    "everyday_bank": ["Checking", "Savings"],
    "set_aside": {},
    "largest_source": "Offerings",
    "one_time": [],
    "skill": {
        "tell": ["Everyday cash is below zero at the end of August: checking is overdrawn.",
                 "The year runs July to June, and July carries the yearly property insurance premium."],
        "ask": ["Whether the line of credit was drawn to cover the overdraft."],
        "avoid": ["Says the church has money in the bank at the end of August.",
                  "Calls July an unusually bad month without naming the yearly insurance premium."],
    },
    "checks": [
        {"id": "overdrawn_cash", "kind": "look_cash", "sign": True,
         "why": "Cash below zero must read as below zero, never as money in the bank.",
         "gap": "The cash finding prints the size of the balance without its sign."},
        {"id": "result", "kind": "look_result"},
        {"id": "fiscal_year_report", "kind": "build_fiscal_year",
         "why": "A July-to-June church's August report covers July and August.",
         "gap": "The report's year always runs from January."},
    ],
}

