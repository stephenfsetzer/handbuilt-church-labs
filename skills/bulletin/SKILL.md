---
name: bulletin
description: Prepare, render, verify, and approval-finalize a weekly worship bulletin in a church folder. Use when the user asks to build or prepare a bulletin, save weekly clergy assignments, change bulletin preferences, inspect bulletin history, or finalize a reviewed bulletin.
---

# Weekly Bulletin

Work inside the church's private folder. Use this skill's production interface
instead of calling renderer scripts directly.

Read [Worship text and source records](references/worship-text.md) when a
private or locally formatted prayer or reading text is needed.

The public production interface has four operations: `orient`, `produce`,
`revise`, and `finalize`.

## 0. Confirm the bulletin runtime

Compare the saved plugin root in `.handbuilt/installation.json` with this
app-loaded skill's plugin root. If they differ, reconnect using the installed
[onboarding connection reference](../onboarding/references/connection-and-brand.md)
before running the launcher. An old cache may still exist after an update.

Before interviewing the pastor or staging a bulletin, verify the connected skill and runtime:

```bash
python3 "<church-folder>/handbuilt.py" start bulletin
```

If it does not report `ready`, stop before production. The host agent may
prepare the private runtime with the `setup` operation defined
in `handbook/runtime-setup.md`, then must run the doctor again. Do not ask the
pastor to install packages or use global Python. Do not present a bulletin as
ready until both the Python packages and the computer-level PDF tools pass.

Read the exact skill path returned by `start`. The launcher selects the managed
Python for production and records the installed workflow used. For supporting
tools invoked directly, use the returned `runtime_python` executable. If the
connection is missing, repair it through onboarding. Do not create a substitute
renderer or use a personal PDF skill.

## 1. Orient

Run:

```bash
python3 "<church-folder>/handbuilt.py" bulletin orient --date <YYYY-MM-DD>
```

Use the result to propose defaults from approved bulletin history and available
music assets. History means an item appeared in an approved bulletin. Do not
claim it was sung, read, or announced during the service.

Verify the lectionary day and selected citations against a published calendar.
Record each reading source with `label`, `location`, and `verified_on`.

## 2. Resolve the service

Recover the service date, standing settings, known people, and existing weekly
material before asking for more. Use the saved layout without reopening that
choice unless the pastor requests a change. Present a short summary that the
returning pastor can correct.

The agent retrieves the appointed readings, collect, and proper preface from
verified sources using the saved lectionary and worship practice. The pastor
supplies local decisions such as music, announcements, petitions, special
service changes, and unresolved assignments. Ask at most three focused
questions at a time, preferably one. Explain what the next answer enables.
Do not hand the pastor a checklist of liturgical texts to gather when the
agent can verify and retrieve them.

If the pastor asks only to prepare assignments or pauses before production,
save the dated work and stop at that boundary. Explain the sourcing you will
do when work resumes, then ask only for the next missing local decision. For
example: "I have the clergy assignments. When we build the bulletin, I will
verify the readings and prayers. Do you have this week's music selections?"

Before resolving the weekly input, read the `worship_profile` path in
`church.yaml` (normally `worship/profile.yaml`). Present its standing
worship choices, their source or tradition pack, and any unresolved values.
Resolve the profile through the worship-resolution module before constructing
the weekly bulletin input:

```bash
<runtime.python> <skill-dir>/scripts/worship_resolution.py \
  --church-folder <church-folder> --weekly-input <weekly-overrides.json>
```

Its result supplies context for review; human approval remains a separate step.
If the result is `needs_input`, inspect the listed reasons. Retrieve and check
missing public worship text when a reliable source is available, then save its
private source copy and provenance. Ask the pastor for unresolved choices,
conflicts, or local and licensed material that the agent cannot obtain.
Rerun resolution before producing.
The weekly caller must supply `service.variant` as the configured variant id
when a profile declares service variants. Read back its exact name and
confirmation policy, then resolve the private order file. An unknown,
unsafe, missing, cyclic, or service-plan-mismatched variant is `needs_input`
with an actionable reason. Never infer a variant from a date, denomination,
history, or renderer default.

For an ordinary service, the caller must supply `service.variant: none` when
variants are configured. The resolved object records that explicit choice at
`liturgy.service_variant`; selected variants also record their private order
file chain and confirmation policy at
`liturgy.service_variant_provenance`.

Use the [bundled Sunday library](references/sunday-library.md) before fetching
standard worship text. Standard BCP selections need no private source path or
pastor-supplied URL. Read only the chosen collect, preface, or psalm entry.
A private override still requires its own verification. For Lutheran licensed
material, help prepare a reusable private source from the church's permitted
material rather than asking the pastor to build technical files.

Resolve weekly `liturgy` fields explicitly. Never infer a Eucharistic Prayer,
Lord's Prayer form, Prayers of the People form, or local communion welcome
from denomination or history. Labs supplies `general-blessing` as the standing
fallback. A church may select a private named blessing in its worship profile
or for one week. Other missing required choices block production until
resolved.

Standing worship preferences are saved in `worship/profile.yaml`. The profile
supports traditional, custom, or omitted doxology; a confirmed psalm format
and response starting side; continuous or repeated prayer labels; and concise
or source rubrics. A blank psalm format remains unresolved until the church
chooses one. A custom doxology uses the private `sources.doxology` text path.
The optional standing `church.yaml.bulletin.doxology_music` entry uses the
same fields as a hymn block. Copy it to `service_music.doxology` only when a
weekly input omits that slot. A weekly `service_music.doxology: null` means
there is no doxology music that week.

Complete lyrics are private church content. Labs does not determine whether a
church may print material it supplies and does not require a permission record.
Derive `lyric_columns` from text length and proof results; it is a layout proof
value that the agent determines during visual review. Copyrighted lyrics must never enter
the public Labs repository or its fixtures.

The weekly bulletin workflow stages `church.yaml.bulletin.footer` into the
companion `brand.bulletin_footer`. It consumes
`church.yaml.leadership` and carries
`church.yaml.bulletin.include_serving_today` and
`church.yaml.bulletin.serving_roles` into `options`, where the role list
filters the Serving Today section. It renders private lyrics supplied by the
church without applying a Labs permission policy. The public repository
contains synthetic lyric fixtures only.

Keep the distinction between standing setup and this week's service explicit.
The church profile may supply the reusable service book, prayer forms, roster,
footer, recurring role slots, and selected bulletin template. The weekly input
supplies the date, readings, hymns, preacher, celebrant, petitions,
announcements, and Serving Today assignments. Resolve a person from the
maintained `leadership.clergy_and_staff` roster only on one exact
case-insensitive role match, with a first-name shortcut only when it is unique
after printed titles are removed. Ambiguous or missing matches need a pastor's
choice. Never save a weekly assignment into the standing roster.

`merge_back_page` is a weekly approval question, never an inferred default.
When a merge is proposed, the result and receipt must show a mandatory
visual-review warning and the signature pages, sides, sheets, and blanks. The
pastor must explicitly approve that week's merge before finalization.

Read [Weekly input](references/weekly-input.md) and its linked field schema
before preparing the production JSON. Use those contracts rather than reading
the Python implementation to discover ordinary input fields. The input adds:

- top-level `template`: `classic` or `modern`
- a `source` record on each reading
- music image paths relative to the church folder or its `music/` directory
- resolved `liturgy` values, including the worship profile reference and any
  local licensed liturgy sources

Missing music scans are allowed as a labeled title-only fallback. Unverified
readings and unresolved example text block production.

## 3. Produce a review package

Include the church's provided logo on both Classic and Modern front pages. Read `brand.json`
and use the existing local mark or banner. If onboarding recorded only a logo
URL, the agent retrieves the confirmed image, saves it under the church's
private `brand/` folder, and replaces the rendering path in `logo.mark` or
`logo.banner` with that local path. Keep source provenance in the church's
onboarding notes. Do not ask the pastor to supply the same logo again when it
can be recovered. A missing or unreadable configured logo blocks production
until repaired; a church with no provided logo may use its name alone.
During visual review, check the logo on the sequential PDF's first page and
on the corresponding outer booklet cover, including legibility and proportions.

Save the resolved input to a temporary JSON file, then run:

```bash
python3 "<church-folder>/handbuilt.py" bulletin produce --input <resolved-bulletin.json>
```

Production renders the selected template, creates the 11x17 booklet, runs the
automated quality gate, stores artifacts in the dated week folder, and writes
a production receipt. A successful result is `ready_for_review`, not approved
or print-ready.

For a supplied-bulletin reproduction, compare each source section with the
rendered output before closeout. Check supplied prayer paragraphs and local
petitions, music titles, lyrics, notation, credits, and recurring information.
A field saved in JSON is not evidence that it printed. Inspect the PDFs and
their extracted text. Recover an available supplied image before accepting a
missing-image fallback. Explain any unsupported content and obtain the
pastor's choice before deliberately omitting it; a receipt does not establish
content completeness. Broad layout changes do not authorize removing words.

Show the user the sequential PDF, booklet PDF, warnings, and receipt. Human
review is required before finalization. Printing or sending requires separate
explicit authorization.

## 4. Revise a review package

If review requests a change, keep the prior package explicit and revise it with
the fourth public operation:

```bash
python3 "<church-folder>/handbuilt.py" bulletin revise \
  --prior-run <prior-bulletin-production-receipt.json> \
  --input <revision-input.json>
```

The prior receipt must be an exact path to an unapproved `ready_for_review`
package. The revision input may contain only the changed fields. The workflow
deep-merges it with the prior source-safe config, then renders a temporary
staged config. The saved `bulletin-config.json` retains church-relative music
and private liturgy source paths for the next revision.

The replacement is rendered and verified before the prior package moves to a
recoverable `.revisions/` folder. The new receipt links the predecessor run,
receipt hash, archive location, and source-config digest. Repeating the same
revision is idempotent. An approved package or an approved history entry can
never be revised or overwritten.

Legacy version 1 receipts are read without modification. Staged music is
recovered only when exactly one matching private source can be verified. A
missing or ambiguous source blocks revision and requires fresh source paths.

## 5. Finalize only after approval

Create approval JSON containing `production_run_id`, `approved_by`, and the
reviewed artifact hashes from the production receipt. An optional `note` and
`approved_at` may be included. Then run:

```bash
python3 "<church-folder>/handbuilt.py" bulletin finalize \
  --receipt <bulletin-production-receipt.json> --approval <approval.json>
```

Finalization verifies that reviewed artifacts have not changed, writes the
approval receipt, and updates approved bulletin history. If review requests a
change, revise through a new production run rather than finalizing the old one.

## Boundaries

- Private church data and licensed music stay in the church folder.
- Only approved receipts update history.
- Do not patch templates inside a church folder.
- Do not call a generated package print-ready before human approval.

The separate doxology setting applies to the Episcopal service plan. In the
Lutheran service plan, keep any doxology within the church's verified local
order or Great Thanksgiving text so it is not printed twice.
