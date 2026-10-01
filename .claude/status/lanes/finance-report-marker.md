# Lane finance-report-marker

Opened: 2026-10-01 17:29 EDT
Branch: lane/finance-report-marker
Owner: PRD-012 design boards (Claude Code, desktop), Labs engine worker
Reason: Finance report engine: print what a report is instead of 'Draft for review' when there is no approval step, and show set-aside (restricted and designated) money by name (Handbuilt PRD-012 build plan decision 3 and slice 2)
Territory: skills/finance-report/ (scripts and tests for the report engine), tests/ for finance
Base: 5c83863a1e79313e3f43eaa7b837064ccdbe95b0 (origin/main)
Retirement plan: PR to main in handbuilt-church-labs; then the Handbuilt app repins to the new revision in its own PR; then worktree-lane close

## Ownership log

- 2026-10-01 17:29 EDT: opened by PRD-012 design boards (Claude Code, desktop), Labs engine worker.

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
