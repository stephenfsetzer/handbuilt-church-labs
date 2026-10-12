# Lane hermetic-finance-evals

Opened: 2026-10-12 19:33 EDT
Branch: lane/hermetic-finance-evals
Owner: claude-code (fix finance eval test hermeticity)
Reason: Four Finance eval tests from PR #33 fail inside a Claude Code session on macOS; make them hermetic.
Territory: tests/test_finance_evals_harness.py tests/test_finance_evals_grading.py evals/ tools/ manifests
Base: 04dec255fce257ab50c0ad5301061edc56404dc0 (origin/main)
Retirement plan: Done when the PR to main merges; lane closes via worktree-lane close.

## Ownership log

- 2026-10-12 19:33 EDT: opened by claude-code (fix finance eval test hermeticity).

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
