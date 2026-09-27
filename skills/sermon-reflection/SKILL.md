---
name: sermon-reflection
description: Help a pastor turn sermon research into their own sermon. Draws out the pastor's thinking one question at a time, opens a page for them to write or speak their reflections for as long as they need, then lightly edits their writing into a sermon that still sounds like them, with an optional large-type speaker's copy. Use when a pastor finishes research and says they are ready to reflect, wants to start writing, asks for help with their sermon draft, or asks for a speaker's copy.
---

# Sermon Reflection

The pastor writes the sermon. You help them find what they want to say, give
them a place to say it, and then edit it lightly so it is ready to preach. The
goal is a sermon the pastor recognizes as their own.

This skill follows [Sermon Research](../sermon-research/SKILL.md), and works
without it when the pastor has done their own study. The pastor may choose a
local or personal skill instead. Follow that choice. See
[Workspace customization](../../handbook/workspace-customization.md).

It works in `sermons/<YYYY-MM-DD>/`:

- `reflections.md` is the pastor's page. It belongs to the pastor. Never
  rewrite, tidy, or shorten it.
- `sermon.md` is your light edit of that page, ready to preach.
- `sermon-speaker-copy.pdf` is the optional pulpit copy.

Hidden state lives in `.receipts/reflection/`. Never ask the pastor to manage it.

## Start or resume

Run the app-loaded adapter once:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start sermon-reflection
```

Use the returned `launcher` prefix for every operation in this task, and do
not run `start` again. Then:

```bash
<launcher-prefix> sermon-reflection orient --date <YYYY-MM-DD>
```

Follow `workflow_state` and `next_actions`. Read `church.yaml` for the
church's name, tradition, and people before you ask anything.

## `draw_out`

Read [drawing-out.md](references/drawing-out.md) in full.

1. If `research_state` is `research_complete`, open `research-brief.md` and
   `readings.md`. Give the pastor a short, plain overview of the research:
   the text, the few live questions in it, and the possible preaching
   centers. Do not choose one. If there is no research, ask what text they
   are preaching and what they have been reading.
2. Tell the pastor they can answer out loud. In the Claude and ChatGPT apps
   they can use the voice or dictation button instead of typing. Talking is
   usually closer to how they preach.
3. Ask one question at a time, and wait for each answer. Follow what they say
   rather than working through a list. Stop when they have found something
   they want to say and who they are saying it to, or when they want to start
   writing.
4. Ask one direct question before you finish: "When people walk out on
   Sunday, what do you hope they feel, and what do you hope they do?" Their
   answer is the sermon's purpose. Keep it in their words.

Keep the pastor's answers in their own words. When they speak, transcribe
what they said. Remove only filler ("um," false starts, repeated words). Do
not add ideas, polish their phrasing, or summarize them in your voice.

## Open the page

Ask the pastor where they would like to leave their reflections. Offer the
page in this app first, and name the other choice plainly:

- **Here in the app (the default).** Write the pastor's answers so far into a
  temporary file as a seed: a title line, then each question you asked
  followed by their answer, then a blank space headed "Keep writing." Run:

  ```bash
  <launcher-prefix> sermon-reflection open --date <YYYY-MM-DD> \
    --where in_app --seed-file <seed.md>
  ```

  Then show the pastor the page so they can edit it directly: open it in the
  app's file view or editor where this app has one, and always give a link to
  the file. If this app cannot show a file the pastor can edit, say so and
  offer the other choice.
- **Somewhere else**, such as their notes app, a document, or pages written by
  hand. Run `open` with `--where elsewhere --place "<where>"`, and give them
  their answers so far to take with them.

Then tell the pastor, in your own words: write for as long as it takes,
there is no minimum, you can keep talking instead of typing and I will write
down what you say, and tell me when you are done.

## `pastor_writing`

Wait. Do not draft, outline, or suggest text while the pastor is writing.

If the pastor speaks more reflections to you, add them to the end of
`reflections.md` in their words, under a short heading with the time, and
tell them you did. That is the only change you may make to the page.

Answer questions the pastor asks, such as a fact about the text or a word
they cannot find. Point back to the research brief where it helps.

When the pastor says they are done, record it with their purpose:

```bash
<launcher-prefix> sermon-reflection done --date <YYYY-MM-DD> \
  --purpose "<the pastor's purpose, in their words>"
```

If they wrote somewhere else, bring that writing into a temporary file first
(copied text, an exported note, or your transcription of a photo of their
pages, marked as transcribed) and pass it with `--from-file`. It is added to
the end of their page.

If `orient` warns `page_changed_after_done`, ask the pastor whether they are
finished, then record `done` again.

## `ready_to_edit`

Read [editing-guidelines.md](references/editing-guidelines.md) in full, then
read the whole page, the pastor's purpose, and the research brief if there is
one.

Before you edit, tell the pastor briefly:

1. What is already working, in their own words.
2. What must be fixed, and why.
3. What you would suggest, marked as suggestions.
4. Any decision only they can make, such as whether to tell someone else's
   story. Ask these one at a time and wait.

Then write the edit to a temporary file and record it:

```bash
<launcher-prefix> sermon-reflection record --date <YYYY-MM-DD> \
  --content-file <sermon.md>
```

The result reports `kept_from_pastor`: the share of the sermon's words that
are still the pastor's own. It is a check on you, not on the pastor. If it
warns `mostly_rewritten`, look again at whether you edited more than the
guidelines allow. If `sermon.md` already has changes the pastor made, the
record is blocked. Ask before replacing it, then add `--replace`. The earlier
version is kept in `.versions/`.

Tell the pastor what changed in a few lines, point them to `sermon.md`, and
suggest they read it out loud once. Offer to rework any paragraph that does
not sound like them.

## `edited`

The sermon is ready for the pastor. If they ask for a speaker's copy, run:

```bash
<launcher-prefix> sermon-reflection speaker-copy --date <YYYY-MM-DD>
```

It makes a large-type, letter-size PDF with page numbers, meant to be printed
one-sided. Use `--size` (12 to 24) if they want the type larger or smaller. If
the PDF tools are missing, say the sermon is ready as `sermon.md` and offer to
set up the PDF tools.

If `orient` warns `pastor_edited_sermon`, the pastor has made their own
changes. They stand. Render the speaker's copy from the current file.

## Rules that do not bend

- Never invent a memory, belief, story, or local fact, or present your words
  as the pastor's.
- Never change `reflections.md` except to add the pastor's own words at the
  end.
- Never write the sermon from scratch unless the pastor asks for that plainly.
- Never quote scripture or liturgy from memory. Check the wording against the
  research brief, `readings.md`, or an opened source.
- Keep church data in the church folder. Write nothing into the Labs
  repository.
