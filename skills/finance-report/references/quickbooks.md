# Pulling from QuickBooks Online

Use the QuickBooks connector's read tools only. Call `company_info` first in
every session; the other tools require it.

## The church's year

Many churches' years run January to December; some run July to June, or
from another month. The report's "year so far", its running chart, its
comparison with last year and every year label follow the church's own year.
The month it starts is saved in the settings as `fiscal_year_start` (1 for
January, 7 for July). Setup reads it from company info
(`fiscalYearStartMonth`). Settings saved before this was kept do not have
it: save the company info response as `company-info.json` in the month's
pulls folder and pass `--company-info` to the build, which reads the month,
saves it in the settings, and continues. With neither, the build stops
rather than assume January. If the settings and company info disagree, it
stops: ask the treasurer which is right.

Below, "the first day of the year" means the first day of the church's year
(January 1, or July 1, and so on).

## The pulls

0. **Company info.** `company_info`, saved as `company-info.json`. Needed for
   setup, and for any month whose settings do not yet say when the year
   starts.
1. **Balance sheet by month.** `qbo_accounting_get_balance_sheet` (the JSON
   tool, not the `_text` one) with `start_date` = the first day of
   `config.history_start`, `end_date` = the report month's last day,
   `split_by` = `month`. The response is large and is saved to a file; copy
   that file to `pulls/balance-sheet.json`. The history must begin by the
   month before last year began (December two years back, for a January
   year) so last year's line can be drawn.
2. **Profit and loss, year to date.** `profit_loss_quickbooks_account` with
   `periodStart` = the first day of the year and `periodEnd` = the month's
   last day. Save as `pulls/pl-ytd.json`.
3. **Profit and loss, through last month.** Same tool, the first day of the
   year to the prior month's last day. Save as `pulls/pl-prior.json`. Skip
   in the year's first month.

If a response comes back inline instead of as a saved file, write it to the
pulls folder exactly as returned. Do not retype or summarize it.

**Books that close into a fund balance.** Only when the build stops because
equity moved without a result: pull the profit and loss for the first day
of last year through each of its month ends (twelve pulls), and from the
first day of this year through each month end before the prior month
(pulls 2 and 3 cover the last two). Save each as `pulls/pl-through-YYYY-MM.json` and pass
it as `--pl-through YYYY-MM=pulls/pl-through-YYYY-MM.json`.

## Connector traps

- **Summary fields are wrong.** `totalExpenses`, `netIncome`, and
  `monthlyBreakdown` double-count or come back as zero. The builder reads the
  line rows (`reportData.data.rows`) only.
- **Amounts posted to a heading.** A parent account can carry its own amount
  (for example $1,800 posted to "7500 OFFICE" itself). The builder
  adds these; its total check catches any it misses.
- **Opening balance plus change.** In a split balance sheet each account
  appears twice: a numbered row with the opening balance ("1020
  Savings") and an unnumbered row with the change since ("Savings").
  The balance is their sum. Do not add them up yourself: `look` and
  `build` give each liability below zero with its balance and the first
  month it went below zero. Read those.
- **Retyped pulls.** Save every response exactly as returned. The scripts
  stop on a row whose cells do not match the columns, which is what a
  retyped or hand-cut pull usually has.
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
  partway through Expenses. Save the pull as returned and run `look` or
  `build` as usual: the script checks it, stops on a pull with 100 rows or
  rows that do not add up to their section totals, and records the refusal
  (`finance/onboarding/look-blocked.json`, or `blocked.json` in the month
  folder) so the cut-off stays visible. Tell the person in plain words and
  offer a shorter period or a QuickBooks export. The section totals in that
  record are correct and may be quoted, labeled as totals; never draft
  groups, accounts or findings from the cut-off pull's lines.
- **The first profit and loss may ask for a company profile.** On first use
  the connector can answer `profile_info_required` (industry and state).
  Filling these in is a write to QuickBooks. Never fill them in on your own:
  ask the pastor, name the two fields, and continue only with their yes.
- **The books move.** Bookkeepers post late entries. Always pull fresh; a
  report rebuilt later will not match the one delivered, which is why final
  reports keep their own `report.json`.

## QuickBooks' own report format

Some hosts read the books through QuickBooks' Accounting API instead of the
connector, for example Handbuilt's hosted runs. Their read tools return
QuickBooks' own report JSON (`Header`, `Columns`, `Rows`) under the same tool
names. Save those responses exactly as returned, like the connector's. The
builder reads both formats and runs the same checks on each. QuickBooks' own
reports have no 100-row limit and print each account once with its balance,
so the connector traps above about cut-off pulls and opening-plus-change rows
do not apply to them. The balance sheet must still be split by month.

## What the connector cannot read

Budgets and classes. The budget goes into `config.json` once a year from the
QuickBooks Budget versus Actuals report (exported in the QuickBooks web app).
