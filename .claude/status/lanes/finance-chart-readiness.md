# Lane finance-chart-readiness

Opened: 2026-09-28 14:09 EDT
Branch: lane/finance-chart-readiness
Owner: Codex Finance integration
Reason: Keep finance chart labels visible and low-dollar captions accurate
Territory: skills/finance-report/scripts/; tests/test_finance_report.py; lane record
Base: 76caf2b9a6ee91742627761c7114fda09b907201 (origin/main)
Retirement plan: Land verified reusable changes through a public PR; preserve until merged and no task needs checkout

## Ownership log

- 2026-09-28 14:09 EDT: opened by Codex Finance integration.

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.

## Verified milestone, 2026-09-28

Corrected cash marker bounds, truthful off-scale labels, zero prior-cash marker,
nearest-dollar spending caption, running-result label bounds and point clearance,
and colliding end labels. No accounting formulas or source data changed.

Checks: managed-runtime doctor ready; 546 unittest cases passed; PII and diff
checks passed; browser glyph bounds checked at 375 and 1280 pixels; ordinary and
edge-case synthetic reports remain two pages and both pages were visually read.
Independent review found no regression in these corrections. Existing handling
of nonpositive current cash/spending remains a separate data-boundary issue;
this milestone does not claim production readiness or a plugin version release.

Next: open the public PR, verify CI, preserve this lane until merged. The web
consumer may pin this exact reviewed source revision explicitly.

## Continued ownership, 2026-09-28

Prior public CI passed. Same owner extends this lane to cash/spending boundary
handling in Finance scripts and synthetic tests. No other lane owns these files.

## Cash and spending boundaries verified

Added shared cash wording, signed balance/credit amounts, explicit unavailable
coverage for nonpositive average spending, zero/empty group handling and cash
history scaling across zero. Percentage charts are omitted when credits make
proportions misleading. Account movements include rows present only in the
prior period; largest movements use magnitude and retain their signs.

Both current and prior grouped pulls now reconcile to section totals, and the
prior net must match the prior balance-sheet point before monthly subtraction.
This prevents partial prior pulls from inflating the current month.

Final checks: 551 public tests passed; PII and whitespace checks passed.
Reconciled synthetic zero, empty, credit and negative-bank reports rendered
as two pages. Their seven dashboard charts exactly matched the PDF charts.
Browser checks at 375 and 1280 pixels passed. Independent code review closed.
No live church books, plugin release or installed cache changed. The web
consumer must include cash_position.py in its reviewed source pin.
