"""Wellspring Mission Church: books that started this year, mostly from the bank feed.

What makes these books hard to read:
- QuickBooks starts in February 2026, so a twelve-month pull covers seven months of activity.
- The bank feed drops much of what comes in and goes out into Uncategorized Income and
  Uncategorized Expense; the largest "source of income" is a holding account.
- Opening Balance Equity holds the starting bank balance.
- No budget, no history to compare with.
"""

CHURCH = {
    "id": "wellspring",
    "name": "Wellspring Mission Church",
    "company": "Wellspring Mission Church",
    "context": ["The pastor confirms this QuickBooks company began recording activity in February 2026. Earlier records are not available in the connected books."],
    "tradition": "",
    "governing_body": "Leadership Team",
    "books_start": "2026-02",
    "last_month": "2026-08",
    "opening_retained": 0.0,
    "pl": [
        {"name": "Uncategorized Income", "section": "Income", "base": 3800, "swing": 0.2},
        {"name": "4010 Tithes", "section": "Income", "under": ["4000 GIVING"], "base": 2600, "swing": 0.2},
        {"name": "4020 Online Giving", "section": "Income", "under": ["4000 GIVING"], "base": 900},
        {"name": "6010 Pastor Stipend", "section": "Expenses", "under": ["6000 STAFF"], "base": 3000},
        {"name": "6510 Rent", "section": "Expenses", "under": ["6500 MEETING SPACE"], "base": 1800},
        {"name": "Uncategorized Expense", "section": "Expenses", "base": 1300, "swing": 0.5},
        {"name": "7510 Supplies", "section": "Expenses", "under": ["7500 MINISTRY"], "base": 400, "swing": 0.4},
    ],
    "balance": [
        {"name": "1010 Checking", "kind": "bank", "plug": True},
        {"name": "3000 Opening Balance Equity", "kind": "equity", "balance": 18000},
    ],
}

TRUTH = {
    "everyday_bank": ["Checking"],
    "set_aside": {},
    "largest_source": "Giving",
    "one_time": [],
    "skill": {
        "tell": ["The books in QuickBooks only start in February 2026, so there is no full year yet.",
                 "Much of what came in and went out is still uncategorized, so the sources of income are not known yet."],
        "ask": ["What the uncategorized income and spending are.",
                "What Opening Balance Equity holds."],
        "avoid": ["Names Uncategorized Income as the church's main source of income.",
                  "Says how many months cash would last using twelve months of spending."],
    },
    "checks": [
        {"id": "cash", "kind": "look_cash"},
        {"id": "result", "kind": "look_result"},
        {"id": "months_of_spending", "kind": "look_months_of_spending",
         "why": "Seven months of spending spread over twelve makes cash look like it lasts far longer than it does.",
         "gap": "Look divides by the months pulled, not the months the books cover."},
        {"id": "short_books", "kind": "look_history_coverage",
         "why": "The pastor should hear that the books only start in February.",
         "gap": "Look does not say when the books start."},
        {"id": "uncategorized_not_a_source", "kind": "look_concentration_not", "name": "Uncategorized",
         "why": "A holding account is not a source of income.",
         "gap": "Concentration can name a holding account as the largest source."},
        {"id": "uncategorized", "kind": "look_flag", "flag": "uncategorized", "mentions": ["Uncategorized"],
         "gap": "Look does not name unsorted income or spending yet."},
        {"id": "opening_balance", "kind": "look_flag", "flag": "opening_balance_equity"},
    ],
}
