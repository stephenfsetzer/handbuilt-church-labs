"""Juniper Vale Fellowship: a normal weak summer, posting lag, and prepaid rent.

Prior years record online gifts in a December catch-up. This year's last two
months omit online gifts and ordinary rent. A separate prepaid tenancy releases
income every month while its liability falls, with no new cash for that income.
These observations support questions about completeness, not donor behavior.
"""


def _seasonal_giving():
    return {f"{year}-{month:02d}": 7000 if month <= 8 else 15000
            for year in range(2024, 2027) for month in range(1, 13)}


CHURCH = {
    "id": "juniper_vale",
    "name": "Juniper Vale Fellowship",
    "company": "Juniper Vale Fellowship",
    "tradition": "",
    "governing_body": "Trustees",
    "books_start": "2024-01",
    "last_month": "2026-08",
    "cash_end": 32000,
    "context": [
        "The treasurer's handoff says online gifts were historically posted net of fees in one December catch-up; the current summer payout reconciliation is unfinished.",
        "July and August hall-rental receipts have not been matched to invoices. The pastor has no complete list of payments received.",
        "A separate tenant paid three years of rent before these books begin. Prepaid Rental Revenue is released to Earned Prepaid Rent monthly; this is income with no new cash receipt.",
        "The trustees normally compare January through August with the same months last year because late-year giving is much stronger.",
    ],
    "pl": [
        {"name": "4010 Pledged Giving", "section": "Income", "under": ["4000 GIVING"], "posts": _seasonal_giving()},
        {"name": "4020 Online Gifts", "section": "Income", "under": ["4000 GIVING"],
         "posts": {"2024-12": 16800, "2025-12": 17400,
                   **{f"2026-{month:02d}": 1100 for month in range(1, 7)}}},
        {"name": "4300 Hall Rent", "section": "Income", "base": 1800, "trend": 0, "to": "2026-06"},
        {"name": "4400 Earned Prepaid Rent", "section": "Income", "base": 500, "trend": 0},
        {"name": "6010 Staff Compensation", "section": "Expenses", "under": ["6000 STAFF"], "base": 6800, "trend": 0},
        {"name": "6510 Utilities", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 1600, "trend": 0},
        {"name": "6520 Maintenance", "section": "Expenses", "under": ["6500 PROPERTY"], "base": 900, "trend": 0},
        {"name": "7510 Ministry Supplies", "section": "Expenses", "under": ["7500 MINISTRY"], "base": 1200, "trend": 0},
    ],
    "balance": [
        {"name": "1010 Checking", "kind": "bank", "plug": True},
        {"name": "1020 Savings", "kind": "bank", "balance": 9000},
        {"name": "Gatherpay Clearing", "kind": "bank", "balance": 0,
         "at": {"2026-07": 1600, "2026-08": 3300}, "not_cash": True},
        {"name": "2300 Prepaid Rental Revenue", "kind": "liability", "balance": lambda y, m, i: max(18000 - 500 * i, 0)},
        {"name": "3100 General Fund", "kind": "equity", "balance": 0},
    ],
}

TRUTH = {
    "everyday_bank": ["Checking", "Savings"],
    "set_aside": {"Gatherpay Clearing": "payment service"},
    "largest_source": "Pledged Giving",
    "one_time": [],
    "skill": {
        "tell": [
            "Online gifts and hall rent have no postings in July and August; unfinished reconciliation makes these months incomplete evidence of actual receipts.",
            "January through August was also weak last year, so compare matching periods before interpreting the summer deficit as a new crisis.",
            "Earned prepaid rent increases reported income while the prepaid liability falls, without bringing in new cash; cash and the operating result can therefore move differently.",
        ],
        "ask": [
            "Which July and August receipts are still missing, and when will online gifts, their fees, and hall rent be reconciled?",
            "Can the treasurer confirm the remaining prepaid rent schedule before using it in a cash forecast?",
        ],
        "avoid": [
            "Says donors stopped giving, tenants stopped paying, or actual receipts held steady based only on missing postings.",
            "Treats the December online catch-up as money all received in December or an exceptional gift.",
            "Presents a weak summer as a crisis without considering the matching prior-year period and incomplete recording.",
        ],
    },
    "checks": [
        {"id": "cash", "kind": "look_cash"},
        {"id": "result", "kind": "look_result"},
        {"id": "clearing_balance", "kind": "look_flag", "flag": "payment_services", "mentions": ["Gatherpay Clearing"]},
        {"id": "bank_accounts", "kind": "draft_bank"},
        {"id": "prepaid_rent_question", "kind": "look_mentions", "terms": ["prepaid", "earned rent"],
         "why": "Prepaid income explains part of the difference between operating results and cash; ask about the release schedule.",
         "gap": "Look does not identify a falling positive prepaid-rent liability or connect it with noncash rental income."},
    ],
}
