# Lane plugin-security-release

Opened: 2026-10-26 19:37 EDT
Branch: lane/plugin-security-release
Owner: Plugin security implementation parent
Reason: Implement the authorized security release against PRD-plugin-install-and-updates and the reviewed security findings.
Territory: runtime security helpers and launcher, package manifest, requirements, related regression tests and migration/font rehearsals, runtime and input-limit handbook pages, publication CI, plugin manifests and integrated PDF/image limit changes. Fixture updates cover the new required package files and the verified runtime test recipe.
Base: fa64adddac47842a11908ee4b8ba5004d95e1406 (origin/main)
Retirement plan: Open a reviewed PR to main; preserve this lane until Stephen merges and ownership and recovery checks permit retirement.

## Ownership log

- 2026-10-26 19:37 EDT: opened by Plugin security implementation parent.
- 2026-10-26: Integrated reviewed worker changes. Full suite, targeted parser checks, real runtime migration and rollback, workflow upgrade rehearsal, public-data guard and package verification passed. Production installation remains unchanged; this lane is retained for pull request review.

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
