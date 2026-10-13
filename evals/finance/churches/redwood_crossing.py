"""Redwood Crossing Church: reliable ledger rows, misleading connector summaries.

The convenience monthly figures count parent spending twice and report a loss,
while the actual rows and balance-sheet movement agree on a surplus. Repeating a
historical pull also reveals a late repair posting: the books are never locked.
"""

CHURCH = {
    "id": "redwood_crossing",
    "name": "Redwood Crossing Church",
    "company": "Redwood Crossing Church",
    "tradition": "",
    "governing_body": "Church Board",
    "books_start": "2024-01",
    "last_month": "2026-08",
    "cash_end": 68000,
    "context": [
        "The treasurer says earlier months are not locked, and late invoices sometimes change reports already shared.",
        "A budget export has not been provided; it cannot be read through this connector.",
    ],
    "connector": {
        "double_monthly": True,
        "revisions": [{"account": "6520 Repairs", "month": "2025-12", "amount": 2400, "after_pull": 2}],
    },
    "pl": [
        {"name": "4010 Member Giving", "section": "Income", "under": ["4000 GIVING"], "base": 17000, "trend": 0},
        {"name": "4300 Hall Rent", "section": "Income", "base": 1000, "trend": 0},
        {"name": "6010 Staff Compensation", "section": "Expenses", "under": ["6000 STAFF"], "base": 9800, "trend": 0},
        {"name": "6510 Utilities", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 1700, "trend": 0},
        {"name": "6520 Repairs", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 800, "trend": 0},
        {"name": "7510 Ministry Supplies", "section": "Expenses", "under": ["7500 MINISTRY"], "base": 1200, "trend": 0},
    ],
    "balance": [
        {"name": "1010 Checking", "kind": "bank", "plug": True},
        {"name": "1020 Savings", "kind": "bank", "balance": 22000},
        {"name": "3100 General Fund", "kind": "equity", "balance": 0},
    ],
}

TRUTH = {
    "everyday_bank": ["Checking", "Savings"],
    "set_aside": {},
    "largest_source": "Member Giving",
    "one_time": [],
    "skill": {
        "tell": [
            "The report rows support a surplus; the connector's zero expense summary and doubled monthly spending cannot support a loss claim.",
            "Figures identify the report and period they come from, and any changed pull is reconciled before presenting a result.",
        ],
        "ask": ["Ask for the budget export before making any claim about performance against budget."],
        "avoid": [
            "Uses the connector's monthlyBreakdown loss or zero totalExpenses as the church's result.",
            "If repeated pulls disagree, silently combines figures from the different versions or treats the old version as final.",
        ],
    },
    "checks": [
        {"id": "cash", "kind": "look_cash"},
        {"id": "ignore_misleading_summaries", "kind": "look_result",
         "why": "Authoritative rows agree with the ledger, despite zero summary expenses and a false monthly loss."},
        {"id": "prior_year_from_rows", "kind": "build_last_year",
         "why": "The prior-year line must follow balanced ledger movement, not double-counted monthly convenience data."},
        {"id": "bank_accounts", "kind": "draft_bank"},
    ],
}
