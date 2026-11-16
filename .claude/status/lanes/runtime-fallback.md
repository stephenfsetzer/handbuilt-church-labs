# Lane runtime-fallback

Opened: 2026-11-16 10:34 EST
Branch: lane/runtime-fallback
Owner: Claude Code session, handbuilt main checkout (2026-11-16)
Reason: Windows Application Control blocked one bundled PDF file and stopped every workflow; readiness becomes per job, with a fallback to the pastor's own Python and a guided install
Territory: tools/handbuilt_runtime.py tools/runtime_*.py bin/ skills/*/SKILL.md handbook/runtime-setup.md INSTALL.md tests/ .claude-plugin/ .codex-plugin/ CHANGELOG*
Base: c32b7366e6c4275e4ee70c18fd7b630d56a6ed8b (origin/main)
Retirement plan: Draft PR to main for Stephen to review and merge, then worktree-lane close

## Ownership log

- 2026-11-16 10:34 EST: opened by Claude Code session, handbuilt main checkout (2026-11-16).

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
