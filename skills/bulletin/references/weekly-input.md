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
| `readings` | Enabled `first` and/or `second` lessons, plus `psalm` and `gospel`. Each supplied reading has full verified `text` and a `source` object containing `label`, `location`, and `verified_on`. Use `citation` for Bible readings and `number` for the psalm. The resolved `liturgy.include_first_reading` and `include_second_reading` flags control which lesson slots are required and printed. At least one non-Gospel lesson remains required. |
| `collect_of_day` | Verified text for the selected occasion. Prefer the bundled Sunday library. |
| `proper_preface` | The verified selected preface when required by the prayer. |
| `liturgy` | The `liturgy` object returned by worship resolution, including its service plan and profile reference. |
| `hymns`, `service_music` | The week's selections. Empty objects represent no selections; do not copy example hymns. Music blocks may include `composer`, which prints as a plain source credit. Service music supports `prelude`, `gloria`, `psalm_antiphon`, `offertory_anthem`, `sursum_corda`, `sanctus`, `fraction_anthem`, `doxology`, `communion_anthem`, and `postlude`. Lutheran plans support `prelude`, `psalm_antiphon`, `offertory_anthem`, `communion_anthem`, and `postlude`. Unsupported or unknown nonempty slots are rejected. |
| `announcements` | The week's announcements, or an empty list when none were supplied. |
| `options` | Supported weekly display choices from the schema. Do not invent a `presentation` wrapper. |

`service.display_name` is an optional service title such as "Holy Eucharist,
Rite II". It is not the Sunday occasion. Leave it absent unless a source or the
pastor supplies a distinct service title; `service.occasion` already prints
the calendar occasion on the cover.

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
