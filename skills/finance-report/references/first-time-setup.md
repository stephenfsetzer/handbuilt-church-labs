# First-time setup

Run once per church, when `finance_report_status.py` says finance settings
are missing. About fifteen minutes, ideally with the treasurer. The agent
drafts everything from the books; the person confirms. The person never edits
JSON. Ask one question at a time, and show what the question is about before
asking it.

## Before setup

QuickBooks must be connected and the company confirmed (the skill's step 0).

## 1. Pull the books for setup (read-only)

Save each response in `finance/board/setup-pulls/`:

- `balance-sheet.json`: balance sheet split by month, from January five years
  ago (or the first month the books have) to the last complete month.
- `pl-12m.json`: profit and loss for the last twelve complete months.
- `pl-YYYY.json`: profit and loss for each of the last four full calendar
  years (fewer if the books are younger).

## 2. Draft

```bash
<launcher> finance-report setup draft \
  --balance-sheet finance/board/setup-pulls/balance-sheet.json \
  --pl-12m finance/board/setup-pulls/pl-12m.json \
  --pl-year finance/board/setup-pulls/pl-2022.json --pl-year finance/board/setup-pulls/pl-2023.json
```

It writes `finance/board/setup-draft.json` and prints a summary.

## 3. Confirm with the person, in this order

1. **Everyday cash.** Show the bank accounts it chose and their balances,
   and what it set aside (payment services such as Stripe, investments,
   headings, unused accounts), with the reason for each. Ask: are these the
   accounts the church pays bills from? An account that is closed now but
   held money in past years stays in, so the history is right. Investment
   funds whose names give no hint are found by their balances; say so when
   that happened.
2. **Money in.** Show the groups (at most five, the last one catches the
   rest) with twelve-month amounts. Ask for plain names a board member would
   use (for example, "4110 Rental Income @ Main Hall" becomes "Hall rent"). Offer to merge
   groups. Edit the draft's `income_groups` names, notes, and accounts.
3. **Money out.** The same for `spending_groups`. If one area needs a
   separate line (for example, legal fees filed under building costs), add a
   group for it and an `exclude` on the parent.
4. **Budget.** The connector cannot read budgets. Offer three choices:
   - export Budget vs. Actuals by month from QuickBooks and share the CSV:
     `<launcher> finance-report setup budget --year YYYY --csv FILE`
   - give the year's planned surplus or shortfall: `--annual AMOUNT`
   - no budget: `--none` (question 2 then compares with last year only)
   With an export, setup also offers a watch-list item for the largest cost
   area against its budget.
5. **Unusual years.** Show each year's result and every one-time candidate
   it found (loan forgiveness, bequests, insurance payments, large other
   income, and costs such as storm damage or a large other expense). For
   each, ask whether it was a one-time item. Record each yes with
   `<launcher> finance-report setup one-time --year Y --amount A --label "plain words"` (add `--done` on
   the last), or `one-time --none`. A cost carries a negative amount, as the
   candidate shows it: `--amount=-A`. Two items in one year add together.
6. **The pressure question.** Show the drafted pair (largest source of money
   against largest cost) and ask whether that is the tension the board
   watches. Write its one-sentence answer with the person.
7. **Obligations.** Show the defaults for the tradition. Adjust.
8. **Watch list.** Ask what money questions the board is already watching.
   Each becomes a watch item (title, latest, next step).
9. **Approver.** Confirm who approves the short answer each month (the
   treasurer by default).

## 4. Save

```bash
<launcher> finance-report setup apply --approved-by "NAME"
```

It refuses to save until the budget is decided, one-time items are reviewed,
every group has a plain name, and an approver is named, and says which is
missing.

## 5. Sample edition

Build the most recent complete month with `--sample` (the skill's steps 2
to 7) and show it. The sample is labeled as such. The first real edition
follows the normal monthly procedure.
