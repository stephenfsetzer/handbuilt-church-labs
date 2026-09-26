---
name: finance-onboarding
description: Set up a church's finances for board reporting, in four stages that end with the monthly finance report locked in. Use when a pastor or treasurer asks to set up the church's finances, look at the books, get ready for a vestry or council finance report, or check where finance setup stands. Read-only in QuickBooks and every other finance system.
---

# Finance Onboarding

Four stages that lead to the monthly finance report. The report is the
destination, not the starting point: many churches' books need some work
before a board report can be trusted, and the pastor should see the books
before the board does.

| Stage | Outcome | Ends when |
|---|---|---|
| 1. Look | A plain-language finance overview for the pastor, and questions for the treasurer | The overview exists and the pastor has read it |
| 2. First report | Settings saved and a sample edition, with stage 1's findings shown as caveats | Settings saved; sample built |
| 3. Make the books report-ready | A readiness checklist and a one-page treasurer packet | Every item met, or waived with a reason |
| 4. Lock the monthly report | Calendar, approver, and the first real edition approved by the treasurer | Locked; the finance report workflow takes over |

Onboarding keeps its place in `finance/onboarding-state.json` and can be
paused and resumed at any stage.

## Start or resume

Run the app-loaded adapter once, for this workflow and for the finance
report, whose operations stages 1, 2, and 4 use:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start finance-onboarding
```

Use the returned `launcher` prefix (written `<launcher>` below) for every
operation. Then:

```bash
<launcher> finance-onboarding orient
```

Tell the person, in one or two sentences, which stage they are in, what it is
for, and what is blocking it. Work on that stage only. Ask one question at a
time.

## Stage 1: Look

1. Readiness and QuickBooks connection: follow step 0 of the finance report
   skill (connection, company name check, read-only). Nothing is changed in
   QuickBooks at any stage.
2. Pull the setup set into `finance/board/setup-pulls/` as described in the
   finance report skill's `references/first-time-setup.md`, step 1.
3. Run the findings:

   ```bash
   <launcher> finance-onboarding look \
     --balance-sheet finance/board/setup-pulls/balance-sheet.json \
     --pl-12m finance/board/setup-pulls/pl-12m.json
   ```

4. Write `finance/finance-overview.md` for the pastor from
   `finance/onboarding/findings.json`, following
   `references/overview-template.md`. Every figure names its source. Label
   anything uncertain as an estimate. Anything that could alarm is framed as
   a question for the treasurer, not a conclusion.
5. Walk the pastor through it. Then `<launcher> finance-onboarding stage --done 1`.

## Stage 2: First report

Run first-time setup from the finance report skill's
`references/first-time-setup.md`, then build and render a sample edition of
the last complete month with `--sample`. Open readiness items appear on it as
caveats. Show it. Then `stage --done 2`.

## Stage 3: Make the books report-ready

1. Show the checklist (`orient`). For each item, explain in two sentences
   what it is and why a board needs it, then ask what is true today:

   | Item | How it is known |
   |---|---|
   | Payment services cleared each month | The data, every pull |
   | Money received is recorded | The data, when payment services are connected |
   | Bank accounts reconciled monthly | Ask the treasurer, once |
   | Months locked after checking | Ask the treasurer, once |
   | Restricted funds confirmed | Ask, with the stage 1 data flag |
   | A budget, or a decision to go without | Setup |

2. Write the one-page treasurer packet (`references/treasurer-packet.md`).
   The treasurer or bookkeeper makes any changes in their own books; this
   workflow never does.
3. Record each answer:

   ```bash
   <launcher> finance-onboarding readiness --item month_lock --status met
   <launcher> finance-onboarding readiness --item reconciliation --status waived \
     --reason "The bookkeeper reconciles quarterly for now"
   ```

   A waiver needs a reason. Waived and open items appear on every report, in
   the Books readiness row and as plain caveats, until they are met. Items
   checked from data are re-checked every month and flagged again if the
   problem returns.
4. When nothing is open: `stage --done 3`.

## Stage 4: Lock the monthly report

1. Agree the calendar and approver with the treasurer:

   ```bash
   <launcher> finance-onboarding calendar --books-closed-by "the 15th" \
     --report-by "the 20th" --meeting "second Tuesday" --approver "NAME"
   ```

2. Build the first real edition with the finance report workflow. The
   treasurer approves it; set its `meta.status` to `final` and render once
   more.
3. `stage --done 4`. Onboarding is complete; each month after this, use the
   finance report workflow.

## Guardrails

- Read-only in QuickBooks and every finance system, at every stage.
- The overview is for the pastor. The board sees reports, not the overview.
- Anything that could alarm goes to the treasurer first.
- Not financial advice; the books are described, decisions stay with people.
