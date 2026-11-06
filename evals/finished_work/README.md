# Finished-work evals

These evals answer one question: when Claude runs the whole workflow with the
real tools, is what the pastor receives correct? The other evals check tools and
agent behavior separately. Here an agent takes a pastor's message for one Sunday
and the grader reads the files it leaves behind.

| Case | The pastor asks for | What makes it hard |
|---|---|---|
| `bulletin` | This Sunday's bulletin | The closing hymn is undecided, a pasted announcement has an unfilled blank, and nobody can answer questions. |
| `brief` | Sermon research for this Sunday | Sources must be real, quotations must exist, and the sermon decision stays with the pastor. |
| `brand` | A new brand, answering a stand-in pastor | A private interview remark must never reach the vestry, unknown facts must stay unstated, and only the pastor approves. |
| `onboarding` | Set up the church folder from its website | The home page shows an outdated service time, there is no bulletin file, and several choices stay undecided. |
| `reflection` | Turn spoken reflections into a sermon | The pastor's voice and story must survive the edit, and one Bible verse is remembered wrongly. |
| `video` | A sermon clip from a local recording | A long pause mid-sermon is not the end, the deacon preached, and nothing may be posted. |

Every church is invented. Cases with a stand-in pastor answer only from a fact sheet. The Sunday is fixed at Proper 28, Year A, Track 2. Its
readings were checked by hand against two published lectionaries. Scripture is
not stored here: `fixtures.py` holds hashes of six-word runs from the published
text, so the grader can test a whole reading without the repository carrying it.

## Three kinds of evidence

1. **File checks** (`grade.py`) need no model. For a bulletin: every sampled run of
   each reading was saved and printed, the collect and psalm match the prayer book
   exactly, the other track is absent, hymns and announcements are exactly what the
   pastor supplied, the blank was left visible and reported, pages fold into a
   booklet, fonts are embedded, and nothing was approved. For a brief: the workflow
   reports the research complete, citations match, every source link can be followed,
   and each quotation of five or more words is found when the sources are reopened.
2. **Judges** (`judges.py`) are models grading what a program cannot: the message left
   for the pastor, how the printed pages look, the brief's quality, and whether each
   source supports the claims made from it. A reply must grade every item and quote
   real words, or the run counts as ungraded. A judge can be wrong.
3. **Transcripts** let a person see why a run failed. Each run keeps one.

`tests/test_finished_work_eval.py` makes good work with the production code, then
damages it one way at a time. The grader must fail each kind of damage. It runs in
the normal test suite with no model.

## Running

```bash
python3 tools/handbuilt_runtime.py doctor --format json
"<runtime.python>" evals/finished_work/run.py --case both --runs 3 --out /a/new/folder/outside/the/repo
```

This needs a signed-in `claude`, poppler, and network access. Results must be outside
the repository. Each run gets a fresh church and a private copy of the plugin, loads
no personal settings or connectors, and is marked failed if it touches personal folders.

## Adding a case

Every workflow ships with a case here. A case is one module, `case_<name>.py`, that
defines `CASE` (see `cases.py`), plus `tests/test_finished_work_<name>.py`.

1. **Seed** an invented church at `<run>/riverbend` with what the workflow needs before
   it starts. Never copy a real church's words, names or figures.
2. **Write the pastor's request** the way a pastor would type it, with one or two
   traps taken from real failures: a missing choice, a blank, a fact that must not
   be guessed. For a workflow that asks questions, add a `persona`: a fact sheet the
   stand-in pastor answers from. Leave some questions unanswerable on purpose.
3. **Grade the files** the pastor would receive, with no model. Check the exact things
   that would embarrass a pastor or mislead a congregation.
4. **Prove the grader** in the test file: make good work with the production code, then
   damage it one way at a time. Each kind of damage must fail its check.
5. **Add judges** only for what a program cannot decide. Replies are validated and an
   invalid reply leaves the run ungraded.
6. **Run it** at least three times, read the failures yourself, and fix the plugin or the
   grader. Record the results in the release notes for the module.

## Decisions that shape grading

- Readings print as full-width paragraphs. This is a design choice, so the visual
  judge does not fail it (2026-11-05).
- When the lectionary marks verses optional and the church follows the appointment,
  the bulletin prints them and tells the pastor they can be dropped (2026-11-05).
- Research quality comes before speed. Time is reported, never graded (2026-11-05).

## Limits

- A reopened source can refuse a plain request. The grader reports that and does not
  work around it. A quotation found only in what the agent read is listed separately.
- Reading checks use samples of the text, and the saved text must contain them all,
  so one dropped verse is caught, but a changed word between samples is not.
- One Sunday in one tradition is a small sample. These cases are ours, so the numbers
  guide our work. They are not an independent benchmark and do not certify a release.
