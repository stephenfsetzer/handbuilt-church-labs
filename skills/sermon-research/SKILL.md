---
name: sermon-research
description: Run or resume the portable sermon research workflow from passage selection through verified readings and a cited research brief. Use when a pastor asks for sermon research or when a weekly sermon research automation invokes the workflow.
---

# Sermon Research

This skill governs Handbuilt research. The pastor may choose a local or
personal skill, adapt this workflow, or request other sermon work in the same
folder. Follow that request without treating this skill's endpoint as a ban.
See [Workspace customization](../../handbook/workspace-customization.md).

Use one canonical workflow for manual and scheduled runs. Work only inside the
supplied private church folder. The workflow governs two files under
`sermons/<YYYY-MM-DD>/`:

1. `readings.md`
2. `research-brief.md`

`research-brief.md` is the primary pastor-facing deliverable. `readings.md`
records the verified scope that supports it. Hidden `.receipts/` files govern
state. Never ask the pastor to manage them.

The workflow ends at `research_complete`. Sermon reflection, outlining, manuscript drafting,
manuscript editing, and sermon review are outside this research operation.
Writing and editing the research brief are internal parts of this skill.
Existing pastor files such as `reflections.md` or `sermon-draft.md` remain
pastor-owned. Do not change them as a side effect of research or interpret them
as workflow state. Edit them when the pastor requests that separate work.

## Start or resume

Run the app-loaded adapter once:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start sermon-research
```

Read the returned skill path to confirm this selected Handbuilt workflow. Use
the returned `launcher` prefix, including its selected plugin root and managed
Python, for every `orient` and `record` operation in this task. Do not run
`start` again after reading the returned skill. The normal
`church-folder/handbuilt.py start sermon-research` command remains valid for a
person checking the connection manually.
If the connection is missing, follow the onboarding connection reference to
repair it for Handbuilt commands. Continue with another workflow when the
pastor chooses one, without claiming it completed Handbuilt's checks.

Run the operation with the exact prefix returned by `start`:

```bash
<launcher-prefix> sermon-research orient --date <YYYY-MM-DD>
```

For a scheduled run, add `--mode scheduled` to `orient` and every `record`
call. Manual and scheduled runs use the same stages and both end at
`research_complete`. The mode changes only which passage-selection actions are
permitted.

Follow `workflow_state` and `next_actions`. A present file may be modified,
unverified, or stale. Do not infer state from conversation history or file
presence. `research_focus` reports the church's configured primary text.

## `needs_readings` or `awaiting_passage`

Read [source-verification.md](references/source-verification.md) in full.
Inspect `sermon.selection_mode` in `church.yaml` before choosing the
verification path.

For a lectionary church, resolve the configured system, year, track, service,
optional verse policy, and primary research text. Open two independent
published lectionary hosts and reconcile them.

When `sermon.selection_mode` is `pastor_selected`, ask the pastor to name and
confirm the passage for this service. `sermon.primary_text` must be `selected`.
Open one published text reference in the configured translation and verify that
its citation matches the pastor's selection. Bind the pastor's confirmation to
the service date in metadata. A scheduled run cannot choose or record this
passage. It returns `awaiting_passage` with no autonomous next action unless a
manually confirmed `readings.md` already exists for the service.

Prepare the readings content in a temporary file outside the sermon folder.
For lectionary mode, metadata contains the normalized selection plus both
sources' observed selections, and the visible artifact states the optional
verse approach, this week's decision, and the exact primary research text. For
pastor-selected mode, metadata contains the normalized selection, the
date-bound pastor confirmation, and one source's observed text and translation.

Record the stage:

```bash
<launcher-prefix> sermon-research record --date <YYYY-MM-DD> \
  --stage readings --content-file <readings.md> \
  --metadata-file <readings-metadata.json>
```

For a complete, valid, copy-adaptable metadata and content pair for both
lectionary and pastor-selected mode, including every visible label the
module checks, see the examples in
[source-verification.md](references/source-verification.md). Do not
construct a first attempt from memory of the module's field names; adapt
those examples instead.

Memory and search snippets do not qualify. For lectionary runs, duplicate pages
on one host and disagreeing observed selections do not qualify. For a
pastor-selected run, neither the published text reference nor the agent may
substitute a different passage.

## `needs_research`

Read [methodology.md](references/methodology.md),
[source-directory.md](references/source-directory.md), and
[source-verification.md](references/source-verification.md) in full. Use the
church's `sermons/research-brief-template.md` when it exists. Otherwise use the
shipped [research-brief-template.md](references/research-brief-template.md).

The active template governs presentation. `methodology.md` governs research
quality. Do not use an earlier brief as an implicit template or style authority.
Read `sermon.research_preferences` in `church.yaml`. Named voices are priority
search targets only when they address this text. Preferred resources still
need to be available and verified. A blank value is absent and must not be
guessed. No preference may preselect the interpretive conclusion. Older church
folders without this section use the portable defaults in `methodology.md`.

When a pastor changes a research preference in ordinary language, route the
standing update through the onboarding `church_setup.py` helper's validated
settings patch. Keep date-specific research choices in the dated sermon
workflow. Do not edit the preference mapping by hand, and do not treat a
weekly passage or preacher as a standing preference.

Resolve one primary research text. Use `sermon.primary_text` from
`church.yaml`, whose allowed values are `first`, `psalm`, `second`, `gospel`,
and `selected`. `selected` is required for pastor-selected mode. If the value
is blank, ask the pastor and update the profile. A manual lectionary run may use
a pastor-supplied override for that Sunday. A scheduled run may not guess or
use an undeclared override.

Run two passes before recording research:

1. Research and write, in your own context. Follow
   [research-pass.md](references/research-pass.md) to open sources and keep
   compact working cards, judge sufficiency, then follow
   [writing-pass.md](references/writing-pass.md) to write the brief directly
   from those cards. Do not hand the cards to another agent; you already hold
   the sources. Save the draft before editing.
2. Edit, in a fresh agent context when available and authorized. Follow
   [editing-pass.md](references/editing-pass.md): the editor rechecks
   quotations and consequential claims against the sources with its fetches
   batched in one turn, edits the draft in place, and returns a short record.
   Record only after its concerns are resolved.

These are internal responsibilities within `needs_research`, not new runtime
states or pastor-facing tasks. Keep the cards, the saved draft, and the
editorial record in a private working directory outside the dated sermon
folder; use the host's existing run directory when available. Include their
paths in the run notes so an interrupted run can resume. They do not replace
the source ledger or receipts. Keep run notes to a tally rather than a narrative.
Batch independent web fetches in one turn. Run the writing pass's preflight
before the first `record` call, and add no source after it. An interactive
run should reach `research_complete` in under ten minutes; a scheduled run
may take longer when it goes deeper.

The lead owns source sufficiency and final acceptance. Use a model suited to
sustained synthesis for research and writing. Without delegation, perform the
editing pass as a separate sequential pass and state the independence limit in
run notes. Do not claim independent review from self-review.

Produce a full `research-brief.md` with the required headings, substantive
interpretive conversation, several possible preaching centers, and followable
citations. Keep source coverage,
retrieval evidence, and research gaps in the receipt ledger. Surface a research
limitation in the brief only when it materially changes how a claim should be
used, and then through attribution and cited scope, never as a note about
searches or access. `Questions for reflection` is the final heading. Do not select the sermon
center or write the pastor's response.

For a pastor-selected passage, keep the published text verification in
`readings.md` and its receipt. The research brief states the pastor's selection
provenance but does not expose a technical `Text verification` field.

Organize theological voices under question-shaped thematic subheadings in
`Interpretive Conversations`. Within each question, put the strongest credible
readings into conversation, distinguish agreement from differences in emphasis
or genuine conflict, and state the choice the pastor may need to make. Use the
methodology's research and writing standard even with a church-owned template.
Give each dispute one home. Do not produce a
roster of one summary paragraph per theologian or repeat a dispute in a second
section.

Record the research source ledger and
a `research_target` containing the primary reading role and exact verified
citation. In lectionary mode, set `selection_basis` to `church_profile` or
`pastor_override`. In pastor-selected mode, set it to `pastor_selection`.

Record with the same command shape and `--stage research`. For a complete,
valid metadata example (`research_target` and the source ledger together), see
[source-verification.md](references/source-verification.md#complete-research-metadata-example).

## `research_complete`

Present `research-brief.md` as ready for the pastor's study and discernment.
Also identify `readings.md` as its verification record. Do not request
reflections, offer to draft automatically, or imply that another workflow stage
is pending. `next_actions` must be empty.

## Replacement and failure rules

- Replacing a stage requires the pastor's awareness and the `--replace` flag.
- Replacing readings preserves the research file and makes its receipt stale.
- Never delete pastor work to repair state.
- A source conflict, unsupported claim, missing research focus, or unconfirmed
  pastor-selected passage blocks progress with a plain explanation.
- The workflow writes no church data into the Labs repository.
- A future Monday 7:00 a.m. automation must invoke this same skill and end at
  `research_complete`. Automation activation requires successful manual Codex
  and Claude research-only runs first.
