# CLAUDE.md

This is a private church operating folder created by Handbuilt Church Labs.
Everything about this church stays here.

## Session startup

1. Activate the app's installed `handbuilt-church-labs:onboarding`,
   `handbuilt-church-labs:bulletin`, or `handbuilt-church-labs:sermon-research`
   skill for the requested work. Use the app's skill loader when available.
   Its current installation is authoritative; an older cached copy may still
   exist after an update.
2. Compare that skill's plugin root with `.handbuilt/installation.json`. If
   they differ, follow the installed onboarding connection reference to
   reconnect this folder before running its launcher. Do not select a cached
   version by its filename or a previous conversation.
3. Run `python3 handbuilt.py start onboarding`, `start bulletin`, or
   `start sermon-research`. Verify the returned skill belongs to the same
   installed plugin, then follow its canonical instructions.
4. Read `church.yaml` and the workflow's saved state before asking questions.
   Preserve answers and pastor-authored files. Use `python3 handbuilt.py` for
   supported operations; it selects managed Python and records the installation.
5. If Handbuilt is unavailable, explain how to install or reconnect it. Stop
   production until the connection works. Do not substitute a personal sermon
   skill, generic PDF skill, or invented renderer.


## Layout

- `church.yaml`: church identity, services, sermon selection mode, lectionary, and people
- `worship/profile.yaml`: standing worship practice and source references
- `brand.json`: colors, logos, and optional display overrides; identity comes from `church.yaml`
- `sermons/<date>/`: verified readings and the cited research brief
- `bulletins/YYYY/MM/<week>/`: bulletin inputs, PDFs, and receipts
- `bulletins/bulletin-log.json`: approved bulletin history
- `music/`: scans this parish is licensed to reproduce

## Rules

- Verify liturgical sources. Never rely on memory or invent a sermon passage.
- In pastor-selected sermon mode, automation waits for the pastor to confirm
  the passage for that service.
- Keep private church material in this folder.
- Sermon research ends at a verified `research-brief.md`. Reflection and
  drafting are outside the Labs workflow.
- Preserve existing pastor reflection and draft files without interpreting
  them as research workflow state.
- Bulletins require human review before finalization or printing.
- Approved history describes approved bulletins. It does not prove what
  happened during a service.
