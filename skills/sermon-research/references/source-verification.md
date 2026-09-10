# Source Verification

Source verification has two layers. Retrieval proves that a source was opened.
Claim review proves that the opened source supports the sentence that uses it.
Both layers are required.

## Reading selection modes

The workflow has one downstream path and two ways to establish the preaching
text. `selection_mode` is either `lectionary` or `pastor_selected`.

### Lectionary selection

Verify the date, occasion, year, track, appointed readings, and optional verses
against two independent published lectionary hosts. Two pages on one host are
one source family. Search results, snippets, model memory, and a calendar page
that was never opened do not qualify.

The `record --stage readings` metadata file is one JSON object with a
`selection` key (the normalized selection) and a `sources` key (the list of
source records). A bare selection object at the top level is rejected with
`missing_reading_selection`; the module does not infer the wrapper.

The complete, valid example below is self-consistent: every field in
`readings.md` matches `selection`, and each source's `observed_selection` is
the complete normalized selection, not a summary of it. Adapt the values;
keep the shape.

<!-- example:lectionary-readings-metadata -->
```json
{
  "selection": {
    "selection_mode": "lectionary",
    "service_date": "2026-09-20",
    "occasion": "Proper 20",
    "lectionary_system": "RCL",
    "year": "A",
    "track": "Track 2",
    "optional_verses_policy": "appointed",
    "optional_verses": "none",
    "translation": "NRSV Updated Edition",
    "readings": {
      "first": "Jeremiah 11:18-20",
      "psalm": "Psalm 54",
      "second": "James 3:13--4:3, 7-8a",
      "gospel": "Mark 9:30-37"
    }
  },
  "sources": [
    {
      "label": "Lectionary Calendar One",
      "url": "https://lectionary-one.example/2026-09-20",
      "host": "lectionary-one.example",
      "retrieved_at": "2026-08-26T12:00:00+00:00",
      "verified_on": "2026-08-26",
      "result": "verified",
      "supports": "date, occasion, year, track, Gospel, and optional verses",
      "observed_selection": {
        "selection_mode": "lectionary",
        "service_date": "2026-09-20",
        "occasion": "Proper 20",
        "lectionary_system": "RCL",
        "year": "A",
        "track": "Track 2",
        "optional_verses_policy": "appointed",
        "optional_verses": "none",
        "translation": "NRSV Updated Edition",
        "readings": {
          "first": "Jeremiah 11:18-20",
          "psalm": "Psalm 54",
          "second": "James 3:13--4:3, 7-8a",
          "gospel": "Mark 9:30-37"
        }
      }
    },
    {
      "label": "Lectionary Calendar Two",
      "url": "https://lectionary-two.example/2026-09-20",
      "host": "lectionary-two.example",
      "retrieved_at": "2026-08-26T12:01:00+00:00",
      "verified_on": "2026-08-26",
      "result": "verified",
      "supports": "date, occasion, year, track, Gospel, and optional verses",
      "observed_selection": {
        "selection_mode": "lectionary",
        "service_date": "2026-09-20",
        "occasion": "Proper 20",
        "lectionary_system": "RCL",
        "year": "A",
        "track": "Track 2",
        "optional_verses_policy": "appointed",
        "optional_verses": "none",
        "translation": "NRSV Updated Edition",
        "readings": {
          "first": "Jeremiah 11:18-20",
          "psalm": "Psalm 54",
          "second": "James 3:13--4:3, 7-8a",
          "gospel": "Mark 9:30-37"
        }
      }
    }
  ]
}
```

If the sources disagree, stop. Resolve the reason, choose the church's stated
authority, and record the discrepancy. Never average or silently choose.

`readings.md` must show every field the module checks: the common labels
(Service date, Occasion, Selection mode, Primary research text, Translation),
the lectionary-only labels (Lectionary, Year, Track, Optional verse approach,
Optional verses this week, and the four bullet-listed readings), and a
verification link for every source. Missing any of these produces
`invalid_readings` naming the exact missing fields.

<!-- example:lectionary-readings-content -->
```text
# Readings

**Service date:** September 20, 2026
**Occasion:** Proper 20
**Selection mode:** Lectionary
**Lectionary:** RCL
**Year:** A
**Track:** Track 2
**Optional verse approach:** Use appointed options
**Optional verses this week:** none
**Translation:** NRSV Updated Edition
**Primary research text:** Gospel, Mark 9:30-37

- First Reading: Jeremiah 11:18-20
- Psalm: Psalm 54
- Second Reading: James 3:13--4:3, 7-8a
- Gospel: Mark 9:30-37

Verified against [Lectionary Calendar One](https://lectionary-one.example/2026-09-20)
and [Lectionary Calendar Two](https://lectionary-two.example/2026-09-20).
```

The verification line must literally contain each source's `url`; a citation
without the linked URL fails `invalid_readings` ("do not cite the required
published verification page or pages"). The primary research line must match
`sermon.primary_text` in `church.yaml` and the corresponding citation above.
Record this pair with the `sermon-research record --stage readings` command
shown under [Start or resume](../SKILL.md#start-or-resume), pointing
`--content-file` and `--metadata-file` at these two files.

### Pastor-selected passage

Use this mode when `sermon.selection_mode` is `pastor_selected`. Ask the pastor to name
the passage for the service and show the exact citation back for confirmation.
The agent must not infer the passage from a theme, prior sermon, calendar, or
conversation. A scheduled run cannot create this selection.

The metadata file is one JSON object with `selection`, `selection_confirmation`,
and `sources` (one entry is enough; lectionary mode needs two).

<!-- example:pastor-selected-readings-metadata -->
```json
{
  "selection": {
    "selection_mode": "pastor_selected",
    "service_date": "2026-09-20",
    "occasion": "Sunday worship",
    "translation": "NRSV Updated Edition",
    "readings": {
      "selected": "Luke 4:16-21"
    }
  },
  "selection_confirmation": {
    "authorship": "pastor_supplied",
    "confirmed_at": "2026-08-26T11:55:00+00:00",
    "service_date": "2026-09-20",
    "selected_text": "Luke 4:16-21"
  },
  "sources": [
    {
      "label": "Published Bible or translation source",
      "url": "https://bible-text.example/luke/4",
      "host": "bible-text.example",
      "retrieved_at": "2026-08-26T12:00:00+00:00",
      "verified_on": "2026-08-26",
      "result": "verified",
      "supports": "selected passage citation and translation",
      "observed_text": "Luke 4:16-21",
      "observed_translation": "NRSV Updated Edition"
    }
  ]
}
```

Open one published text reference in the configured translation. The source
verifies the citation and configured translation; the pastor, not the source
or the agent, authorizes the passage for that service.

<!-- example:pastor-selected-readings-content -->
```text
# Readings

**Service date:** September 20, 2026
**Occasion:** Sunday worship
**Selection mode:** Pastor-selected passage
**Translation:** NRSV Updated Edition
**Primary research text:** Selected, Luke 4:16-21
**Selection confirmation:** Pastor confirmed this passage for this service.

- Selected Text: Luke 4:16-21

Verified against [Published Bible or translation source](https://bible-text.example/luke/4).
```

Record this pair with the same command shape and `--stage readings`.

### Track for a lectionary without one

`selection.track` is always required text for `selection_mode: lectionary`,
even when the configured lectionary has no track concept (for example, the
Book of Common Prayer lectionary). Record `"Not applicable"` in both the
metadata and the visible `**Track:**` line. It is not cross-checked against
`church.yaml` unless `lectionary.system` is RCL, so church.yaml is free to
leave `lectionary.track` blank for a non-RCL system; RCL still requires an
exact `Track 1` or `Track 2` match.

## Primary research text

The weekly brief gives one reading primary research attention. For a
lectionary service, it treats the other readings as context. The church profile
identifies the normal role: `first`, `psalm`, `second`, or `gospel`. A pastor
may override it for a manual run. For a pastor-selected service, the configured
role is `selected`, and the research target basis is `pastor_selection`. A scheduled run must use the configured role and may only
continue after the pastor-selected readings stage was recorded manually.

Bind that decision to the verified readings in research metadata:

```json
{
  "research_target": {
    "role": "gospel",
    "citation": "Matthew 16:21-28",
    "selection_basis": "church_profile"
  }
}
```

For a pastor-selected passage, use:

```json
{
  "research_target": {
    "role": "selected",
    "citation": "Luke 4:16-21",
    "selection_basis": "pastor_selection"
  }
}
```

The citation must exactly match the selected role in the current readings
receipt and the `Text` header in the research brief.

## Research ledger

Every materially used research source receives one ledger record:

```json
{
  "source_id": "stable-short-id",
  "title": "Source title",
  "author": "Author or responsible body",
  "publisher": "Publisher or host institution",
  "url_or_citation": "Followable URL or precise primary citation",
  "source_type": "primary, scholarly, commentary, reporting, or other",
  "retrieved_at": "2026-08-26T12:00:00+00:00",
  "access_result": "opened",
  "claim_support": "The claims or section this source supports",
  "currency_note": "Why its date is appropriate for the claim"
}
```

`access_result` is `opened` or `verified`. A source mentioned by another
writer remains indirect until the original is opened. Label an inaccessible
or paywalled source in the prose if its absence matters, but do not put it in
the materially used ledger.

### Complete research metadata example

The `record --stage research` metadata file combines `research_target` (see
above), the full source ledger (at least four entries), and, for a brief
under 2,500 words, a `scope_note`. This combined shape, not any one field
alone, is what is most often missed without reading the module directly.

<!-- example:research-metadata -->
```json
{
  "research_target": {
    "role": "gospel",
    "citation": "Mark 9:30-37",
    "selection_basis": "church_profile"
  },
  "sources": [
    {
      "source_id": "commentary-one",
      "title": "A Critical and Exegetical Commentary on Mark",
      "author": "Responsible Scholar",
      "publisher": "Established Academic Press",
      "url_or_citation": "https://commentary-one.example/mark-9",
      "source_type": "scholarly",
      "retrieved_at": "2026-08-26T12:00:00+00:00",
      "access_result": "verified",
      "claim_support": "Supports reading the child as a figure of status reversal",
      "currency_note": "A durable critical commentary; not time-sensitive"
    },
    {
      "source_id": "historical-context-one",
      "title": "Household and Status in First-Century Galilee",
      "author": "Responsible Historian",
      "publisher": "Established Academic Press",
      "url_or_citation": "https://historical-context-one.example/article",
      "source_type": "scholarly",
      "retrieved_at": "2026-08-26T12:05:00+00:00",
      "access_result": "verified",
      "claim_support": "Supports the social meaning of receiving a child in the household",
      "currency_note": "A durable historical study; not time-sensitive"
    },
    {
      "source_id": "primary-source-one",
      "title": "Mishnah, tractate on household status",
      "author": "Primary source",
      "publisher": "Established critical edition",
      "url_or_citation": "https://primary-source-one.example/text",
      "source_type": "primary",
      "retrieved_at": "2026-08-26T12:10:00+00:00",
      "access_result": "opened",
      "claim_support": "Supports the described household status hierarchy",
      "currency_note": "Ancient primary text; does not expire"
    },
    {
      "source_id": "reporting-one",
      "title": "Current reporting on service and status",
      "author": "Responsible Publisher",
      "publisher": "Responsible Publisher",
      "url_or_citation": "https://reporting-one.example/article",
      "source_type": "reporting",
      "retrieved_at": "2026-08-26T12:15:00+00:00",
      "access_result": "verified",
      "claim_support": "Supports the contemporary convergence example on humility and status",
      "currency_note": "Current as of the preaching date; refresh before reuse"
    }
  ],
  "scope_note": "A brief under 2,500 words needs this note explaining the narrowed scope."
}
```

`research_target.citation` must exactly match the verified readings' citation
for that role (`Mark 9:30-37` continues the lectionary example above). Every
`url_or_citation` that is a URL must also appear as a link in
`research-brief.md`'s References section. Record with the same command shape
and `--stage research`, using the `research-brief.md` shape from
[research-brief-template.md](research-brief-template.md), governed by
[methodology.md](methodology.md) including its final source cross-check.

## Source hierarchy

Use the strongest reachable source for the claim:

1. Biblical text and official or established lectionary calendar
2. Primary historical, patristic, legal, institutional, or data source
3. Peer-reviewed scholarship or a major critical reference
4. Reputable specialist commentary
5. Current reporting from a responsible publisher
6. General summaries for orientation only

A lower source can still be useful. It should not carry a claim that a stronger
available source could settle.

## Claim-support pass

Before recording research, inspect every paragraph that contains an external
fact, quotation, historical claim, language claim, current claim, or named
interpretation.

For each one:

- Open the cited source.
- Locate the exact support.
- Confirm the author, title, date, and publication context.
- Keep quoted language short and exact.
- Mark an inference as an inference.
- Cut or soften a claim whose support is weaker than its wording.
- Check that a citation did not drift away from its claim during revision.

The workflow module validates timestamps, URL or citation shape, claim-support
detail, currency notes, linkage between ledger URLs and the visible brief, and
receipt binding. The researching model owns the semantic claim-support read. A
passing schema does not prove a source says what the brief claims.

## Currency

Currency follows the kind of claim. An ancient primary text and a durable work
of scholarship do not expire on a news cycle. Reporting, policy, officeholders,
prices, program rules, and descriptions of current conditions can age quickly.
Use a source current enough for the preaching date and say when an older source
is intentionally historical.

## Failure behavior

- Broken link: find the canonical replacement or remove the claim.
- Only a snippet available: do not cite the snippet as read evidence.
- Source unavailable: name the gap if it matters.
- Conflicting authorities: stop and explain the conflict.
- Attractive quote with uncertain provenance: omit it.
- Current example with stale support: refresh it or remove it.
