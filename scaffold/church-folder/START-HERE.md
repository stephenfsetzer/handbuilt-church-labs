# Start Here

This is your church folder. Handbuilt Church Labs workflows read from it and
write finished work back into it.

During setup, `ONBOARDING.md` shows what the website supplied, what you
confirmed, what still needs attention, and the next step. You do not need to
edit that file.

Open this folder in Codex or Claude Code before starting ordinary church work. Then ask for one of these
workflows:

- "Build my bulletin."
- "Start my sermon research."

Each sermon research folder has two governed files: `readings.md` and
`research-brief.md`. The workflow keeps its verification receipts hidden and
tells you when either file needs review or regeneration. `readings.md` records
either the reconciled lectionary selection or the passage you confirmed for
that service. Weekly automation waits for you when a passage still needs to be
selected. The workflow ends when the research brief is ready for your study.

Your church identity, regular services, and optional sermon research
preferences live in `church.yaml`. Your visual identity lives in `brand.json`.
Licensed music scans belong in `music/`. Weekly work is stored under
`bulletins/` and `sermons/`.

For sermon research, `church.yaml` controls standing preferences. The plugin's
canonical template controls presentation unless you explicitly create
`sermons/research-brief-template.md` as a church-specific override. An earlier
brief is history, not an instruction for the next week.

The small `handbuilt.py` launcher connects this folder to the installed plugin.
It does not copy the skills here. If you move computers or reinstall the plugin,
ask Handbuilt onboarding to reconnect this existing folder. Your work stays here.

The installed plugin contains the reusable workflow and production code. This
folder contains your church's private record.
