# Make your church workspace your own

Handbuilt helps you create a private workspace and supplies a few useful
skills. You own that workspace. Add, edit, replace, or remove instructions,
skills, templates, and working files as your church needs change.

## Add or adapt a skill

Ask your agent to create `skills/<name>/SKILL.md` inside your church folder.
A skill is a reusable set of instructions. Its own folder can also contain
templates, examples, and scripts. For example:

```text
Create a local parish-newsletter skill using my preferred tone and sections.
Save each newsletter as a draft for me to review.
```

The supplied workspace instructions tell the agent to read relevant local
skills. You can also request one by its file path, use an existing personal
skill, or choose another tool. Local file use does not require Handbuilt.
Automatic appearance in an app's skill menu is separate; the agent should
check that app's supported setup before promising menu discovery.

To adapt a supplied Handbuilt skill, give the local version a distinct name.
Have the agent check relative references and helper dependencies. It can keep
using Handbuilt commands where they fit and use other tools for custom work.
Local adaptations remain yours and do not automatically receive upstream
changes. Prefer local adaptations over editing an installed plugin cache,
where an update may replace the files.

## Change the workspace instructions

`CLAUDE.md` and `AGENTS.md` are editable starting points. Tell the agent how you
want it to work, or edit the files yourself. You can remove them and the
welcome documents without changing readiness for Handbuilt workflows whose
required configuration and sources still exist.

Handbuilt keeps local recovery copies of those two files during connection and
workflow startup. Before and after a requested instruction edit, the agent
uses [instruction recovery](instruction-recovery.md) to save versions. You can
ask to compare or restore an earlier version without managing backup paths.

A request to update these instructions or use another workflow is sufficient
direction. The agent must not demand plugin permission or ask you to uninstall
Handbuilt first. A missing Handbuilt connection affects its own commands;
other work can continue with the tools available.

## Edit a bulletin beyond the supplied settings

Tell the agent what should change and whether it applies to one week or future
bulletins. For supported settings, it can use Handbuilt's revision tools.
For a custom edit or a user-selected workflow, it should proceed with local
files and suitable tools. Explain an actual technical limitation in plain
language and work toward the requested result.

Keep the existing reviewed version, work on a new copy, and verify the changed
result. For a layout edit, retain the text and music unless the pastor also
requests content changes. Check the rendered pages for missing content,
clipping, and readable type. A shorter page count is not permission to remove
a hymn image or change worship order.

A Handbuilt receipt describes specific files and the checks performed on
them. An edit makes that receipt inapplicable to the changed files. Do not
rewrite receipt hashes to imply the edit was checked. The agent can prepare a
custom version for the pastor's review outside Handbuilt finalization, or
render a supported revision and obtain a new receipt. Describe which checks
were performed accurately. The pastor still reviews the result before printing
or sending; the agent need not add a separate permission step to make the edit.

The stock renderer currently offers Classic and Modern with defined settings.
It does not automatically load church-local CSS or template files. A custom
skill must apply its own customization and check its output. This guidance
permits that work; it does not add new renderer controls.

## Keep your changes when reconnecting

Reconnecting Handbuilt updates its connection and an unchanged supplied
launcher. It preserves local skills, custom instructions, and other church
work, and does not restore deleted guidance. If you customized the launcher,
the connection helper preserves it and asks for reconciliation before that
Handbuilt connection can be updated. Other work remains available.

For an existing folder created with older restrictive instructions, ask:

```text
Update this workspace so I can use local skills and edit my own files.
Keep my existing preferences and work.
```

The agent should use the instruction recovery snapshot command, then replace only the
Handbuilt clauses that claim exclusive control, forbid other skills, or forbid
authorized custom edits. Preserve local additions and follow the pastor's
chosen wording. Add local skill guidance if requested. Do not replace whole
instruction files with the latest scaffold or recreate files the pastor
removed. Reconnection alone deliberately leaves these files untouched.

You can remove Handbuilt and keep using the workspace. Its installed commands
will be unavailable, and a local skill that uses those commands will need a
replacement. Your documents and independent local skills remain yours.
