"""Cedar Hollow Lutheran Church: fund accounting.

What makes these books hard to read:
- The treasurer closes each year's result into a fund balance in January, so equity moves
  without a result and last year's line on the balance sheet is wrong.
- Account numbers carry hyphen and letter parts ("5120C", "4010-10").
- Almost all income sits under one heading; the real largest source is one account under it.
- Three funds have not moved in over a year. One, the community meal fund, has gifts and
  costs running through income and spending every month while its balance stays frozen, so
  nobody can say from the books what it holds now.
- School payroll tax passes through the books: collected as income, paid as expense.
- A storm damaged the roof; insurance paid most of it back a month later.
"""

H_IN = "4000-10 GENERAL FUND RECEIPTS"

CHURCH = {
    "id": "cedar_hollow",
    "name": "Cedar Hollow Lutheran Church",
    "company": "Cedar Hollow Lutheran Church",
    "context": ["The treasurer confirms the separate Memorial Fund Savings bank account holds donor-restricted memorial gifts. The restriction and usable balances of the other fund-equity labels have not been verified against gift letters or shared costs."],
    "tradition": "Lutheran",
    "governing_body": "Church Council",
    "books_start": "2024-01",
    "last_month": "2026-08",
    "fund_close": {"into": "3010-10 General Fund Balance", "month": 1},
    "opening_retained": 0.0,
    "pl": [
        {"name": "4010-10 Envelope Offerings", "section": "Income", "under": [H_IN], "base": 12000, "swing": 0.2},
        {"name": "4020-10 Online Giving", "section": "Income", "under": [H_IN], "base": 2500, "swing": 0.1},
        {"name": "4030-10 Loose Plate", "section": "Income", "under": [H_IN], "base": 900, "swing": 0.4},
        {"name": "4050-10 Building Use", "section": "Income", "under": [H_IN], "base": 1200},
        {"name": "4600-10 Community Meal Gifts", "section": "Income", "base": 700, "swing": 0.5},
        {"name": "4700-10 School Payroll Tax Collected", "section": "Income", "base": 3000},
        {"name": "5110-10 Pastor Salary", "section": "Expenses", "under": ["5100-10 PERSONNEL"], "base": 6500, "trend": 0.02},
        {"name": "5120C Deacon Stipend", "section": "Expenses", "under": ["5100-10 PERSONNEL"], "base": 2800, "trend": 0.02},
        {"name": "5130D Deacon Housing", "section": "Expenses", "under": ["5100-10 PERSONNEL"], "base": 900, "trend": 0.0},
        {"name": "5140-10 Elmbridge Benefits", "section": "Expenses", "under": ["5100-10 PERSONNEL"], "base": 2100},
        {"name": "6110-10 Utilities", "section": "Expenses", "under": ["6100-10 PROPERTY"], "base": 1700, "swing": 0.5},
        {"name": "6120-10 Repairs", "section": "Expenses", "under": ["6100-10 PROPERTY"], "base": 900, "swing": 0.8},
        {"name": "7110-10 Synod Mission Support", "section": "Expenses", "under": ["7100-10 MISSION"], "base": 1100},
        {"name": "7510-10 Office", "section": "Expenses", "under": ["7500-10 ADMINISTRATION"], "base": 400, "swing": 0.3},
        {"name": "7600-10 Community Meal Supplies", "section": "Expenses", "base": 520, "swing": 0.3},
        {"name": "7700-10 School Payroll Tax Paid", "section": "Expenses", "base": 3000},
        {"name": "8100-10 Insurance Reimbursement", "section": "Other Income", "posts": {"2025-11": 18000}},
        {"name": "8200-10 Storm Damage Repairs", "section": "Other Expenses", "posts": {"2025-10": 21500}},
    ],
    "balance": [
        {"name": "1010-10 Operating Checking", "kind": "bank", "plug": True},
        {"name": "1020-10 Savings", "kind": "bank", "balance": lambda y, m, i: 22000 + 150 * i},
        {"name": "1030-10 Memorial Fund Savings", "kind": "bank", "balance": 12000},
        {"name": "2010-10 Payroll Liabilities", "kind": "liability", "balance": 2400},
        {"name": "3010-10 General Fund Balance", "kind": "equity", "balance": 46000},
        {"name": "3200-10 Memorial Fund", "kind": "equity", "balance": 12000},
        {"name": "3300-10 Organ Fund", "kind": "equity", "balance": 4500},
        {"name": "3400-10 Community Meal Fund", "kind": "equity", "balance": 9000},
    ],
}

# What a careful bookkeeper would tell the pastor about these books. Each check is scored
# against the scripts (and, in a skill run, against what Claude wrote for the pastor).
TRUTH = {
    "everyday_bank": ["Operating Checking", "Savings"],
    "set_aside": {"Memorial Fund Savings": "restricted"},
    "largest_source": "Envelope Offerings",
    "one_time": [{"year": 2025, "account": "8100-10 Insurance Reimbursement"},
                 {"year": 2025, "account": "8200-10 Storm Damage Repairs"}],
    "pass_through": ["4700-10 School Payroll Tax Collected", "7700-10 School Payroll Tax Paid"],
    "skill": {
        "tell": ["Everyday cash is about {cash}, in Operating Checking and Savings; the Memorial Fund Savings account is restricted money kept apart from it.",
                 "Envelope offerings are the largest single source of income (not just 'operating fund income' as a whole).",
                 "The storm damage cost and the insurance payment that followed it belong together and are one-time.",
                 "School payroll tax passes through the books: it is not the church's own income or spending."],
        "ask": ["Which funds are donor-restricted and what each truly holds now, including the community meal fund whose balance has not moved while its gifts and costs keep flowing.",
                "Whether the books close each year into a fund balance, which explains the January equity entries."],
        "avoid": ["States as fact how much the community meal fund holds or is owed.",
                  "Says the church lost money in January because of the year-end closing entry."],
    },
    "checks": [
        {"id": "cash", "kind": "look_cash"},
        {"id": "result", "kind": "look_result"},
        {"id": "concentration_child", "kind": "look_concentration",
         "why": "One heading holds most income; the board needs the account under it.",
         "gap": "Concentration looks under a heading only when it holds more than 80% of income."},
        {"id": "restricted_funds", "kind": "look_flag", "flag": "restricted_funds", "mentions": ["Memorial", "Organ", "Community Meal"]},
        {"id": "no_payment_flag", "kind": "look_no_flag", "flag": "payment_services"},
        {"id": "restricted_cash_set_aside", "kind": "draft_bank",
         "why": "Memorial Fund Savings holds restricted money, not everyday cash."},
        {"id": "plain_names", "kind": "draft_plain_names",
         "why": "Group names must not keep account-number fragments such as '-10' or a stray letter."},
        {"id": "one_time", "kind": "draft_one_time"},
        {"id": "fund_close_last_year", "kind": "build_last_year", "pl_through": True,
         "why": "With month-by-month pulls, last year's line must match last year's real result."},
        {"id": "fund_close_refused", "kind": "build_refuses_without_pl_through",
         "why": "Without them, the build must stop rather than chart a closing entry as a loss."},
        {"id": "pass_through_named", "kind": "look_mentions", "terms": ["pass-through", "passes through", "pass through"],
         "why": "School payroll tax is not the church's income or spending; it inflates both totals.",
         "gap": "Pass-through accounts are not recognized yet."},
    ],
}
