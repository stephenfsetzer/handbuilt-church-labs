# Lane plugin-security-release

Opened: 2026-10-26 19:37 EDT
Branch: lane/plugin-security-release
Owner: Plugin security implementation parent
Reason: Implement the authorized security release against PRD-plugin-install-and-updates and the reviewed security findings.
Territory: tools/handbuilt_runtime.py tools/church_workflow.py tools/workflow_updates.py requirements.txt tests/test_handbuilt_runtime.py tests/test_runtime_security.py tests/test_workflow_updates.py tests/smoke_managed_updates.py handbook/runtime-setup.md .github/workflows/publication.yml plugin manifests and integrated PDF/image limit changes
Base: fa64adddac47842a11908ee4b8ba5004d95e1406 (origin/main)
Retirement plan: Open a reviewed PR to main; preserve this lane until Stephen merges and ownership and recovery checks permit retirement.

## Ownership log

- 2026-10-26 19:37 EDT: opened by Plugin security implementation parent.

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
