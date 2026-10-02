---
name: finance-report
description: Build the monthly finance report for the vestry or church council, a two-page PDF in the church's brand, from QuickBooks. Use when a pastor or treasurer asks to build or run the finance report, the vestry or council finance report, or this month's board finance packet. Read-only in QuickBooks. Finance onboarding comes first for a church that has not finished it.
---

# Finance Report

A monthly finance report for the governing board: two pages, seven
plain-language questions plus a watch list, in the church's brand. Each
edition covers the books through a month end and goes to the next meeting.
The shape is fixed (see `references/shape.md`); church-specific settings live
in the church's `finance/board/config.json`.

This workflow reports on the books. It never changes them, and it does not
ask the treasurer for monthly bookkeeping tasks. What the books cannot show,
the report says plainly as a caveat.

## Start or resume

Run the app-loaded adapter once:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start finance-report
```

Read the returned skill path to confirm this workflow. Use the returned
`launcher` prefix for every operation below; the examples write it as
`<launcher>`. Do not run `start` again during the task.

If `finance/onboarding-state.json` does not show `"locked": true`, the church
has not finished finance onboarding. Say so and offer to continue it at its
current stage (start `finance-onboarding`). A sample edition can still be
built.

## Procedure

Ask one question at a time. Read `finance/board/config.json` and the latest
month folder before asking anything.

0. **Check readiness.** Run `<launcher> finance-report status` and act on
   anything missing. Then check QuickBooks yourself: look for the QuickBooks
   connector tools. If they are missing, explain in two sentences that the
   report reads the books and never changes them, and guide the person to add
   the QuickBooks connector in Claude (Settings, then Connectors) and sign in
   with the church's QuickBooks login. When the tools are present, call
   company info and read the company name back; if it does not match
   `church.yaml`, stop and ask which company is the church's. Say that the
   connector also has tools that could change the books and this workflow
   uses only its reading tools. If finance settings are missing, run
   first-time setup (`references/first-time-setup.md`). No `brand.json` is
   fine: the report uses a neutral theme.

1. **Choose the month.** Default to the last complete month. Confirm it and
   the meeting it goes to (the August edition goes to the September
   meeting). If the settings have no budget for the year, ask for one or for
   a decision to go without.

2. **Pull from QuickBooks, read-only.** Follow `references/quickbooks.md`:
   company info, the balance sheet split by month, then profit and loss for
   January 1 through the month end and through the prior month end (skip the
   second in January). Save each response in `finance/board/YYYY-MM/pulls/`.

3. **Look for income not yet recorded.** If the church uses payment services
   such as Stripe or Givebutter and they are connected, compare their payouts
   for the month with QuickBooks. List each amount, payer, and date. Do not
   guess.

4. **Build the data.**

   ```bash
   <launcher> finance-report build --month YYYY-MM --prepared YYYY-MM-DD \
     --balance-sheet finance/board/YYYY-MM/pulls/balance-sheet.json \
     --pl-ytd finance/board/YYYY-MM/pulls/pl-ytd.json \
     --pl-prior finance/board/YYYY-MM/pulls/pl-prior.json \
     [--unrecorded "1500|Hall rent received August 21, not yet recorded"]
   ```

   A blocked result means something does not agree: a total with
   QuickBooks, a pull with its period, or last year's line with last year's
   recorded result. Stop and report it. Never edit figures by hand to make a
   check pass.

   Raise each item in the result's `needs_a_person` list: watch items that
   need this month's facts, new accounts that fell into "Everything else"
   (confirm or change the grouping in the settings), and earlier months that
   changed since last month's report (also flagged on the report itself),
   and a month that looks unrecorded: no income entered at all, which means
   the bookkeeper has not posted it yet, not that nothing came in. The draft
   then says so and reads the year through the month before. Offer to pause
   and rebuild once the books catch up, or to go on with the draft marked.

5. **Update the watch list with the person.** Items carried from last month
   with a template update themselves; the rest need this month's latest fact
   and next step. Ask about each one, one at a time: what changed, and is it
   resolved? Add new items. Measured items get Better or Worse automatically.

6. **Finish the short answer.** The build drafts it. Refine it with
   `references/short-answer.md`. Say plainly that the treasurer approves or
   edits it before the report is final.

7. **Render and look.**

   ```bash
   <launcher> finance-report render finance/board/YYYY-MM/report.json
   ```

   The render fails unless the PDF is one or two pages. It warns on a draft,
   and refuses a final report, if a dollar figure in the short answer or the
   watch list matches nothing in the data. Then look at both pages: no
   overlapping labels, no "Update needed" left in the watch list.

8. **Treasurer review.** The treasurer confirms each obligation's status and
   approves the short answer. Only then set `meta.status` to `final` and
   render once more. Leave the final PDF, `report.json`, and receipt
   unchanged afterward.

## Each January

Add last year to the settings' `long_view.full_years` and `pressure` series
(from the full-year profit and loss; take out one-time items and label
them), and add the new year's budget.

## Guardrails

- Read-only in every finance system. Never post, edit, categorize, or pay.
- Report on the books; do not manage them. No monthly statement requests or
  confirmations beyond the obligations row, which the board needs to see.
- Anything that could alarm (restricted money possibly spent, late filings,
  pension arrears) goes to the treasurer first, not into a board draft.
- Not financial advice. The report describes the books; the board decides.
- A draft carries "Draft for review." A sample rebuilt from later books is
  marked as a sample (`--sample`).
