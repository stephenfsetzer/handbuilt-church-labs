# The report shape, version 1.0

Fixed on September 26, 2026. The renderer stamps `shape_version` into every
receipt.

## Page 1: where we stand this month

- Header: church logo or mark, "Where we stand: <Month>", the meeting, draft
  or final, and the one color key (positive color means ahead, attention
  color means short).
- The short answer.
- Since last month: bank cash, year so far, money in this month, money out
  this month.
- 1. Can we pay our bills? Months-of-spending boxes, last month marked.
- 2. Are we on plan? Running total: plan, last year, this year.
- 3. Where does our money come from? One split bar, year to date, with
  this month beside each part.
- 4. Where does it go? The same for spending.

## Page 2: watch list and the longer view

- Watch list: item, status, latest, next step. Obligations row.
- 5. Is our cash growing or shrinking? Month-end bank cash since the history
  start.
- 6. How have whole years gone? (updated yearly)
- 7. The pressure question, the largest income source against the largest
  cost area. (updated yearly)
- How to read this report, and sources.

## What a church may change (in its config and brand)

Brand colors, type, and logo; the board's name (from `church.yaml`); the
account groups and their plain names (at most five a side); the watch-list
items; the obligations; the pressure question's two series.

## What a church may not change

The questions, their wording and order, the chart forms, the one color
meaning, two pages at most, and the rule that every figure names its source.
A change to any of these is a new shape version, not a per-church setting.

## Optional config keys (added in 0.8.1)

Both keys are absent by default, and a report built without them is unchanged.

- `"approval": "none"` is for a report with no approval step, such as one
  built by the hosted Handbuilt app. `report.json` records
  `meta.approval = "none"`, and the header prints "Books through <date>" in
  place of "Draft for review" or "Final". No other text calls the report a
  draft in that mode.
- `"set_aside_accounts"` lists money the church holds that is not everyday
  cash: `[{"account": "<balance sheet account>", "name": "Memorial Fund",
  "kind": "restricted"}]`, where `account` is written the way `bank_accounts`
  entries are, and `kind` is `restricted`, `designated`, `investment`, or
  `in_transit`. `report.json` gets `cash.set_aside`, a list of
  `{name, kind, amount}` at the report month end, and `cash.set_aside_total`.
  Question 1 lists it by name, grouped by kind, as money not counted in bank
  cash. It is never added to or taken from the bank figure, and months of
  spending stay based on everyday money only. An account may not be in both
  `bank_accounts` and `set_aside_accounts`, and an account missing from the
  balance sheet stops the build.
