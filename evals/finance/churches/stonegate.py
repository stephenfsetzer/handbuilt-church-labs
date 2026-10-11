"""Stonegate Community Church: a good-looking result built on one-time money.

What makes these books hard to read:
- Spending runs ahead of giving every month, but one-time money hides it: a payroll loan
  forgiven, an employee retention credit, a bequest, and the sale of the parsonage, which
  falls inside the last twelve months.
- A brokerage account sits among the bank accounts under the firm's name only.
- The main checking account's name is all capitals, like a heading.
- Legal fees for a property question are filed with the building costs this year.
- An old checking account was closed last year; it held money before that, so history needs it.
- The church carries a mortgage.
- No denomination, so there are no tradition defaults to lean on.
"""

CHURCH = {
    "id": "stonegate",
    "name": "Stonegate Community Church",
    "company": "Stonegate Community Church",
    "tradition": "",
    "governing_body": "Board of Elders",
    "books_start": "2023-01",
    "last_month": "2026-08",
    "cash_end": 64000,  # everyday cash at the end of the last month
    "pl": [
        {"name": "4010 Tithes and Offerings", "section": "Income", "under": ["4000 GIVING"], "base": 14000, "swing": 0.15},
        {"name": "4020 Online Giving", "section": "Income", "under": ["4000 GIVING"], "base": 3000, "swing": 0.1},
        {"name": "4300 Facility Rental", "section": "Income", "base": 900},
        {"name": "6010 Lead Pastor", "section": "Expenses", "under": ["6000 STAFF"], "base": 7500, "trend": 0.03},
        {"name": "6020 Worship Leader", "section": "Expenses", "under": ["6000 STAFF"], "base": 3000, "trend": 0.03},
        {"name": "6030 Youth Director", "section": "Expenses", "under": ["6000 STAFF"], "base": 2500, "trend": 0.03},
        {"name": "6040 Payroll Taxes", "section": "Expenses", "under": ["6000 STAFF"], "base": 900},
        {"name": "6510 Utilities", "section": "Expenses", "under": ["6500 FACILITY"], "base": 1600, "swing": 0.5},
        {"name": "6520 Mortgage Interest", "section": "Expenses", "under": ["6500 FACILITY"], "base": 900, "trend": -0.03},
        {"name": "6530 Repairs", "section": "Expenses", "under": ["6500 FACILITY"], "base": 700, "swing": 0.8},
        {"name": "6540 Legal Fees", "section": "Expenses", "under": ["6500 FACILITY"],
         "posts": {"2026-03": 9400, "2026-05": 6100, "2026-06": 3800}},
        {"name": "7010 Missions", "section": "Expenses", "under": ["7000 MINISTRY"], "base": 1200},
        {"name": "7510 Office", "section": "Expenses", "under": ["7500 ADMIN"], "base": 600, "swing": 0.2},
        {"name": "8010 PPP Loan Forgiveness", "section": "Other Income", "posts": {"2024-03": 38500}},
        {"name": "8020 Employee Retention Credit", "section": "Other Income", "posts": {"2024-09": 26000}},
        {"name": "8030 Bequest", "section": "Other Income", "posts": {"2025-04": 50000}},
        {"name": "8040 Gain on Sale of Parsonage", "section": "Other Income", "posts": {"2025-10": 96000}},
    ],
    "balance": [
        {"name": "1010 LAKESHORE CHECKING", "kind": "bank", "plug": True},
        {"name": "1015 Old Checking - Harbor Savings", "kind": "bank",
         "balance": lambda y, m, i: 8000.0 if (y, m) < (2025, 6) else 0.0},
        {"name": "1020 Money Market", "kind": "bank", "balance": lambda y, m, i: 30000 + 60.0 * i},
        {"name": "1600 Edward Jones", "kind": "bank", "balance": lambda y, m, i: 185000 + 900.0 * i + 2500.0 * ((i * 7) % 5 - 2), "not_cash": True},
        {"name": "1700 Church Building", "kind": "other_asset", "balance": 600000},
        {"name": "2500 Mortgage - Lakeshore Bank", "kind": "liability", "balance": lambda y, m, i: 240000 - 1100.0 * i},
        {"name": "3100 Unrestricted Net Assets", "kind": "equity", "balance": 420000},
    ],
}

TRUTH = {
    "everyday_bank": ["LAKESHORE CHECKING", "Old Checking - Harbor Savings", "Money Market"],
    "set_aside": {"Edward Jones": "investment"},
    "largest_source": "Giving",
    "one_time": [{"year": 2024, "account": "8010 PPP Loan Forgiveness"},
                 {"year": 2024, "account": "8020 Employee Retention Credit"},
                 {"year": 2025, "account": "8030 Bequest"},
                 {"year": 2025, "account": "8040 Gain on Sale of Parsonage"}],
    "skill": {
        "tell": ["The last twelve months look ahead only because of the parsonage sale; without it, spending runs ahead of giving.",
                 "The Edward Jones account is an investment, not everyday cash.",
                 "LAKESHORE CHECKING is the church's main checking account.",
                 "The church carries a mortgage."],
        "ask": ["Whether this year's legal fees, filed with the building costs, are one-time.",
                "Whether the old checking account is closed."],
        "avoid": ["Calls the church financially healthy or growing on the strength of the twelve-month result.",
                  "Counts the Edward Jones balance as money for paying bills."],
    },
    "checks": [
        {"id": "cash", "kind": "look_cash",
         "why": "The brokerage account is not money the church pays bills from, and the main checking account is.",
         "gap": "The brokerage account is counted as everyday cash and the capitalized checking account is left out."},
        {"id": "result", "kind": "look_result"},
        {"id": "underlying_result", "kind": "look_mentions", "terms": ["one-time", "one time", "Gain on Sale", "Parsonage"],
         "why": "The last twelve months look ahead only because of the parsonage sale; the pastor must see that.",
         "gap": "Look reports the twelve-month result without naming one-time money inside it."},
        {"id": "bank_accounts", "kind": "draft_bank",
         "gap": "An investment account named only for its firm is drafted as a bank account."},
        {"id": "caps_checking_kept", "kind": "draft_bank_includes", "account": "LAKESHORE CHECKING",
         "why": "A bank account named in capitals is still a bank account, not a heading.",
         "gap": "A two-word bank account name in capitals, with no number in it, is read as a heading."},
        {"id": "one_time", "kind": "draft_one_time"},
        {"id": "debt", "kind": "look_mentions", "terms": ["Mortgage"],
         "why": "A mortgage is a standing obligation the board should see.",
         "gap": "Look does not mention loans yet."},
        {"id": "obligations_generic", "kind": "draft_obligations", "expect_count_at_least": 3},
    ],
}
