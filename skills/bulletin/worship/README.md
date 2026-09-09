# Worship profile contract

The church folder owns one worship profile at `worship/profile.yaml`. It is
the editable source for standing worship practice. `church.yaml` contains only
the pointer to that file, so the same fact is not maintained in two places.

The bulletin skill reads the profile and resolves it with the week's choices
into the `liturgy` object in `ResolvedBulletin`. The production module receives
that object and does not infer a prayer, setting, blessing, or local communion
welcome from denomination, history, or a renderer default.

For church-owned text, the resolved weekly `liturgy.sources` map associates a
logical choice with a relative file under the church folder. Production stages
that file over the shipped sources for the render and removes the staged copy
before promoting the review package.

Tradition packs in the sibling `traditions/` directory define the vocabulary,
source expectations, and service plan for a tradition. The catalog registers
which packs are supported. They do not redistribute copyrighted service-book
text. Episcopal BCP Rite II includes the public shipped sources available to
the renderer. ELCA and LCMS Lutheran profiles identify their service books and
use a Lutheran Holy Communion service plan that requires the church to supply
licensed local text or source files.

The profile has five kinds of information:

- `tradition`: family, denomination, service book, and rite
- `defaults`: standing choices that can be carried into a week
- `sources`: shipped identifiers or church-owned licensed text references
- `provenance`: when the pastor last reviewed the profile
- `status`: whether onboarding still has unresolved choices

The resolved worship input uses the shipped `general-blessing` when the profile
does not specify another choice. A church may supply a private blessing
identifier and source file, or explicitly choose `blessing: omit`. The default
is not selected from a denomination or tradition pack.

The profile is intentionally not a Markdown posture document. The workflow
can show a plain-language summary in conversation while keeping one canonical
machine-readable record.

## Service variants

`service_variants` is an optional mapping keyed by a church-chosen variant id.
Each entry supplies an exact `name`, a `base_service_plan`, a church-relative
`order_file`, and a `confirmation_policy`. The order file lives in the private
church folder, normally under `worship/orders/`, and may use `extends`,
`replace`, `insert`, and `files`.

`files` maps logical liturgy units to existing church-relative source files.
Resolution validates those files, follows `extends` with cycle detection, and
merges the base before the child. The resulting service variant is placed at
`liturgy.service_variant`, while its source map is merged into
`liturgy.files` for the production staging interface. Weekly input must supply
`service.variant`; it is never inferred from a denomination, date, or history.
