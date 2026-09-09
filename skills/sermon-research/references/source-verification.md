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

Record one normalized selection in metadata:

```json
{
  "selection_mode": "lectionary",
  "service_date": "2026-09-20",
  "occasion": "Proper 20",
  "lectionary_system": "RCL",
  "year": "A",
  "track": "Track 2",
  "optional_verses_policy": "appointed",
  "optional_verses": "none",
  "translation": "the church preference",
  "readings": {
    "first": "citation",
    "psalm": "citation",
    "second": "citation",
    "gospel": "citation"
  }
}
```

Record each reading source with:

```json
{
  "label": "Published calendar name",
  "url": "https://example.invalid/date",
  "host": "example.invalid",
  "retrieved_at": "2026-08-26T12:00:00+00:00",
  "verified_on": "2026-08-26",
  "result": "verified",
  "supports": "date, occasion, year, track, Gospel, and optional verses",
  "observed_selection": {"same": "complete normalized selection object"}
}
```

If the sources disagree, stop. Resolve the reason, choose the church's stated
authority, and record the discrepancy. Never average or silently choose.

In `readings.md`, use pastor-facing labels for the stable policy and weekly
decision:

```text
Selection mode: Lectionary
Optional verse approach: Use appointed options
Optional verses this week: none
Primary research text: Gospel, Matthew 16:21-28
```

The primary line must match `sermon.primary_text` in `church.yaml` and the
corresponding citation in the normalized selection.

### Pastor-selected passage

Use this mode when `sermon.selection_mode` is `pastor_selected`. Ask the pastor to name
the passage for the service and show the exact citation back for confirmation.
The agent must not infer the passage from a theme, prior sermon, calendar, or
conversation. A scheduled run cannot create this selection.

Record the normalized selection:

```json
{
  "selection_mode": "pastor_selected",
  "service_date": "2026-09-20",
  "occasion": "Sunday worship",
  "translation": "the church preference",
  "readings": {
    "selected": "Luke 4:16-21"
  }
}
```

Record the human confirmation separately from the source evidence:

```json
{
  "selection_confirmation": {
    "authorship": "pastor_supplied",
    "confirmed_at": "2026-08-26T11:55:00+00:00",
    "service_date": "2026-09-20",
    "selected_text": "Luke 4:16-21"
  }
}
```

Open one published text reference in the configured translation and record:

```json
{
  "label": "Published Bible or translation source",
  "url": "https://example.invalid/luke/4",
  "host": "example.invalid",
  "retrieved_at": "2026-08-26T12:00:00+00:00",
  "verified_on": "2026-08-26",
  "result": "verified",
  "supports": "selected passage citation and translation",
  "observed_text": "Luke 4:16-21",
  "observed_translation": "the church preference"
}
```

The visible artifact must include:

```text
Selection mode: Pastor-selected passage
Primary research text: Selected, Luke 4:16-21
Selection confirmation: Pastor confirmed this passage for this service.
Selected Text: Luke 4:16-21
```

The source verifies the citation and configured translation. The pastor, not
the source or the agent, authorizes the passage for that service.

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
