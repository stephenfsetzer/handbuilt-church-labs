# AGENTS.md

This is a private church operating folder created by Handbuilt Church Labs.
Everything about this church stays here.

## Session startup

1. Run `python3 handbuilt.py start onboarding`, `start bulletin`, or
   `start sermon-research` for the requested workflow.
2. Read the exact `skill` path returned by that command. This identifies the
   connected Handbuilt installation. Follow its canonical instructions.
3. Read `church.yaml` and the workflow's saved private state before asking
   questions. Preserve answers and pastor-authored files.
4. Use `python3 handbuilt.py` for supported workflow operations. It selects
   Handbuilt's managed Python and records the installation used privately.
5. If the connection is missing, load the installed Handbuilt onboarding skill
   and reconnect this existing folder. If Handbuilt is not installed, explain
   how to install it. Stop production until the connection works. Do not use
   a personal sermon skill, generic PDF skill, or invented renderer as a fallback.


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
