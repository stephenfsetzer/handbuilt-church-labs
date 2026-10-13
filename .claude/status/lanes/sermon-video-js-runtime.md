# Lane sermon-video-js-runtime

Opened: 2026-10-09 17:28 EDT
Branch: lane/sermon-video-js-runtime
Owner: Claude Code, at Stephen's direction
Reason: Fix YouTube 403 failures in sermon-video by passing yt-dlp a JS runtime (node or bun) when Deno is absent, and have doctor report yt-dlp version, JS runtime and yt-dlp-ejs
Territory: skills/sermon-video/scripts/sermon_video.py; skills/sermon-video/references/providers.md; tests/test_sermon_video.py; lane record. Overlaps lane/sermon-video territory, which is landed on main via #21 and has no unlanded skill changes
Base: 27bdf81fa3f2a8baec04196950795e18fa73c6ea (origin/main)
Retirement plan: Land through a public PR to main with Stephen as author; close by the light path once merged

## Ownership log

- 2026-10-09 17:28 EDT: opened by Claude Code, at Stephen's direction.

Record a transfer as: `- <date>: from <owner> to <owner> at <commit>; must not touch: <ports, data roots, files>`.

Rules (docs/worktree-policy.md): commit at every verified milestone; never seed
another lane from this working tree; keep church data roots outside the checkout;
record ownership transfers above; close through the closeout checklist (section 6)
and the preservation procedure (section 7), or the light path for clean, fully
merged lanes it defines.
