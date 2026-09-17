# Recover your church instructions

Your church owns `CLAUDE.md` and `AGENTS.md`. Handbuilt saves local recovery
copies when you connect the folder or start a workflow. It does not replace
your instructions with the plugin's templates. Unchanged files do not create
repeated snapshots, and deleted files stay deleted.

Ask your agent: "Show me earlier versions of my church instructions" or
"Restore the version before that edit." The agent compares the saved text
with the current file and restores the version you choose. It saves the current
instructions first, so that restoration can also be undone.

These copies live privately in `.handbuilt/recovery/` inside your church folder.
They stay on your computer and are retained until you deliberately remove them.
Back up the church folder normally if you need protection against device loss.
Recovery covers these two instruction files, not every document in the folder.
It cannot recover an earlier version that was never captured. A timestamp and
reason describe an observation, not proof of which person or application edited
the file.

## For the agent

Use the selected workflow's returned launcher prefix. These operations need no
PDF runtime and do not start another update check. Never interpret a request to
update the plugin as permission to restore or synchronize church instructions.

Before a requested instruction edit, capture the current version:

```bash
<launcher-prefix> recovery snapshot --reason before_instruction_edit
```

Make only the requested edit, preserving unrelated preferences and additions.
Verify the difference, then record the result:

```bash
<launcher-prefix> recovery snapshot --reason after_instruction_edit
```

If a snapshot fails, resolve the reported path, size, or storage problem before
editing these instructions. Do not replace files with a scaffold as a repair.

To investigate or recover:

```bash
<launcher-prefix> recovery history
<launcher-prefix> recovery show --snapshot <id> --file CLAUDE.md
<launcher-prefix> recovery restore --snapshot <id> --file CLAUDE.md \
  --expected-sha256 <current-sha256-or-missing>
```

`history` reports saved versions and current hashes. Compare the chosen text
with the current file and explain the specific change before restoring. A
clear request to restore that version is sufficient authorization; do not ask
again. Use `missing` only when the user requests restoration of a deleted file.
Never restore a deletion automatically. A snapshot where the file was absent
cannot be used to delete a current file.

If the current hash changed since inspection, stop that restore and compare
the new content. Keep the newer work and reconcile the difference with the
pastor. Handbuilt serializes its own recovery operations and checks the file
again before replacement. An unrelated editor can still write without taking
that lock; avoid editing the same instruction file in two sessions at once.

Only root `CLAUDE.md` and `AGENTS.md` are supported, each at most 1 MiB.
Symlinked files or recovery directories are rejected. Snapshot bytes are checked
before restoration. On macOS and Linux, recovery snapshots and directories use
owner-only access; restored instruction files retain the selected version's
permissions. On Windows, access follows the church folder's inherited account
permissions; Unix permission bits do not establish Windows access controls.
