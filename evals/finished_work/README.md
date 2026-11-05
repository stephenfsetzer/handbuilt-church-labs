# Finished-work evals

These evals answer one question: when Claude runs the whole workflow with the
real tools, is what the pastor receives correct? The other evals check tools and
agent behavior separately. Here an agent takes a pastor's message for one Sunday
and the grader reads the files it leaves behind.

| Case | The pastor asks for | What makes it hard |
|---|---|---|
| `bulletin` | This Sunday's bulletin | The closing hymn is undecided, a pasted announcement has an unfilled blank, and nobody can answer questions. |
| `brief` | Sermon research for this Sunday | Sources must be real, quotations must exist, and the sermon decision stays with the pastor. |

The church is invented. The Sunday is fixed at Proper 28, Year A, Track 2. Its
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

## Limits

- A reopened source can refuse a plain request. The grader reports that and does not
  work around it. A quotation found only in what the agent read is listed separately.
- Reading checks use samples of the text, and the saved text must contain them all,
  so one dropped verse is caught, but a changed word between samples is not.
- One Sunday in one tradition is a small sample. These cases are ours, so the numbers
  guide our work. They are not an independent benchmark and do not certify a release.
