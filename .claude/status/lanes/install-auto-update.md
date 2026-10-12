# Lane install-auto-update

Opened: 2026-10-12 11:18 EDT
Branch: lane/install-auto-update
Owner: Claude Code desktop session: plugin install and auto-update
Reason: Every new plugin version must reach every install path with auto-update on; PRD go-to-market-2026/prds/PRD-plugin-install-and-updates.md in the handbuilt repo
Territory: .claude-plugin/ .codex-plugin/ .agents/plugins/marketplace.json .github/workflows/ tools/check_version_bump.py tests/test_version_bump.py INSTALL.md README.md handbook/workflow-updates.md
Base: ae541c69b565396467056cc5b7606b166f8140ee (origin/main)
Retirement plan: Merged by PR to main, release v0.8.8 published with both assets, then scripts/worktree-lane close

## Ownership log

- 2026-10-12 11:18 EDT: opened by Claude Code desktop session: plugin install and auto-update.

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
