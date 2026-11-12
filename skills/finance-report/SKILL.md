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
"<app-loaded-plugin-root>/bin/handbuilt-python" "<app-loaded-plugin-root>/tools/church_workflow.py" \
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
   company info, the balance sheet split by month, then profit and loss from
   the first day of the church's year through the month end and through the
   prior month end (skip the second in the year's first month). The year is
   the church's own: January to December, or July to June, and so on, as
   `fiscal_year_start` in the settings says. If the settings do not have
   `fiscal_year_start` yet, save the company info response as
   `company-info.json` in the pulls folder and add
   `--company-info finance/board/YYYY-MM/pulls/company-info.json` to the
   build below; the build saves the month in the settings. Save each
   response in `finance/board/YYYY-MM/pulls/` exactly as returned.

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
     [--unrecorded "1500|Preschool rent received August 21, not yet recorded"]
   ```

   A blocked result means something does not agree: a total with
   QuickBooks, a pull with its period, a pull with its own columns, last
   year's line with last year's recorded result, or the settings' year start
   with QuickBooks. Stop and report it. Never edit figures by hand to make a
   check pass. A cut-off pull leaves its refusal in `blocked.json` in the
   month folder.

   Every year the report states (the year so far, the running chart, last
   year, their labels) follows the church's year; the result's `year` says
   which months it covers. A liability below zero comes back in
   `liabilities_below_zero` with its balance and first month below zero;
   quote those, never a figure worked out from the pull's rows.

   If the church closes each year into a fund balance, equity moves without
   a result and the build stops on last year's line or on the balance sheet
   change. Ask the treasurer whether the books close into funds. If they do,
   pull the profit and loss for January 1 through each month end of last
   year, and through each month end this year before the prior month (the
   two pulls above cover the last two; see `references/quickbooks.md`), and
   add one `--pl-through YYYY-MM=PULL.json` per month. The build then
   reads those years' monthly results from the profit and loss.

   Raise each item in the result's `needs_a_person` list: watch items that
   need this month's facts, a group whose accounts match nothing this year,
   new accounts that fell into "Everything else"
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

## Each new year

When the church's year begins (January, or July, and so on), add last year
to the settings' `long_view.full_years` and `pressure` series (from the
whole-year profit and loss; take out one-time items and label them), and add
the new year's budget.

## Guardrails

- Read-only in every finance system. Never post, edit, categorize, or pay.
- Report on the books; do not manage them. No monthly statement requests or
  confirmations beyond the obligations row, which the board needs to see.
- Anything that could alarm (restricted money possibly spent, late filings,
  pension arrears) goes to the treasurer first, not into a board draft.
- Not financial advice. The report describes the books; the board decides.
- A draft carries "Draft for review." A sample rebuilt from later books is
  marked as a sample (`--sample`).
