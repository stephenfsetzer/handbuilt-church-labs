# Worship onboarding

Read this reference after the private church folder exists. Use a recent
bulletin as the initial working template when one is available. Use the
standard guided interview as the fallback when it is not.

## Choose the evidence path

Ask whether the pastor can provide a recent bulletin in Word or PDF format.
Explain the division of labor:

> The website supplies public identity, leadership, contact, brand, and likely
> QR information. A recent bulletin can show the detailed order of worship so
> I do not need to ask you to name every liturgical setting.

If the pastor has no bulletin, cannot upload it, or the file is too incomplete
to establish the order, continue with the fallback questions. Do not pressure
the pastor to find a file and do not treat its absence as a failure.

## Bulletin path

Preserve the original Word or PDF file in the private church folder. Parse it
locally and keep the source artifact, extracted text, layout observations, and
standing-setting hypotheses separate. For a PDF, pair text extraction with a
rendered visual check. For a Word document, inspect text and rendered page
structure when layout matters.

For a PDF, follow the
[source import and inventory workflow](../../bulletin/references/source-inventory.md):
snapshot the file, inspect the extracted page renders and text (a page with no
selectable text is not necessarily blank), and record each decided section
before treating the import as usable for a future bulletin.

Build a private evidence ledger with the source file, page or section
location, extracted value, and confidence. This is internal workflow support.
Do not introduce it as a pastor-facing deliverable or ask the pastor to review
it unless they request the provenance. Look for:

- service name, date, time, and service-book page references;
- the overall order, including Word, Sacrament, music, and dismissal;
- congregational responses and directions to stand, sit, sing, or speak;
- creed, confession, prayers, Eucharistic Prayer, Lord's Prayer, fraction,
  communion welcome, blessing, and dismissal;
- readings, psalm, Gospel, sermon, collects, and seasonal material;
- hymn numbers, titles, composers, choir or music roles;
- Serving Today roles and leadership names;
- footer contact information, QR codes, and invitation copy; and
- cover, section headings, page flow, announcements, and recurring layout.

Treat the bulletin the pastor supplied as the working template until the
pastor changes it. Carry forward what is directly observable:

- the overall service order and recurring sections;
- printed liturgical choices and congregational responses;
- section presence, including Serving Today and leadership sections;
- role labels and role slots, while replacing the assigned names each week;
- page flow, headings, footer structure, and other repeatable layout; and
- reusable invitation and contact structure.

Before saving prayer print choices, inspect the actual prayer body on its
rendered pages. A heading, BCP page reference, opening dialogue, Sanctus,
memorial acclamation, and final Amen do not establish a full printed prayer.
Directions such as "The Celebrant continues the prayer" may replace omitted
paragraphs. Record `print_full_eucharistic_prayer: false` when the bulletin
prints only responses or excerpts; use true only when the prayer body is
printed, or the pastor explicitly requests full text. Compare with the
bundled prayer to distinguish a prayer identifier from its print treatment.
Record the supporting pages in the private evidence ledger.

Likewise, "read responsively" alone does not establish half verses, whole
verses, or who begins. Inspect bold responses on the page; if they do not
settle the pattern, ask the single remaining psalm question. Do not infer a
standing preference from a familiar Episcopal default.

Save the reusable choices that are clear in the source, including the service
book and prayer forms, the ordinary role slots, the lectionary and translation
when verified, the printed hymn practice, recurring sections and their broad
placement, and the Classic or Modern bulletin design. Preserve observations
about exact placement privately when the renderer cannot reproduce them. Do
not present a source observation as a promise of an exact imported layout.

Keep the date, readings, hymns, names, petitions, announcements, and other
Sunday-specific content as weekly replacements. Do not ask whether each
observed section or role slot should recur. Supplying the bulletin for
onboarding already selected it as the initial template.

Present a concise pastor-facing summary under three headings:

- **What I will carry forward:** the observed working structure and defaults.
- **What changes each week:** the date-specific content and assignments.
- **What I still need:** only a conflict, ambiguity, source or license location,
  or required value that the sources do not establish.

One bulletin is enough to establish a useful initial template. Offer a second
recent bulletin only as an optional refinement, never as a condition for
completion.

Do not infer a license or source ownership from appearance. Resolve a
lectionary track and preaching translation from published evidence or printed
source notes when possible. Ask only about the small number of remaining
decisions that affect safe reuse.

## Fallback worship interview

Use ordinary church language. Explain the term before asking for it. Ask about
the church's practice in familiar language.

### Overall order of worship

> The overall order of worship is sometimes called the rite. A Eucharistic
> Prayer is one prayer within that order. For example, a church might use Holy
> Eucharist, Rite II, with Eucharistic Prayer A. Which overall order of worship
> should I use as your normal starting point? You can say later or not sure.

Ask which service book or worship source the church uses and which overall
order it normally follows. Do not infer Rite II, a Eucharistic Prayer, or any
other choice from denomination alone.

### How worship text should appear

Use the supplied bulletin to propose these choices together. Explain: “These
settings let future bulletins keep your church's familiar presentation. We
will save them once, and you can change them in ordinary language later.”

- Show whether the psalm alternates half verses or whole verses, is read
  together, or is printed plainly. Keep verse numbers. For whole verses,
  confirm whether the people begin with the first or second printed verse.
  Save whole-verse `psalm_response_start: first` when the congregation begins,
  or `second` when the leader begins. For `responsive_half_verse`, the leader
  reads the first half and the congregation the second; `psalm_response_start`
  has no effect. Do not ask a separate starting-side question for half verses.
- Propose the traditional doxology, the church's own wording, or omission.
  Ask about a music image only if the sample or pastor indicates one is used.
- Propose continuous prayer paragraphs with one opening speaker label and
  concise rubrics. Explain that prayer words stay intact. Keep repeated
  labels or full source rubrics if that is the church's preference.

If the sample does not establish a psalm pattern, ask one focused question
about who reads which part. Do not silently select responsive half verses.
Reading paragraphs follow the verified biblical source; this is preparation
work for the agent, not a technical formatting question for the pastor.

### Eucharistic and prayer choices

Ask, in small stages, for the usual Eucharistic Prayer or Thanksgiving, Lord's
Prayer form, Prayers of the People form, and usual settings. These are standing
defaults, not permission to choose text for a particular Sunday. When the
source does not show them, also ask whether the usual service prints the creed,
the confession, and the full Eucharistic Prayer. Explain that these choices
control what the congregation sees in the next bulletin.

For standard text, first follow the bulletin skill's
[Sunday library](../../bulletin/references/sunday-library.md). An ordinary
Episcopal prayer choice resolves from the bundled book; do not ask the pastor
for its source URL or a copy. The agent retrieves any available permitted
source and prepares private licensed material when required.

For source copying and verification, follow the bulletin skill's
[worship text and source records](../../bulletin/references/worship-text.md)
reference. Keep the original source and formatted text in the private church
folder and inspect the sidecar before using the text.

If the church uses local or licensed text, ask where that text lives in the
private church folder. Never copy licensed text into this public repository.
When a selected prayer is available from a verified public official source,
inspect that source and save a private source copy with its provenance before
rerunning the resolver. Ask the pastor only when the source is unavailable,
conflicting, locally varied, or requires a licensed file. Use the
canonical general blessing unless the church has an approved local blessing or
explicitly wants to omit it. A communion welcome is optional and remains a
local override when the pastor supplies one.

### Sermon text selection

Ask whether sermons normally follow a lectionary or use a passage selected by
the pastor only when the supplied sources cannot establish the working pattern.

For a bulletin path, compare the service date and printed readings with two
independent published calendars for the church's stated tradition. Save the
current readings and their sources when the match is clear. Determine a track
only when that Sunday's readings distinguish the tracks. If the calendars
conflict, or the bulletin does not match the expected readings, explain the
specific discrepancy and ask one focused question.

Confirmation of the current sermon passage is not confirmation of a permanent
`pastor_selected` policy. Record the passage for that service, then determine
the standing selection mode from the verified pattern or leave it unresolved.
Inspect the bulletin for a translation or copyright note before asking which
Bible translation to use. A absent translation is an appropriate
single onboarding question because it affects sermon research.

For lectionary preaching, derive the lectionary, track, preaching translation,
and optional-verse practice from the bulletin and
published calendars when possible. Ask one short question about the church's
usual sermon reading when the source does not state it. Ask only for a
remaining value that blocks the first useful result. Explain that the Revised
Common Lectionary may use Track 1 or Track 2, and the primary sermon text may be the first reading,
psalm, second reading, or Gospel.

Save `sermon.selection_mode: lectionary` and the selected role for lectionary
preaching. For pastor-selected preaching, save
`sermon.selection_mode: pastor_selected` and
`sermon.primary_text: selected`; leave lectionary-only settings blank.

The weekly workflow waits for the pastor to confirm the passage. A bulletin's
printed readings can inform the current service but do not by themselves prove
the church's recurring sermon-selection policy.

### People and research preferences

Use the website and bulletin to establish the pastor's printed name and title
and the regular role slots, such as celebrant or musicians. Treat people named
only in a dated Serving Today section as weekly assignments. Ask only when a
name, title, or print order is ambiguous and blocks the requested output.

Maintain reusable clergy and staff as entries with a name and role. Resolve a
weekly role from that roster only when the role match is exact and one person
matches. A first-name shortcut is safe only when it identifies one person
after printed titles are removed. If two people match, ask which person is
serving that week. Never add a dated celebrant or preacher to the standing
roster merely because they appeared in one bulletin.

Use portable research defaults during onboarding. Research preferences are an
optional later refinement and must not become a first-run questionnaire.

## Optional bulletin setup after the first useful result

Do not continue into this section automatically. Introduce a choice only when
the pastor requests it or an actual bulletin proof makes the choice necessary.

### Leadership, Serving Today, and footer

If the supplied bulletin includes a leadership roster, carry forward its
structure, role labels, and ordering while treating the names as weekly or
maintained data. Otherwise, ask about a roster only when the pastor wants one.
Explain “governing body” as the church's leadership group and ask what the
church calls it only if that label is needed for the requested output.

Use one guided confirmation for the printed clergy and governing roster:
confirm whether it should appear, the exact printed section label, the exact
member label, and the inclusion and ordering of the supplied names. Then save
the confirmed structure through `church_setup.py`. A website roster is
evidence for a proposal only. It never turns on printed leadership by itself.

If the supplied bulletin includes a **Serving Today** section, carry forward
the section and its role slots without asking whether it should recur. Replace
the names and assignments for each service. Use the observed footer structure
and confirmed website contact values as the working footer.

Save these answers in `church.yaml`:

- `bulletin.template` (`classic` or `modern`)
- `leadership.print_in_bulletin`
- `leadership.clergy_and_staff`
- `leadership.governing_body.label`
- `leadership.governing_body.member_label`
- `leadership.governing_body.officers`
- `leadership.governing_body.members`
- `bulletin.include_serving_today`
- `bulletin.serving_roles`
- `bulletin.footer`

### Recurring service variants

Ask whether the church has recurring services that change the usual order. If
yes, confirm the exact name, base service, replaced or inserted parts, stable
locations, approved-text location, and source or license. Save only
church-owned order files under `worship/orders/` and reference them from the
worship profile.

### Bulletin page layout

Record a normal back-page description in plain language, such as announcements
above a leadership roster. Do not make the pastor resolve internal print-layout
language during core onboarding. Defer weekly questions about combining a
closing hymn with that page until an actual proof exists.

A supplied source's recurring welcome, accessibility note, pastoral contact,
or worship-book explanation is a supported standing field, not a gap to defer.
Save it as ordered `title`/`text` sections under
`bulletin.parish_information.before_service` and/or `.after_service` (see the
[bulletin skill's weekly input reference](../../bulletin/references/weekly-input.md)
and [source import and inventory](../../bulletin/references/source-inventory.md)
when the text came from an imported PDF). This is distinct from dated
`announcements`; do not carry recurring parish information there, defer it to
"the first bulletin," or treat it as a future feature request.

## Save and resolve

Use these existing settings when saving answers. Do not invent alternative
field names or status values.

| Confirmed answer | Setting |
| --- | --- |
| Service book and order | `worship_profile.tradition_pack` and `worship_profile.tradition` |
| Prayer forms and printed sections | `worship_profile.defaults`, with true or false for Episcopal print decisions |
| Verified local worship text | `worship_profile.sources`, using church-relative paths; leave shipped-source overrides blank |
| Standing worship preferences | `worship_profile.defaults.doxology`, `psalm_format`, `psalm_response_start`, `prayer_presentation`, `rubric_style`, `include_first_reading`, and `include_second_reading` |
| Gospel announcement wording | `worship_profile.defaults.gospel_acclamation`: `lord` (standard BCP, the default) or `savior`, when the sample's exact printed wording differs |

The reading flags default to true to preserve the usual two-lesson order. A
church may set either flag to false when its appointed service has only one
non-Gospel lesson. The weekly `liturgy` object may override either flag for a
single service; this does not change the standing profile. The psalm and Gospel
remain required, and both lesson flags cannot be false.
| Standing doxology music | `bulletin.doxology_music`, using the existing hymn block shape; a weekly null remains weekly |
| Standing parish information | `bulletin.parish_information.before_service` / `.after_service`, ordered `{title, text}` lists; an explicit weekly empty list suppresses a scope for that week only |
| Clergy names and regular roles | `leadership.clergy_and_staff`, each with `name` and `role` |
| Usual reading practice | `lectionary` and `sermon.selection_mode` / `sermon.primary_text` |
| Reusable layout | `bulletin.template`: `classic` or `modern` |

These are keys in the setup helper's standing patch. Its `worship_profile`
object updates the existing worship file; it does not change the file pointer.
Set `worship_profile.status` to `confirmed` after the pastor has supplied or
confirmed the worship choices. Use `needs_onboarding` while they remain
unknown. Readiness is calculated separately, including missing text sources.
For Lutheran services, save the six private source paths under `sources` as
`gathering`, `prayers`, `great-thanksgiving`, `lords-prayer`, `communion`, and
`sending`. The resolver reuses those paths each week. Ask about the print
decisions only when the chosen service order uses them.

Batch each meaningful stage into one coherent write to the private church
folder, update `ONBOARDING.md`, and verify the result. Report saved, pending,
and still unresolved outcomes without listing every internal file or creating
extra cleanup writes for intermediate prose.

Run the worship resolver after the worship profile is saved:

```bash
<runtime.python> <plugin-root>/skills/bulletin/scripts/worship_resolution.py \
  --church-folder <church-folder>
```

`needs_input` is an honest result. Ask only for the listed choices before
presenting worship-dependent work as ready.

For a lectionary church, look up the parish's next service date and reconcile
two independent published calendars. For an RCL church, begin with The
Lectionary Page and the Vanderbilt Revised Common Lectionary library. For a
non-lectionary church, ask for the pastor's passage, read the exact citation
back for confirmation, and open one published text reference in the configured
translation.

End by naming the next two requests: “build my bulletin” and “start my sermon
research.” Then stop. Do not immediately ask an optional onboarding question.
If a dependency or asset remains pending, say exactly what is ready now and
what will become available after verification.

The separate doxology setting applies to the Episcopal service plan. In the
Lutheran service plan, keep any doxology within the church's verified local
order or Great Thanksgiving text so it is not printed twice.

## Checking a saved choice against a retained bulletin

When a bulletin was imported (Episcopal Rite II only), `church_setup.py
status` returns a `source_choices` object: `status` (`not_applicable`,
`no_import`, `checked`, or `unavailable`), `observations` (what the retained
text actually shows for `eucharistic_prayer`, `closing_hymn_position`, and
`gospel_acclamation`, each `unknown`, `ambiguous`, or `high` confidence with
a page and short evidence string), and `contradictions` (only the fields
where a `high`-confidence observation disagrees with the saved standing
choice). A matching or `unknown`/`ambiguous` observation never blocks
anything; only a real, unacknowledged contradiction makes `bulletin_ready`
false.

When `contradictions` is non-empty, explain the mismatch in plain language
("the imported bulletin shows Prayer A on page 3, but the saved choice is
Prayer B"). Use the pastor's instructions already given: correct an agent's
saving mistake when the confirmed instruction was to follow that source,
or record an intentional change the pastor has already requested. Explain
what was saved. Ask once only when the intended choice remains unclear.

- If the pastor says the source was right, save the new value as an ordinary
  standing update through `church_setup.py update --scope standing`.
- If the pastor confirms the saved choice is intentional even though it
  differs from that one dated bulletin, record an explicit override through
  the same `update --scope standing` command, using the `source_sha256` from
  `source_choices.observations.<field>.source_sha256s` (do not guess or
  compute this hash yourself):

```json
{
  "worship_profile": {
    "source_overrides": {
      "eucharistic_prayer": {
        "source_sha256": "<one value from source_sha256s>",
        "value": "B",
        "reason": "The rector confirmed Prayer B is the intended standing choice."
      }
    }
  }
}
```

An override is tied to that exact source hash and that exact standing value.
It becomes stale when that source no longer supports the observation or the
standing value changes. Adding another agreeing sample does not erase an
already confirmed preference; conflicting samples are reported as ambiguous.

The automated check covers only a few clear textual clues. An `unknown`
result does not replace ordinary page review: use clear printed or visual
evidence, and ask when that evidence does not settle the choice. Distinguish
your own source review from an automated finding. Never invent a value to
fill an unknown observation.
