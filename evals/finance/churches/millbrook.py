"""Millbrook Episcopal Church: online giving that never quite lands, and a cleanup backlog.

What makes these books hard to read:
- Gatherpay Clearing and an online-giving clearing account carry balances: gifts received online
  are recorded late or only in part.
- Undeposited Funds holds checks and cash that were received but never deposited in the books.
  It sits under Other Current Assets, not under the bank accounts.
- Online gifts for July and August are still sitting in Gatherpay Clearing, so giving looks like it fell.
- The online-giving clearing account is below zero: payouts were booked, the gifts behind them were not.
- The connector restarts Net Income each August though the year runs January to December.
- The building's equity sits under a "Temporarily Restricted" label; it is not donor money.
- Payroll liabilities and deferred rent are below zero, which needs an explanation from the treasurer.
- Opening Balance Equity still holds an old correction.
- An amount is posted to an income heading instead of an account.
- "Ask My Accountant" and "Uncategorized Expense" collect spending nobody has sorted.
- The books moved to QuickBooks in July 2024 and there is no budget.
"""

CHURCH = {
    "id": "millbrook",
    "name": "Millbrook Episcopal Church",
    "company": "Millbrook Episcopal Church",
    "tradition": "Episcopal",
    "governing_body": "Vestry",
    "books_start": "2024-07",
    "last_month": "2026-08",
    "opening_retained": 0.0,
    "connector_reset": 8,
    "pl": [
        {"name": "4010 Pledge Payments", "section": "Income", "under": ["4000 PLEDGES AND OFFERINGS"], "base": 9500, "swing": 0.15},
        {"name": "4020 Plate Offerings", "section": "Income", "under": ["4000 PLEDGES AND OFFERINGS"], "base": 1200, "swing": 0.3},
        {"name": "4030 Online Gifts", "section": "Income", "under": ["4000 PLEDGES AND OFFERINGS"], "base": 1800, "swing": 0.2,
         "to": "2026-06"},  # July and August gifts are still sitting in Gatherpay Clearing
        {"name": "4000 PLEDGES AND OFFERINGS", "section": "Income", "base": 600, "swing": 0.5},
        {"name": "4210 Hall Rentals", "section": "Income", "under": ["4200 RENTALS"], "base": 1500},
        {"name": "6010 Rector Salary", "section": "Expenses", "under": ["6000 CLERGY"], "base": 6200, "trend": 0.02},
        {"name": "6020 Clergy Pension Plan", "section": "Expenses", "under": ["6000 CLERGY"], "base": 1100},
        {"name": "6510 Utilities", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 1500, "swing": 0.6},
        {"name": "6520 Maintenance", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 1000, "swing": 0.7},
        {"name": "7010 Diocesan Assessment", "section": "Expenses", "under": ["7000 DIOCESE"], "base": 1400},
        {"name": "7510 Office", "section": "Expenses", "under": ["7500 ADMINISTRATION"], "base": 450, "swing": 0.3},
        {"name": "7900 Ask My Accountant", "section": "Expenses",
         "posts": {"2026-02": 3200, "2026-05": 1450, "2026-07": 2600}},
        {"name": "7950 Uncategorized Expense", "section": "Expenses", "base": 250, "swing": 0.9, "from": "2025-06"},
    ],
    "balance": [
        {"name": "1000 Operating Checking", "kind": "bank", "plug": True},
        {"name": "1050 Petty Cash", "kind": "bank", "balance": 150},
        {"name": "Gatherpay Clearing", "kind": "bank", "balance": lambda y, m, i: 90.0 * (i % 4), "at": {"2026-07": 1900, "2026-08": 3400}},
        {"name": "Online Giving Clearing", "kind": "bank", "balance": lambda y, m, i: -2150.0 if i > 12 else 0.0},  # payouts booked, gifts not
        {"name": "1200 Undeposited Funds", "kind": "other_asset",
         "balance": lambda y, m, i: 400.0 * (i % 3), "at": {"2026-07": 5200, "2026-08": 6800}},
        {"name": "2100 Payroll Liabilities", "kind": "liability", "balance": lambda y, m, i: -1900.0 if i > 8 else 300.0},
        {"name": "2200 Credit Card", "kind": "liability", "balance": 800},
        {"name": "2300 Deferred Rental Revenue", "kind": "liability", "balance": lambda y, m, i: 3000.0 - 450.0 * i if i < 12 else -2400.0},
        {"name": "3000 Opening Balance Equity", "kind": "equity", "balance": 7350},
        {"name": "3100 Unrestricted Net Assets", "kind": "equity", "balance": 52000},
        {"name": "3200 Temporarily Restricted - Building Fund Balance", "kind": "equity", "balance": 380000},
    ],
}

TRUTH = {
    "everyday_bank": ["Operating Checking", "Petty Cash"],
    "set_aside": {"Gatherpay Clearing": "payment service", "Online Giving Clearing": "payment service"},
    "largest_source": "Pledge Payments",
    "one_time": [],
    "skill": {
        "tell": ["July and August have no online gift postings while payment clearing balances remain; recording lag is possible, so a giving decline is not established.",
                 "Gatherpay Clearing, Online Giving Clearing and Undeposited Funds have balances needing reconciliation; the report cannot establish actual receipts from those balances alone.",
                 "Spending nobody has sorted sits in Ask My Accountant and Uncategorized Expense."],
        "ask": ["Whether July and August giving is fully recorded, and which receipts or fees explain the clearing balances.",
                "What Ask My Accountant and Uncategorized Expense hold.",
                "Why payroll liabilities and deferred rental revenue are below zero.",
                "What is in Opening Balance Equity."],
        "avoid": ["Says giving dropped, or that members are giving less, because of July and August.",
                  "Claims actual giving did not fall or treats the clearing balance as proven missing gifts.",
                  "Says the fiscal year runs August to July.",
                  "Treats the 'Temporarily Restricted' building fund balance as donor-restricted cash the church holds."],
    },
    "checks": [
        {"id": "cash", "kind": "look_cash"},
        {"id": "result", "kind": "look_result"},
        {"id": "payment_services", "kind": "look_flag", "flag": "payment_services",
         "mentions": ["Gatherpay Clearing", "Online Giving Clearing"]},
        {"id": "undeposited_funds", "kind": "look_mentions", "terms": ["Undeposited"],
         "why": "Money received but never deposited in the books is the same problem as a payment service balance.",
         "gap": "Undeposited Funds sits outside the bank block, where only bank-block payment services are checked."},
        {"id": "negative_liabilities", "kind": "look_flag", "flag": "negative_liabilities", "mentions": ["Payroll", "Deferred"]},
        {"id": "opening_balance", "kind": "look_flag", "flag": "opening_balance_equity"},
        {"id": "heading_posting", "kind": "look_flag", "flag": "heading_postings", "mentions": ["PLEDGES AND OFFERINGS"]},
        {"id": "uncategorized", "kind": "look_flag", "flag": "uncategorized", "mentions": ["Ask My Accountant", "Uncategorized"],
         "why": "Spending nobody has sorted is a question for the treasurer before any report.",
         "gap": "Look does not name unsorted spending yet."},
        {"id": "bank_accounts", "kind": "draft_bank"},
        {"id": "plain_names", "kind": "draft_plain_names"},
        {"id": "no_one_time", "kind": "draft_one_time"},
    ],
}
