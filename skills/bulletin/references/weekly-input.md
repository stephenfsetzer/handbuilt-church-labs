# Prepare the weekly input

If this week's content draws on a bulletin imported during onboarding, check
[source import and inventory](source-inventory.md)'s `validate_for_production`
before relying on it; a mapped section that never made it into this JSON, or
one whose source changed, blocks there rather than silently missing.

Use this reference and the [field schema](../renderer/bulletin-config-schema.json)
before preparing JSON. The [example](../renderer/example-bulletin-config.json)
illustrates field shapes only. Its names, date, readings, music, and placeholders
are not defaults for a church. Ordinary production does not require reading the
Python implementation or inventing a renderer.

The agent builds one private JSON object:

| Field | What to save |
| --- | --- |
| `template` | The saved `classic` or `modern` choice, at the top level. |
| `service` | `date` (YYYY-MM-DD), `occasion`, `proper`, `lectionary_track`, `preacher`, `celebrant`, and `liturgical_color`. Verify calendar facts; resolve people from saved context or ask about that week's assignments. |
| `readings` | Enabled `first` and/or `second` lessons, plus `psalm` and `gospel`. Write only the `citation` for each Bible reading and the `number` for the psalm, then [let the tool copy the texts](#let-the-tool-copy-the-texts). The finished file holds each reading's full verified `text` and a `source` object containing `label`, `location`, and `verified_on`. The psalm prints a small "The Psalm" label and a larger heading, `Psalm <number> (<latin_title>)`; an optional psalm `heading` replaces that larger line when the pastor asks for different wording. The resolved `liturgy.include_first_reading` and `include_second_reading` flags control which lesson slots are required and printed. At least one non-Gospel lesson remains required. |
| `collect_of_day` | Verified text for the selected occasion. Write `{"library": "<name>"}` with its name in the bundled Sunday library, and the tool copies the text. |
| `proper_preface` | The verified selected preface when required by the prayer, written the same way. |
| `liturgy` | The `liturgy` object returned by worship resolution, including its service plan and profile reference. |
| `hymns`, `service_music` | The week's selections. Empty objects represent no selections; do not copy example hymns. Music blocks may include `composer`, which prints as a plain source credit. Service music supports `prelude`, `gloria`, `psalm_antiphon`, `offertory_anthem`, `sursum_corda`, `sanctus`, `fraction_anthem`, `doxology`, `communion_anthem`, and `postlude`. Lutheran plans support `prelude`, `psalm_antiphon`, `offertory_anthem`, `communion_anthem`, and `postlude`. Unsupported or unknown nonempty slots are rejected. |
| `announcements` | The week's announcements, or an empty list when none were supplied. An entry may add `image` or `images` (church-relative paths, resolved like a hymn image) to carry a supplied event poster or inline QR graphic, and an optional `caption`. `text` is optional when the image already carries the content; `title` is still required. |
| `parish_information` | Optional. Omit it to use the church's saved standing sections. Set `before_service` and/or `after_service` explicitly, including an empty list, to override or suppress that scope for this week only; each is an ordered list of `{title, text}`. |
| `options` | Supported weekly display choices from the schema. Do not invent a `presentation` wrapper. |

## Let the tool copy the texts

Do not type a reading, a psalm, the collect, or the preface yourself, in the
file, in a command, or in a message to the pastor. Write the file with names
only:

```json
"readings": {
  "first": {"citation": "Ezekiel 33:7-11"},
  "psalm": {"number": "119:33-40"},
  "second": {"citation": "Romans 13:8-14"},
  "gospel": {"citation": "Matthew 18:15-20"}
},
"collect_of_day": {"library": "proper-18"},
"proper_preface": {"library": "lords-day"}
```

Copy the `liturgy` object in first, because the psalm follows its saved
response format. Then run:

```bash
<runtime.python> <skill-dir>/scripts/weekly_texts.py fill --input <weekly-file> \
  --lectionary-page <this Sunday's page on https://lectionarypage.net/>
```

The tool downloads that page, finds each lesson by its citation, and writes
the words and their source into the file. The psalm, collect and preface come
from the bundled Sunday library. It reports each part it filled and how many
words, never the words themselves. Write each citation as the page prints it.
When the page has no lesson with that citation, the tool lists the ones it
has, and the file is left unchanged.

- **Optional verses in a lesson.** The page sets them off in square brackets.
  The tool stops and asks until you add `--optional-verses include` or
  `--optional-verses omit`, following `lectionary.optional_verses`.
- **Optional verses in the psalm.** Write the verses to print in `number`:
  `"90:1-12"` includes them and `"90:1-8,12"` leaves them out.
- **A reading the pastor chose from somewhere else.** Save the pastor's source
  as a file in the church folder and record it as a church source. Do not
  retype it.
- **Checking the result.** Read the review PDF, not the file. Do not print the
  file's readings to check them.

A part that already has `text` is left alone, so a pastor's own wording is
never replaced.

When the pastor has not chosen a hymn yet, save a visible blank for that slot,
such as `{"title": "[Closing hymn to be chosen]"}`, and ask for the choice.
Never choose a hymn for them. Production lists the bracket under `open_items`,
so it cannot reach print unnoticed.

`lectionary.optional_verses` in `church.yaml` decides optional verses, such as
Psalm 90:1-8, (9-11), 12. `include_all` prints them and `omit_optional` leaves
them out. `appointed` follows the published appointment: print the optional
verses and tell the pastor they can be dropped. `ask_each_week` asks. Say which
verses printed in the heading.

A recurring welcome, accessibility note, pastoral contact, or worship-book
explanation found in a supplied source belongs in the standing
`church.yaml bulletin.parish_information` field (see
[worship onboarding](../../onboarding/references/worship-onboarding.md) and
[source import and inventory](source-inventory.md)), not in this week's
`announcements`, and not deferred to "the first bulletin" or a future
feature. It is a supported field now.

`service.display_name` is an optional service title such as "Holy Eucharist,
Rite II". It is not the Sunday occasion. Leave it absent unless a source or the
pastor supplies a distinct service title; `service.occasion` already prints
the calendar occasion on the cover.

A blank line in reading text prints as a gap. For a reading set as poetry, keep
the source's line breaks and add a blank line only where the source has a stanza
break. Never add one in mid-sentence. A single newline keeps the next line close.

For the psalm, preserve verified verse numbers, half-verse markers, and the
church's saved response format. The renderer has distinct responsive and
unison forms. Do not guess where to divide a verse.

Run worship resolution with the weekly overrides first. If it reports
`needs_input`, resolve the specific missing choice or source and repeat it.
When it reports `resolved`, copy its `liturgy` object into the weekly input.
Do not put the entire resolver response inside `liturgy`. The production tool
validates the resulting input; it does not turn an incomplete weekly object
into a complete worship service.

An Episcopal service variant may insert a verified private collect after the
Collect of the Day by using the `collect-of-day` anchor. The built-in collect
still renders from `collect_of_day`; inserted units use the normal verified
church source path. A later collect may also be inserted after the existing
`post-communion-prayer` anchor.

Keep weekly work in the private church folder so another task can resume it.
Use the private launcher to produce the review package. A rejected input should
lead to a focused correction of that input. It is never a reason to change the
renderer, remove a source check, or switch layouts.

Music image paths are resolved from the church folder root. For example, an
image staged under `bulletins/2026/09/2026-09-06/source-assets/page10-000.png`
must be entered as that church-root-relative path, even when the weekly JSON
lives inside the dated bulletin folder. Paths are copied into the review
package after the normal church-folder safety and source checks.

## Named services and reusable parts

Use `service.service_id` for a catalog service. Add `service.occurrence_id`
only when the same service happens more than once on that date; its default
is `main`. Run orientation for that exact service and occurrence so assignments
and unfinished packages come from the right history.

Select reusable text through `liturgy.part_selections`, mapping a supported
unit to its part ID, such as `{"communion_welcome": "short-welcome"}`. Put a
one-date selection in the weekly input. A recurring selection belongs in that
service's catalog settings. Keep part selections separate from direct source
files for the same unit in the same input. The resolver returns selected part
provenance separately from the resolved source files.

When the pastor pauses before all weekly material is available, save the
partial input inside the private church folder and record its path and next
unresolved decision in the existing progress notes. For a new catalog service,
use `bulletins/drafts/<date>/<service-id>/<occurrence-id>/input.json`; the agent
maintains this file. Recover it on return before asking questions. Do not call
an incomplete draft a produced or approved bulletin, and use the exact review
receipt for revisions once a review package exists.
