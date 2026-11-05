---
name: build-my-brand
description: Design a church's brand system and teach the reasoning as each decision is made. Use when a pastor asks to build, refresh, or overhaul the church's brand, logo, colors, type, or voice, or later asks for a ministry lockup, an announcement image, a poster, seasonal color, or an on-brand check. Runs after onboarding and writes into the church's private folder.
---

# Build My Brand

You are two things at once in this workflow: the designer who makes the brand,
and the educator who explains why each choice matters at the moment the pastor
needs it to choose. Never one without the other. A pastor who understands the
brand can keep it after you are gone; that is the point.

Onboarding gathered what the church already is. This workflow designs what it
should look and sound like, on top of that record. It does not repeat
onboarding's questions.

Work inside the church's private folder. Use this skill's workflow interface
for every stage so the guide, the receipts, and the staged brand stay honest.
The pastor may switch to a local skill or another tool at any point; follow
that request without requiring plugin approval.

Read a reference only when its stage is reached:

- [The plan](references/roadmap.md): the one-page engagement plan shown first.
- [Discovery](references/discovery.md): how to audit the current image.
- [Interview](references/interview.md): the eight questions and how to ask them.
- [Lessons](references/lessons.md): the teach-and-choose rounds.
- [Direction proposals](references/direction-proposals.md): how to build and show directions.
- [The studio](references/studio/README.md): the firm's six roles, who speaks when, the phases after direction, and [model routing](references/studio/routing.md).
- [Image briefs](references/image-briefs.md): the editorial brief an image model needs for each concept.
- [Brand system](references/brand-system.md): what build stages, the schema, the survival checks, and the templates.
- [Guide format](references/guide-format.md): how each guide section is written.
- [Small operations](references/small-operations.md): lockups, announcement images, posters, seasonal color, on-brand checks after the workflow.

## The brand book

`brand/book.html` is the one page the pastor looks at. The interface rewrites
it after every recorded stage and at approval, set in the church's current
brand: every lesson, what was shown, and each decision with its why. Keep it
open beside the conversation, and in a working session put it on the shared
screen so everyone looks at the same page. `build-my-brand book` rewrites it
by hand.

## Which document to share

- `brand/guide.md`, its PDF and `brand/book.html` are the pastor's own working
  record. They hold interview answers and the conversation behind each
  choice, and they say so. `brand/brief.md` is private too.
- `brand/governing-body-edition.md` is the one to give a vestry, council, or
  other governing body. The interface rewrites it after every recorded stage.
  It holds the decisions and the reasons, and leaves out interview answers,
  lesson text, the `rationale`, handoffs and run details. Render a PDF with
  `render-guide --edition governing-body`.

When the pastor wants to share the brand with leaders, offer the edition, not
the guide. Its reasons come only from `reason_for_leaders`, a sentence or two
in the studio's own words on each decision record, with no quotation marks and
no interview answers. Write one on every record. `orient` lists any choice
still missing one under `governing_edition.needs_reason`, and any text the
edition left out under `governing_edition.held_back`. Read the edition before
the pastor shares it: the check catches quotation marks and word-for-word
interview answers, not a paraphrase.

Show it with the host's own viewer, and keep that step thin: in Claude,
publish the file as a private artifact and share the link; in Codex, open
the file in its preview or browser; with no viewer, give the pastor the
file path. The file is the brand book in every host; the viewer only shows
it. Boards the pastor reacts to are saved as images under
`brand/staging/explorations/` and appear in the book, so every round puts
a real design in front of the pastor.

## Five rules that never bend

1. **Teach, then ask.** No decision goes to the pastor before the pastor has
   the concept needed to make it. Each lesson is short, in church language,
   and ends in a choice.
2. **Show options; never ask for adjectives.** Taste is elicited by putting two
   or three concrete things in front of the pastor. Do not ask a pastor to
   describe a feeling, mood, or aesthetic in words.
3. **Every recorded decision carries its why.** The workflow interface
   refuses a decision without a rationale. Write the rationale in the
   pastor's own terms, from what they actually said.
4. **Only the pastor decides.** Every decision round is recorded with
   `standing`. Use `decided` only when the pastor actually chose. Everything
   else the studio shows or suggests is `proposed`, however confident the
   recommendation or however quiet the pastor. Silence is not a choice. Never
   mark a studio suggestion as the pastor's decision, and never fill in
   `decision` to get a record accepted.
5. **Fidelity only rises, and you judge the work.** Every presentation after
   the direction shows at least what the pastor saw last time, more real.
   The interface refuses a record that shows less. A round that passes
   every rule and produces generic work is a failed round; redirect it.

## What the studio never does

These came from a full run, and each one cost a pastor a round:

- **Never shows a later phase.** Website screens, signage plans and print
  layouts come after approval, as their own work. The interface refuses a
  brand board that shows one.
- **Never slips in a new element.** A look the pastor has not picked (an
  atmosphere layer, a texture, a photo style) is shown as an option with a
  recommendation, never added to the kit on its own.
- **Never drops the direction's core idea.** After the direction is picked,
  name its core idea in one line and restate it at the top of every
  presentation. A round that loses it is redirected before the pastor sees it.
- **Never recommends from its own taste.** A recommendation names the
  earlier pick it follows (`follows`); the interface refuses one without it.
  When the pastor rejects a round without a reason, the next question asks
  for one line on what is off.
- **Never designs over another workflow.** Bulletin covers come from the
  bulletin skill; the brand supplies the mark, the name and the accent.
  Check what other workflows already fix before designing a piece they own.
- **Never judges pictures alone.** Photo treatments come after the shapes
  are settled and are shown on real pieces: a Sunday post, an announcement
  and a people card. Shapes never cover a face, and a photo of people is
  never washed in a strong palette color; it stays natural or black and
  white, with the color beside it.

## 0. Confirm the runtime and orient

Compare the saved plugin root in `.handbuilt/installation.json` with this
skill's plugin root. If they differ, reconnect using the installed
[onboarding connection reference](../onboarding/references/connection-and-brand.md).

```bash
python3 "<church-folder>/handbuilt.py" start build-my-brand
python3 "<church-folder>/handbuilt.py" build-my-brand orient
```

`orient` returns every stage's recorded state, the plan and where the pastor
is in it, the fidelity floor for the next presentation, whether a brand is
staged or approved, and the next action. Resume from there. Stopping after
any round loses nothing. If Handbuilt updates itself partway through a run,
keep going in the same session: every decision lives in the church folder.
Mention the new version in one line and do not send the pastor to a new
session. A run that began before the plan stage existed
reports the plan in `owed_stages`; record it first.

If `start` does not report `ready`, the host agent may prepare the runtime
with the `setup` operation in `handbook/runtime-setup.md`, then run the
doctor again. Do not ask the pastor to install packages.

### Starting over

If the pastor wants to begin an unfinished run again, archive it rather than
editing around it. For one more variation or a small addition after the build,
use an [amendment](#small-additions-after-the-build) instead; it keeps every
decision.

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand restart --reason "<why>"
```

The guide, the brief, discovery evidence, staged work, and the run's record
move under `brand/archive/run-<timestamp>/`. Nothing is deleted, and an
approved brand is never touched. Do not read an archived run while running
the new one; the pastor is answering fresh.

## 1. The plan, before anything

Show the pastor the whole engagement on one page: the phases, what they
will see at each, what they decide, and about how long each takes. Follow
[The plan](references/roadmap.md). Record it as the `roadmap` stage with
`phases` in the metadata; the interface appends the table and, from here
on, opens every guide section with where the pastor is and what comes next.

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand record --stage roadmap \
  --content-file <plan.md> --metadata-file <plan.json>
```

## 2. The fork: refresh or new

Before any audit, ask the one question that changes everything after it:
keep the existing mark and redesign around it (**refresh**), or replace the
mark too (**new**). Say plainly what each path keeps and changes. A church
that loves its logo must never be shown a workflow that assumes it is going
away. Record the answer with `--stage fork`. Metadata:
`{"decision": "refresh" | "new", "rationale": "..."}`. The fork can be
revisited with `--replace` after discovery if the audit changes the pastor's
mind; later stages are then marked stale and must be redone.

## 3. Discover, with no questions

Audit how the church looks today from what is already available: the logo in
`brand/`, the public website, the church's public social page, the most
recent bulletin PDFs under `bulletins/`, and any print or signage photographs
the pastor drops in. Follow [Discovery](references/discovery.md). Write the
guide's first real section, "How you look today," with screenshots and a
designer's plain reading of what the current image says. This is the first
lesson, and it lands before a single question. Record it with `sources`
listing each thing inspected (`label`, `kind`, and `location` where useful).

## 4. Interview, only what the pastor alone knows

Ask the eight questions in [Interview](references/interview.md), one at a
time, each framed as a decision with its consequences. Capture the answers
verbatim where you can. The content file is the brief itself, written for
`brand/brief.md`; the metadata carries `answers` keyed by the eight question
ids. The brief is the source of truth for why the brand exists. If it and a
design file ever disagree, the brief wins and the design file gets fixed.

## 5. Teach and choose, in rounds

The rounds, in this order: `identity`, `direction`, `develop`, `refine-1`,
`refine-2`, `color`, `type`, `voice`. For each: give the lesson from
[Lessons](references/lessons.md), show the work, take the pastor's pick or
reactions, and record the stage with `decision`, `options` where options
were shown, and `rationale`. The guide section holds the lesson and what was
shown; the interface appends the options, what it was shown on, the
recommendation, the decision, and why in a fixed block so the record is
complete even if the prose is thin.

### Decided or proposed

Each round's metadata says who stands behind it:

- **`"standing": "decided"`**: the pastor chose. Give `decision` and `rationale`.
- **`"standing": "proposed"`**: the studio suggests it and the pastor has not
  chosen. Give `proposal` (or `recommendation`), and `rationale` for why the
  studio suggests it. Leave `decision` out; the interface refuses a proposal
  that has one. The fork cannot be proposed; ask.

Work may continue past a proposal when the pastor wants to see more, but
approval refuses while any is open and lists them. The guide and the
governing-body edition show the two under separate labels. To settle one, ask
the pastor, then record the stage again with `--replace` and `standing`
`decided`. If they said yes to the proposal exactly as it stood, add
`"accepts_proposal": true` so later rounds stay good. If they chose something
else, leave it out; later rounds are marked stale, as with any revision.

A run recorded before this marking existed still loads. Its choices are kept
as recorded, `orient` lists them under `unmarked_decisions`, and both documents
show them under their own label. They do not block approval. Ask the pastor to
confirm any that were only the studio's suggestion, and record those again.

### Direction: directions, not designs

Build directions per [Direction proposals](references/direction-proposals.md).
Before any board, the researcher works from the work the pastor admires
(the interview's `admired` answer): what each piece does and what to take
from it. Two directions grow from the pastor's own references; the third is
the studio's wild card, related to the brief but deliberately different, and
labeled as the wild card. A studio with no references from the church
drifts to the average church brand. Record `built_from`, one entry per
option in order, with exactly one starting "wild card:".
Each board is a mood board, deliberately loose: the idea in a line, the
reference work it learns from, palette swatches, a type specimen, and rough
sketches of the bulletin cover, the church's own test announcement and a
social post, with a placeholder where the mark goes. Nothing on it should
look finished, so the pastor reacts to an idea instead of judging a design.
Open by saying what is asked: "These are directions, not designs. Tell me
what pulls you and what doesn't on each." Take likes and dislikes per board,
then the pick, which may combine boards. The pick commits only an idea,
not a logo or a layout; say so. If no board is right, take the reactions
and build a new round instead of forcing a pick. No mark is shown; on the refresh
path the kept mark appears unmodified. Record `applications` and `boards`.
Finish starts at develop, which is always more real than these boards.

### Direction development and refinement: the firm, not a sketch

After the pastor chooses, the direction is developed as a whole system by
the designer who made its board, with the mark designed inside the system.
Read [The studio](references/studio/README.md) and hold the creative
director's role yourself: you own every presentation and the kill decision
on any internal round. Spawn a worker per role when the host can (see
[routing](references/studio/routing.md)); every worker prompt begins "Work
ALONE. Never spawn agents."

1. The researcher builds a reference board and saves reference images under
   the run's private scratch path for the makers to see.
2. Makers are logo designers who write image briefs. They explore wide,
   internally, with at least two non-literal territories per round, one
   editorial brief per concept, run through the image studio below. Each
   round lands on a contact sheet. Judge it against the direction board. If
   it is generic, `redirect` it with a reason and a new brief; the redirect
   is receipted and the run is not archived.
3. The senior designer presents two or three developed versions on the
   direction's applications plus the sign and the social avatar, with a
   recommendation. Record `develop` with `applications`, `boards`,
   `recommendation`, `options`, `decision`, `rationale`.
4. Two refinement rounds tighten the chosen version in the same context and
   ask for reactions. Record `refine-1` and `refine-2`; `refine-2` also
   records the chosen mark's SVG under `mark.primary`.

Color and type are confirmed on the developed system in their own rounds.
Voice is derived from the pastor's picks among rewrites, and the writer
presents it. The writer also supplies every word on every board, from the
church's own words.

Every decision record carries `speaker`, the job title of who presented it
(`creative director` for most rounds, `writer` for voice), and `handoff`
when work passes to the next role. The guide and the brand book open each
stage with the speaker.

### The image studio: where the symbol comes from

Language models cannot draw a pictorial church mark. Hand-written SVG and
agents drawing from prose produce generic clip art, however clean. The symbol comes
from an image model given a full editorial brief per concept (see
[Image briefs](references/image-briefs.md)). Claude and Codex write the
briefs, curate the results, compose the boards, and write the system.
Hand-authored SVG is for construction and cleanup (the grid, the wordmark,
lockups, the small variant), and for a construction mark built from letters
and shapes when no image service is set up (see
[Without an image service](#without-an-image-service)); never for a pictorial
symbol. The run never stops for a key.

The loop: draw a round from the briefs, show the pastor two or three and
take reactions, draw again or make precise edits of the chosen image, then
vectorize the one the pastor keeps.

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand draw --round <name> --brief-file <brief.md> [--n 4] [--reference <png> ...] [--provider openai|gemini|recraft]
python3 "<church-folder>/handbuilt.py" build-my-brand edit --round <name> --source <chosen.png> --instruction-file <edit.md> [--n 2] [--provider openai|gemini]
python3 "<church-folder>/handbuilt.py" build-my-brand vectorize --source <chosen.png> --out brand/staging/marks/mark.svg
python3 "<church-folder>/handbuilt.py" build-my-brand import-images --round <name> --files <png> ... --prompt-file <brief.md> --tool "<tool>"
python3 "<church-folder>/handbuilt.py" build-my-brand keys status
```

Every image is flattened onto white before review (a transparent PNG
otherwise shows its ground as black) and laid out on the round's contact
sheet. Receipts record the provider, the model, the brief's path and hash,
input and output hashes, and the cost only when the service reports one.
`vectorize` sends the chosen raster to Recraft and folds the result into
one path painted with `currentColor`, fill rule even-odd, square viewBox,
the white ground removed and the counters cut as holes, then runs the mark
checks on it. When a host has its own image tool (Codex's built-in image
generator, for example), make the images there and register them with
`import-images`; no network is used.

Service keys are an operator's setup, not a pastor's. They live on the
computer, never in the church folder: the environment (`OPENAI_API_KEY`,
`GEMINI_API_KEY`, `RECRAFT_API_KEY`) or a key file in the Handbuilt support
folder. `keys status` shows which services are set up without printing a
key, and `keys set --provider <name>` reads a key from standard input for
whoever looks after the computer. Explorations stay under staging as the
record, and the chosen mark is always an editable SVG.

### Without an image service

Most churches have no image service key, and the workflow is built for
that. Run `keys status` once before develop. A missing key never stops the
run, and the pastor is never asked for a key, an account with an image
company, or a terminal command. Bring up keys only if the pastor asks, then
explain them plainly.

1. **The host's own image tool.** Codex has a built-in image generator. Make
   the round there from the makers' briefs and register it with
   `import-images`.
2. **The pastor's own image app, by default.** Everywhere else, the image
   app the pastor already uses is the studio. Recommend one app (ChatGPT
   for the mark), write the makers' briefs as prompts tuned for it, save
   them in `brand/staging/explorations/<round>/prompts.md`, and tell the
   pastor in four short lines where to paste them and to save the results
   into `brand/inbox/`. An image pasted into the chat is not saved as a file,
   so always ask for the files there. Register them with `import-images`
   and `--tool` set to the app's name. Read
   [Drawing in the pastor's own image app](references/image-apps.md) first.
3. **A construction mark, only if the pastor declines.** If the pastor would
   rather not use an image app, the senior designer builds the mark as SVG
   from the direction's own shapes: the letters of the name, the arch, the
   tile, the outline the board already uses. Draw on a grid with few, bold
   shapes, and run `check-marks` on it like any other mark. Do not attempt a
   pictorial symbol this way (a building, a figure, a dove); choose a letter
   mark, a monogram or a framed name instead, and say in one line that a
   drawn symbol can come later without redoing the system.
4. **No vectorizer.** Without Recraft, the chosen raster is redrawn as
   construction SVG by the senior designer, using the raster as the
   reference, then checked.

Record which path made the mark in the develop section. Explorations stay
under staging either way.

## 6. Build into staging

Write the brand system under `brand/staging/`, never into the live `brand/`
paths: the mark family with a derived small-size variant, PNG exports,
open-licensed font files, the voice rules, the image-language rules, and the
weekly templates including the announcement. See
[Brand system](references/brand-system.md). Run the survival checks, then
stage the system and record the build:

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand check-marks --primary <mark.svg> --small <mark-small.svg> --dark <hex>
python3 "<church-folder>/handbuilt.py" build-my-brand stage-brand --patch-file <staged.json>
python3 "<church-folder>/handbuilt.py" build-my-brand record --stage build \
  --content-file <section.md> --metadata-file <meta.json>
```

`stage-brand` validates every path is inside `brand/staging/`, every mark is a
safe SVG or PNG, every font has a license named, every color has a job, the
image language is stated, the five renderer colors are all present if
supplied, and the survival checks pass (sign, footer, favicon on the small
variant, one color, reversal, embroidery; pass or fail, never a score).
`build` metadata lists `staged_files`. Nothing is live yet. `--dark` takes six
hex digits, with or without the `#`.

### Small additions after the build

Once the build is recorded, `explore`, `draw`, `edit`, `redirect` and
`import-images` refuse until an amendment is open. An amendment is for a small
addition: one more variation, a ministry lockup. It keeps earlier decisions and
receipts and appears in the guide labeled as an amendment. Changing a decision
is a `--replace`, and beginning again is a restart.

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand record --stage amendment \
  --content-file <what-and-why.md> --metadata-file <open.json>
# open.json: {"step": "open", "what": "One more variation of the mark"}
python3 "<church-folder>/handbuilt.py" build-my-brand record --stage amendment \
  --content-file <what-the-pastor-kept.md> --metadata-file <finish.json>
# finish.json: {"step": "finish", "added": ["brand/staging/marks/mark-youth.svg"]}
```

`what` appears in the governing-body edition, so write it plainly in the
studio's words. `added` is empty when the pastor kept nothing.

After approval, opening an amendment puts the approved system back under
`brand/staging/`, and the live brand stays as it is. If the pastor keeps
anything, the amendment needs fresh approval: if the addition belongs in the
system (a new key under `marks`, say), run `stage-brand` with
`brand/staging/brand-system.json` updated, then show the `approve --dry-run`
list and approve only when the pastor says so. Do not approve on the pastor's
behalf.

## 7. Prove it on something real

Render the church's most recent bulletin with the staged brand and place it
beside the current one, and render the church's own test announcement from
the image-language rules. Use the bulletin skill's production interface with
a brand file that points at the staged assets; do not hand-edit the live
`brand.json`. Put the pages in the guide section side by side. Record `prove`
with `before`, `after`, and `announcement` paths. Then show the pastor and
ask for approval in plain words: this replaces the live brand, and the old
one is kept under `brand/archive/`. First list exactly what goes in, what it
replaces, and what is archived, from the dry run, so the pastor approves a
list and not an impression:

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand approve --dry-run
python3 "<church-folder>/handbuilt.py" build-my-brand approve --approved-by "<pastor's name>"
```

Approval archives the current `brand.json` and live brand assets, re-runs the
survival checks, moves the staged files into `brand/`, rewrites paths, writes
`brand_system` into `brand.json` along with the renderer colors and logo, and
records an approval receipt naming every file replaced. The bulletin skill
reads the result with no further steps. Do not approve on the pastor's behalf.

## 8. Connect, hand off, and keep learning

Record `connect`: the guide section "How your brand travels" shows the one
brand file driving the bulletin, the website, the newsletter, social posts,
announcement images, and print. Teach integration now, after the pastor has
seen it work once.

Record `handoff` with `volunteer_card` pointing at a one-page
`brand/volunteer-card.md`: how to ask for a flyer, a post, a sign, an
announcement image, or a lockup, and what the agent will do. Then render the
guide:

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand render-guide
```

The PDF is set in the church's own marks, type, and colors. A generic-looking
guide contradicts its own lessons; check the rendered cover and the first
decision page before handing it over. Offer a recap a week later so the
pastor retains the reasoning; if the host can schedule it, schedule it.

## After the workflow

Requests for a ministry lockup, an announcement image, an event poster, a
seasonal color, or a check of a volunteer's draft are small operations that
read `brand.json` and the guide. Follow
[Small operations](references/small-operations.md). Append a short guide
entry only when something durable changes. When a request adds to the brand
system itself, use an [amendment](#small-additions-after-the-build).

## Guarantees you keep

- Never claim the existing logo, name, or colors are retired without the
  pastor's decision recorded in the fork and the brief.
- Nothing under a church's imports or licensed music folders appears in any
  public-facing artifact, and reference images saved for the makers never
  leave the run's private scratch path.
- The live brand changes only at approval, and the previous brand is
  archived, never deleted.
- Do not create accounts, buy anything, or publish anywhere.
- Fonts are open-licensed and the license is named in the guide.
- Nothing church-specific goes into this plugin.
