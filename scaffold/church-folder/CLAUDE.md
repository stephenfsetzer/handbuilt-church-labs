# CLAUDE.md

This is the church's private workspace. The pastor owns its files and decides
how the agent works here. Handbuilt Church Labs supplies optional workflows.

## Work with the pastor

- Follow the pastor's request and local instructions. The pastor may add,
  edit, replace, or remove these instructions, local skills, and working files.
  Do not require plugin approval for those changes.
- Read relevant local skills under `skills/<name>/SKILL.md` when requested or
  when their stated purpose matches the task. Follow a user-selected local or
  personal skill instead of automatically routing back to Handbuilt.
- Use Handbuilt for its supported work when it is the selected workflow.
  Ordinary editing and other church work do not require a Handbuilt command,
  connection check, or receipt.
- Preserve existing work during setup and reconnection, including custom
  instructions and skills. Do not restore intentionally removed files.
- If a Handbuilt setting cannot express an authorized edit, help carry it out
  with local files or another tool. Preserve the earlier version and verify
  the changed result. A receipt describes the files checked at that time;
  do not claim it verifies a later edit.

## When using Handbuilt

1. Load the app's installed `handbuilt-church-labs:onboarding`,
   `handbuilt-church-labs:bulletin`, or `handbuilt-church-labs:sermon-research`
   skill for the requested Handbuilt operation.
2. Run the app-loaded skill's `tools/church_workflow.py` with
   `--church-folder "<this-folder>" start <workflow>` once. The saved connection
   may use a newer managed release or an intentional pinned development copy;
   do not reconnect just because its root differs from the app-loaded skill.
3. Read the exact returned skill and use its returned `launcher` prefix for
   every operation in this task. Do not start again or switch versions while
   preparing, reviewing, or finalizing the same work.
4. Read `church.yaml` and the workflow's saved state before asking questions.
   The launcher selects managed Python and records the installation used.
5. If Handbuilt is unavailable, explain how to reconnect it for Handbuilt
   operations. Continue other requested work with the tools available.

If the pastor asks to use the latest Handbuilt version or keep it updated,
run the app-loaded launcher with `ensure-latest` before starting the requested
workflow. Report the selected version and tell the pastor to start a new task
after an update. Never replace a development checkout silently; explain the
stable reconnect path if the command reports a development connection.

## Where work lives

- `skills/`: the church's own reusable skills and supporting files
- `church.yaml`: church identity, services, lectionary, and people
- `worship/profile.yaml`: standing worship practice and source references
- `brand.json`: visual identity and optional display overrides
- `sermons/<date>/`: readings, research, and pastor-directed sermon work
- `bulletins/YYYY/MM/<week>/`: bulletin inputs, PDFs, and receipts
- `music/`: private music files

## Instruction recovery

Handbuilt keeps local versions of CLAUDE.md and AGENTS.md when connecting or
starting a workflow. Before and after an authorized edit to these instructions,
use its recovery snapshot command. Ask the selected Handbuilt workflow for
recovery guidance when comparing or restoring a saved version. Keep intentional
deletions; a plugin update is not permission to restore or replace instructions.

## Working care

Verify liturgical sources and preserve private material. Never invent a
pastor-selected passage. Review a changed bulletin before printing or sending.
Handbuilt research ends at the cited brief; continue into writing or another
skill when the pastor requests it. Handbuilt approval history records the
specific approved artifact, and does not prove what happened in a service.
