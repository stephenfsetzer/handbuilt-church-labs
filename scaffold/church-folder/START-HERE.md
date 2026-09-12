# Start Here

This is your church workspace. You can add, edit, replace, or remove its files
and skills to fit your church. Handbuilt Church Labs supplies a few workflows
to get started, and writes their results here.

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
brief records that week's research; use your chosen template for future weeks.

The small `handbuilt.py` launcher connects this folder to the installed plugin.
It does not copy the skills here. If you move computers or reinstall the plugin,
ask Handbuilt onboarding to reconnect this existing folder. Your work stays here.

## Make this workspace your own

Ask your agent to create a local skill in `skills/<name>/SKILL.md`. A skill is
a reusable set of instructions, with any templates or supporting files beside
it. See [Your church's skills](skills/README.md). You can also use personal
skills and other tools you already have.

`CLAUDE.md` and `AGENTS.md` are editable starting instructions for your agent.
Ask it to change how it works here, or edit those files yourself. You can remove
them or these welcome documents without changing Handbuilt workflow readiness.
Keep the configuration and sources needed by any workflow you still use.

You can ask for an edit beyond Handbuilt's settings, or choose another tool.
The agent should help, retain the earlier version, and check the changed work.
Reconnecting Handbuilt preserves your custom files and does not restore files
you removed. The plugin does not need to be installed for ordinary work here.
