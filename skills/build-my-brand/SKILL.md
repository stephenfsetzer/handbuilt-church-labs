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
- [Interview](references/interview.md): the seven questions and how to ask them.
- [Lessons](references/lessons.md): the teach-and-choose rounds.
- [Direction proposals](references/direction-proposals.md): how to build and show directions.
- [The studio](references/studio/README.md): the firm's roles, the phases after direction, and [model routing](references/studio/routing.md).
- [Image briefs](references/image-briefs.md): the editorial brief an image model needs for each concept.
- [Brand system](references/brand-system.md): what build stages, the schema, the survival checks, and the templates.
- [Guide format](references/guide-format.md): how each guide section is written.
- [Small operations](references/small-operations.md): lockups, announcement images, posters, seasonal color, on-brand checks after the workflow.

## Four rules that never bend

1. **Teach, then ask.** No decision goes to the pastor before the pastor has
   the concept needed to make it. Each lesson is short, in church language,
   and ends in a choice.
2. **Show options; never ask for adjectives.** Taste is elicited by putting two
   or three concrete things in front of the pastor. Do not ask a pastor to
   describe a feeling, mood, or aesthetic in words.
3. **Every recorded decision carries its why.** The workflow interface
   refuses a decision without a rationale. Write the rationale in the
   pastor's own terms, from what they actually said.
4. **Fidelity only rises, and you judge the work.** Every presentation after
   the direction shows at least what the pastor saw last time, more real.
   The interface refuses a record that shows less. A round that passes
   every rule and produces generic work is a failed round; redirect it.

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
any round loses nothing. A run that began before the plan stage existed
reports the plan in `owed_stages`; record it first.

If `start` does not report `ready`, the host agent may prepare the runtime
with the `setup` operation in `handbook/runtime-setup.md`, then run the
doctor again. Do not ask the pastor to install packages.

### Starting over

If the pastor wants to begin an unfinished run again, archive it rather than
editing around it:

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

Ask the seven questions in [Interview](references/interview.md), one at a
time, each framed as a decision with its consequences. Capture the answers
verbatim where you can. The content file is the brief itself, written for
`brand/brief.md`; the metadata carries `answers` keyed by the seven question
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

### Direction: one idea, shown in context

Build directions per [Direction proposals](references/direction-proposals.md).
Each is a whole composition: the bulletin cover, the church's own test
announcement, the website's first screen, set in the direction's type and
palette with a placeholder where the mark goes. No mark is shown; on the
refresh path the kept mark appears unmodified. Record `applications` and
`boards`. These boards set the fidelity bar for everything after them.

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
Voice is derived from the pastor's picks among rewrites.

### The image studio: where the symbol comes from

Language models cannot draw a church mark. Hand-written SVG and agents
drawing from prose produce generic clip art, however clean. The symbol comes
from an image model given a full editorial brief per concept (see
[Image briefs](references/image-briefs.md)). Claude and Codex write the
briefs, curate the results, compose the boards, and write the system.
Hand-authored SVG is for construction and cleanup (the grid, the wordmark,
lockups, the small variant), never for the symbol itself.

The loop: draw a round from the briefs, show the pastor two or three and
take reactions, draw again or make precise edits of the chosen image, then
vectorize the one the pastor keeps.

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand draw --round <name> --brief-file <brief.md> [--n 4] [--reference <png> ...] [--provider openai|recraft]
python3 "<church-folder>/handbuilt.py" build-my-brand edit --round <name> --source <chosen.png> --instruction-file <edit.md> [--n 2]
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

Service keys live on the computer, never in the church folder: the
environment (`OPENAI_API_KEY`, `RECRAFT_API_KEY`) or a key file in the
Handbuilt support folder. `keys status` shows which services are set up
without printing a key; `keys set --provider <name>` reads the key from
standard input. If a key is missing, say so plainly and offer the host's own
image tool; never ask the pastor to paste a key into the conversation.
Explorations stay under staging as the record, and the chosen mark is
always an editable SVG.

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
`build` metadata lists `staged_files`. Nothing is live yet.

## 7. Prove it on something real

Render the church's most recent bulletin with the staged brand and place it
beside the current one, and render the church's own test announcement from
the image-language rules. Use the bulletin skill's production interface with
a brand file that points at the staged assets; do not hand-edit the live
`brand.json`. Put the pages in the guide section side by side. Record `prove`
with `before`, `after`, and `announcement` paths. Then show the pastor and
ask for approval in plain words: this replaces the live brand, and the old
one is kept under `brand/archive/`.

```bash
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
entry only when something durable changes.

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
