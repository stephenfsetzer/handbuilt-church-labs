# Small operations after the workflow

Once the brand is approved, most requests are small. Read `brand.json`
(`brand_system`) and `brand/guide.md` first; they hold every rule. Do not
re-run the workflow for these.

## A lockup for a ministry, program, or event

Apply `lockup_rules` exactly. Set the name in the text face in the position
the rule states, using the primary mark. Export SVG and PNG into
`brand/marks/lockups/<slug>/`. Show it beside the parent lockup so the pastor
sees the family resemblance. Append a two-line guide entry under
"Keeping your brand" naming the lockup and the date.

## An announcement image for a program

The most common weekly request. Follow `brand_system.imagery` exactly:
compose from what `made_from` allows, in the `announcement` composition,
and never do anything in `forbidden`. Start from the announcement template
under `brand/templates/`. The program gets no logo; it gets this image, so
it feels like the church and unlike last week. Show it beside the test
announcement from the guide so the pastor sees the family resemblance.

## A poster, flyer, or sign

Start from the matching template under `brand/templates/`. Change only what
the template's first line says to change. Use the palette jobs: one accent
per page, body text in ink. Render through the bulletin renderer's engine
where a PDF is needed. Review the result at print size before handing it
over.

## Seasonal color

A season may add one color for a bounded time. Record it in the guide with
its start and end dates and its job. It never replaces the primary color and
never changes `brand.json`.

## An on-brand check of a volunteer's draft

Compare the draft with the guide's rules in order: name spelled exactly as
the wordmark, one identity (no invented logos), type families, palette jobs,
voice rules. Report what passes and what to change, in the volunteer's
language, with the fix stated rather than the principle. This check is
advisory; it does not block anything.

## What never changes without the workflow

The mark, the small variant, the wordmark, the type pairing, the primary color, and the imagery rules. A request
to change any of these is a refresh, which starts the workflow at the fork.
