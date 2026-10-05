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

**Books that close into a fund balance.** Only when the build stops because
equity moved without a result: pull the profit and loss for January 1
through each month end of last year (twelve pulls), and this year through
each month end before the prior month (pulls 2 and 3 cover the last two). Save each as `pulls/pl-through-YYYY-MM.json` and pass
it as `--pl-through YYYY-MM=pulls/pl-through-YYYY-MM.json`.

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
  fiscal year, and checks it against the profit and loss. Books that close
  into a fund balance break this; use the `--pl-through` pulls above.
- **Profit and loss stops at 100 rows.** The connector returns at most 100
  line rows, with no cursor and no warning. Section totals stay correct, so
  a church with a large chart of accounts silently loses line items, usually
  partway through Expenses. If a pull has exactly 100 rows, or its rows do
  not add up to their section totals, treat it as cut off: stop and tell the
  person in plain words. Do not draft groups or findings from it.
- **The first profit and loss may ask for a company profile.** On first use
  the connector can answer `profile_info_required` (industry and state).
  Filling these in is a write to QuickBooks. Never fill them in on your own:
  ask the pastor, name the two fields, and continue only with their yes.
- **The books move.** Bookkeepers post late entries. Always pull fresh; a
  report rebuilt later will not match the one delivered, which is why final
  reports keep their own `report.json`.

## What the connector cannot read

Budgets and classes. The budget goes into `config.json` once a year from the
QuickBooks Budget versus Actuals report (exported in the QuickBooks web app).
