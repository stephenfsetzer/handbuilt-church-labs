# Pulling from QuickBooks Online

Use the QuickBooks connector's read tools only. Call `company_info` first in
every session; the other tools require it.

## The three pulls

1. **Balance sheet by month.** `qbo_accounting_get_balance_sheet` (the JSON
   tool, not the `_text` one) with `start_date` = the first day of
   `config.history_start`, `end_date` = the report month's last day,
   `split_by` = `month`. The response is large and is saved to a file; copy
   that file to `pulls/balance-sheet.json`. The history must begin by
   December two years before the report year so last year's line can be
   drawn.
2. **Profit and loss, year to date.** `profit_loss_quickbooks_account` with
   `periodStart` = January 1 and `periodEnd` = the month's last day. Save as
   `pulls/pl-ytd.json`.
3. **Profit and loss, through last month.** Same tool, January 1 to the
   prior month's last day. Save as `pulls/pl-prior.json`. Skip in January.

If a response comes back inline instead of as a saved file, write it to the
pulls folder exactly as returned. Do not retype or summarize it.

## Connector traps

- **Summary fields are wrong.** `totalExpenses`, `netIncome`, and
  `monthlyBreakdown` double-count or come back as zero. The builder reads the
  line rows (`reportData.data.rows`) only.
- **Amounts posted to a heading.** A parent account can carry its own amount
  (for example $1,800 posted to "9000 Misc Expenses" itself). The builder
  adds these; its total check catches any it misses.
- **Opening balance plus change.** In a split balance sheet each account
  appears twice: a numbered row with the opening balance ("1002 Money
  Market") and an unnumbered row with the change since ("Money Market").
  The balance is their sum.
- **The connector's fiscal year.** It assumes a fiscal year starting in
  August, so its "quarters" end January, April, July, and October, and its
  Net Income row resets each August. Never read year-to-date or retained
  earnings from it directly. The builder takes each month's result as the
  change in Retained Earnings plus Net Income, which is right whatever the
  fiscal year, and checks it against the profit and loss.
- **The books move.** Bookkeepers post late entries. Always pull fresh; a
  report rebuilt later will not match the one delivered, which is why final
  reports keep their own `report.json`.

## What the connector cannot read

Budgets and classes. The budget goes into `config.json` once a year from the
QuickBooks Budget versus Actuals report (exported in the QuickBooks web app).
