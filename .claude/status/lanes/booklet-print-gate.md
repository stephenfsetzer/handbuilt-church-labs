# Lane booklet-print-gate

Opened: 2026-10-02 17:40 EDT
Branch: lane/booklet-print-gate
Owner: Booklet print gate session (Claude Code, desktop), with Labs workers
Reason: Booklet print gate (Handbuilt PRD-005A/booklet-print-gate.md): page craft the pastor corrected becomes blocking checks, bounded automatic fitting, and regression tests
Territory: skills/bulletin/renderer/print_layout.py, skills/bulletin/renderer/render_bulletin.py (print-unit attributes), skills/bulletin/renderer/impose_booklet.py, skills/bulletin/renderer/bulletin-config-schema.json (print options), skills/bulletin/bulletin_production/interface.py (quality gate, fit, receipt), skills/bulletin/SKILL.md, tools/church_workflow.py (check-print), handbook/printing-guide.md, tests/ for these
Base: a670412 (origin/main, 0.8.1)
Retirement plan: PR to main; churches pinned to an earlier lane repin after merge; then worktree-lane close

## Ownership log

- 2026-10-02 17:40 EDT: opened by the booklet print gate session (Claude Code, desktop).

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
