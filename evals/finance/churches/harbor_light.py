"""Harbor Light Lutheran Church: a chart of accounts too big for the connector.

What makes these books hard to read:
- Over a hundred profit and loss rows. The QuickBooks connector stops at 100 rows without
  saying so, and anything drafted from a cut-off pull is missing part of the books.
- Every program has its own heading and a handful of small accounts.
"""

AREAS = ["WORSHIP", "MUSIC", "EDUCATION", "YOUTH", "OUTREACH", "PROPERTY", "STAFF", "ADMINISTRATION"]
LINES = ["Supplies", "Printing", "Hospitality", "Travel", "Training", "Equipment", "Software", "Volunteers",
         "Contracted Help"]


def _chart():
    pl = [
        {"name": "4010 Envelope Offerings", "section": "Income", "under": ["4000 GIVING"], "base": 21000, "swing": 0.15},
        {"name": "4020 Online Giving", "section": "Income", "under": ["4000 GIVING"], "base": 6000, "swing": 0.1},
        {"name": "4030 Special Appeals", "section": "Income", "under": ["4000 GIVING"], "base": 1500, "swing": 0.9},
        {"name": "4110 Preschool Rent", "section": "Income", "under": ["4100 BUILDING USE"], "base": 4000},
        {"name": "4120 Community Group Rent", "section": "Income", "under": ["4100 BUILDING USE"], "base": 600},
        {"name": "4510 Dividends", "section": "Income", "under": ["4500 INVESTMENTS"], "base": 500, "swing": 0.5},
    ]
    for a, area in enumerate(AREAS):
        head = f"{6000 + 100 * a} {area}"
        for i, line in enumerate(LINES):
            base = 2400 if (area, line) == ("STAFF", "Contracted Help") else 180 + 35 * ((a * 7 + i) % 9)
            pl.append({"name": f"{6000 + 100 * a + 10 * (i + 1)} {area.title()} {line}", "section": "Expenses",
                       "under": [head], "base": base, "swing": 0.4})
    pl.append({"name": "6950 Pastor Compensation", "section": "Expenses", "under": ["6900 CALL"], "base": 9800})
    pl.append({"name": "6960 Portico Benefits", "section": "Expenses", "under": ["6900 CALL"], "base": 2600})
    pl.append({"name": "7010 Synod Mission Support", "section": "Expenses", "under": ["7000 MISSION"], "base": 2200})
    return pl


CHURCH = {
    "id": "harbor_light",
    "name": "Harbor Light Lutheran Church",
    "company": "Harbor Light Lutheran Church",
    "tradition": "Lutheran",
    "governing_body": "Church Council",
    "books_start": "2024-01",
    "last_month": "2026-08",
    "opening_retained": 0.0,
    "pl": _chart(),
    "balance": [
        {"name": "1010 Checking", "kind": "bank", "plug": True},
        {"name": "1020 Savings", "kind": "bank", "balance": 40000},
        {"name": "1500 Endowment", "kind": "investment", "balance": lambda y, m, i: 150000 + 400.0 * i},
        {"name": "3100 General Fund", "kind": "equity", "balance": 210000},
    ],
}

TRUTH = {
    "everyday_bank": ["Checking", "Savings"],
    "set_aside": {},
    "largest_source": "Envelope Offerings",
    "one_time": [],
    "connector_limit": True,
    "skill": {
        "tell": ["The profit and loss from QuickBooks was cut off at the connector's row limit, so its figures cannot be used yet.",
                 "What happens next: a shorter period or a QuickBooks export, and who can provide it."],
        "avoid": ["Presents income, spending, or a result for the twelve months from the cut-off pull."],
    },
    "checks": [
        {"id": "refuses_partial_pull", "kind": "look_refuses_truncated",
         "why": "A cut-off pull must stop the look; nothing drafted from it can be trusted."},
        {"id": "full_pull_cash", "kind": "look_cash",
         "why": "A complete pull of a big chart must still be read.",
         "gap": "Any profit and loss of 100 rows or more is refused, complete or not, and there is no export path."},
        {"id": "full_pull_result", "kind": "look_result",
         "gap": "Any profit and loss of 100 rows or more is refused, complete or not, and there is no export path."},
        {"id": "full_pull_draft", "kind": "draft_plain_names",
         "gap": "Any profit and loss of 100 rows or more is refused, complete or not, and there is no export path."},
    ],
}
