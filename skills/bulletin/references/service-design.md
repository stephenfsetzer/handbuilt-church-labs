# Service design and scoped bulletin decisions

Read this reference when a pastor is returning to a saved service, adding a
recurring service, choosing or changing a reusable worship part, resuming
unfinished dated work, or asking why a bulletin's wording or layout should
change. It supplements the production contract. It does not replace source
verification, artifact review, or the pastor's approval.

The pastor may keep a customized church workspace or choose another tool.
Use this guidance to make supported Handbuilt work clearer, never to require
plugin approval or to limit a church's local practice.

## Recover the useful starting point

Before asking a question, inspect the actual capabilities and returned state
available to the current caller. Recover, when present:

- the selected service through `service.service_id`;
- the exact dated occurrence through `service.occurrence_id`;
- church defaults and the selected service's usual parts;
- reusable parts and their verified source records;
- saved part selections, variants, pending dated work, and the last usable
  review package; and
- the effective choices, their origins, unresolved decisions, and material
  changes returned by the shared resolver.

The profile catalog is the church-owned source for recurring services and
reusable parts: `profile.catalog.services`, `profile.catalog.parts`, and
`profile.catalog.part_selections`. Read the
[worship profile contract](../worship/README.md) when creating or changing
these records. Keep implementation fields out of the pastor's normal workflow.

Use the recovered state to begin with the selected service, its date, what is
already settled, and the next useful action. A returning pastor should not
repeat the setup interview. A new service needs a short explanation of what
will be reused and which meaningful difference still needs a decision.

## Keep scope visible

Every recommendation and write has one of these scopes:

| Scope | Meaning | Typical examples |
| --- | --- | --- |
| This occurrence | One date and, when needed, one occurrence of a service | This Sunday's welcome, reading, music, or instruction |
| Recurring service | The named service and its future occurrences | A family service's usual communion instruction |
| Church defaults | Shared practice inherited by services that do not override it | Common presentation or a shared worship preference |

Ask about scope only when the pastor's words leave it unclear. Interpret
phrases such as "this Sunday" as the occurrence, and "from now on for the
family service" as that recurring service. A clearly authorized scope does
not need a second confirmation. If a shared change would affect several
services, preview the affected services before saving and explain that impact
in ordinary church language.

After a write, read the saved state back. Report the actual scope, the saved
selection or text, and the affected services or occurrences returned by the
workflow. A successful helper call alone does not prove persistence. A dated
exception must remain dated, and a recurring service change must remain
available to its next occurrence. Approved bulletins and receipts retain the
content that was approved even if a shared part changes later.

## Apply a scoped change

Use the connected launcher with the church's managed runtime:

```bash
python3 "<church-folder>/handbuilt.py" onboarding update --scope service --service-id family --patch-file "<church-folder>/.service-patch.json" --preview
```

A service patch contains the service fields directly, for example:

```json
{"part_selections": {"communion_welcome": "family-welcome"}}
```

Create a new part or service through `--scope standing`, wrapping the patch
in `{"worship_profile": {"catalog": {...}}}`. New catalogs require
`schema_version: 1`, `services`, and `parts`; `default_service` is optional.
A part has `name`, `unit`, and a church-relative `file` whose source has been
verified. A new service has a `name` and only the confirmed differences from
church defaults. Catalog names are internal; use `display_name` only for a
requested printed title. Rename `name` without changing the stable ID.

The preview returns `affected_services`, `changed`, and `before_state`.
Explain a shared effect before saving. Apply the same authorized patch without
`--preview`, adding `--expected-state <before_state>`. If the state changed,
recover it and update the proposal instead of overwriting intervening work.
A successful save returns `verified: true` and current readiness. Inspect that
result and recover the selected service through `bulletin orient --date
<YYYY-MM-DD> --service-id <id>` before claiming the choice carries forward.

For one dated exception, set `liturgy.part_selections` in that occurrence's
input, or use its direct `liturgy.sources` or `liturgy.files`. Do not specify
both a selected part and a direct file for the same unit in one scope. Missing
selections inherit; `null` leaves a decision open; `omit` is allowed only for
optional units listed in the worship contract. When revising a review package,
use its exact receipt and keep its service and occurrence IDs.

Existing folders without a catalog continue using their saved profile and
legacy history. Adding a catalog is an intentional setup edit; preserve the
existing service and its choices when introducing another service. When the
pastor is naming their existing service, set `catalog.legacy_service` to that
service's ID so orientation can recover its earlier approved history. This
association leaves the old records and artifacts unchanged. Do not assign
legacy history to a new additional service or guess when its ownership is
ambiguous. Catalog service history is recorded
separately by service, date, and occurrence.

## Recommend the smallest useful change

Start with the closest saved order and reusable part. Reuse an existing match
before proposing a new alternative. Offer an alternative when the difference
is meaningful for worship, such as a different communion welcome, a distinct
instruction sequence, or a recurring service's order. Do not create a catalog
entry for a one-off typo, a date-specific name, or a local correction that has
no recurring purpose.

When a new service is added, carry forward shared church defaults and the
closest existing order. Ask only about differences that change participation,
content, or recurring layout. Keep a service label, public printed title, and
part purpose separate. A private catalog label does not print unless the
pastor supplied or approved it as the public title.

The pastor owns liturgical and theological choices. Identify a missing
instruction, conflict, or inconsistent wording and recommend a resolution,
but do not invent verified text, choose a different prayer to save space, or
remove service content. A pastor-authorized change to printed wording may be
saved and printed even when it differs from a supplied source. Record the
source and the authorization separately from the printed heading or label.

## Ask questions that protect participation

When review reveals a real issue, connect the recommendation to what people
must do in the room:

- Can people tell when to stand, sit, speak, or sing?
- Is the congregational response easy to find beside the leader's words?
- Does a page turn interrupt a prayer, response, hymn, or instruction?
- Can people read music at the printed size and identify the next action?
- Does the heading describe the words that are actually printed?

Use the rendered proof and extracted text to support the recommendation.
Explain a music-size or keep-together change with its observed page placement
and sheet-count effect. Successful PDF generation is not evidence of
readability. Automatic staff detection, facing-page flow, and a universal
readability threshold are future work until measured print evidence
supports them.

## Pause, resume, and recap

At a pause, save decisions that the pastor authorized, name their scope, and
record the exact next unresolved decision. On resume, recover that state and
carry it forward in a short recap:

> Saved for the family service: the new communion instruction. This Sunday's
> music is still open. Next, choose the music or tell me to leave it for later.

At completion, distinguish what future occurrences inherit from what was
specific to the date. Keep receipts and source paths available for inspection
without making the pastor review internal ledgers.
