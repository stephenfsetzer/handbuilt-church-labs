# Lane sermon-video-update-check

Opened: 2026-10-12 19:09 EDT
Branch: lane/sermon-video-update-check
Owner: Claude Code session nifty-goldberg (sermon-video update check)
Reason: Sermon-video skips the shared start check, so its users never see the Claude automatic-updates prompt added in v0.8.8 (PR #35).
Territory: skills/sermon-video/, tools/church_workflow.py, tools/claude_updates.py, tests/, manifest version entries, CHANGELOG
Base: 5198beb60844bbf218218d0668fa9577480a6be3 (origin/main)
Retirement plan: PR to main for Stephen's review; close the lane with worktree-lane close after merge.

## Ownership log

- 2026-10-12 19:09 EDT: opened by Claude Code session nifty-goldberg (sermon-video update check).

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
