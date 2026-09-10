# Source import and inventory

Read this when a supplied bulletin PDF needs snapshot evidence, or before
treating an imported source as ready for production. Shared by onboarding
(which creates an import) and the bulletin workflow (which checks one).

## What it is

When onboarding accepts a pastor's uploaded bulletin, the agent snapshots it
privately, renders each page, extracts its text, and extracts any embedded
artwork with transparency preserved, including a masked or stencil logo. This
raw evidence does not interpret the bulletin; it only preserves what was
supplied so nothing gets lost or has to be re-uploaded. Deciding what each
page means is a separate, explicit step below.

## The short workflow

1. **Import.** `skills/onboarding/scripts/import_bulletin.py import
   --church-folder ... --source-pdf ...`. Returns an `import_id` and, per
   page, a rendered image, extracted text, and any extracted artwork.
2. **Inspect.** Read the page renders and text. Never infer a blank page from
   empty selectable text; a scanned or image-set music page commonly has
   none. Decide, page by page or section by section, what each part is and
   where it belongs.
3. **Record.** For each decided section, `map-section` with a `disposition`
   (`mapped`, `unresolved`, or `omitted`; omitted needs a reason), a `scope`
   (`standing` carries forward; `weekly` needs the service date and applies
   only to that dated bulletin), and where it maps to (`config_path`,
   `text_file`, and/or `asset_path`). Leave anything undecided as
   `unresolved` rather than guessing.
4. **Mark the review complete.** Once every page has been accounted for,
   `mark-review-complete` with a short note. This is the agent's own record
   that it went through every page, not a pastor approval and not a claim
   that every decision is settled: an unresolved or omitted section still
   needs the pastor's actual answer, and final bulletin approval stays the
   separate `bulletin finalize` step. Recording only one section -- a logo,
   say -- never counts by itself; this step is what makes an import usable
   for production. Editing a section afterward clears it and needs it
   recorded again.
5. **Check before building.** Before producing a bulletin that relies on an
   import, run `validate-for-production` with the effective weekly bulletin
   JSON. It blocks on a relevant unresolved section, a missing review
   attestation, an omitted section with no reason, a destination the
   renderer does not support, or a mapped file that changed or is not
   actually referenced by the bulletin. A mapped image, logo, or music asset
   still needs a human look (the result's `visual_review` list); this check
   only confirms the mapping is internally consistent, never how something
   looks.

## Example command sequence

Internal reference for the agent, not pastor-facing. Replace the bracketed
values; `<runtime.python>` is the executable the runtime doctor returned, and
`<plugin-root>` is the installed Labs plugin directory. Quote both paths.

```bash
# 1. Import: snapshot, render, extract text and artwork
<runtime.python> "<plugin-root>/skills/onboarding/scripts/import_bulletin.py" import \
  --church-folder "<church-folder>" \
  --source-pdf "<church-folder>/onboarding/uploads/2026-11-15-bulletin.pdf" \
  --original-filename "2026-11-15-bulletin.pdf"
# -> prints the manifest JSON; note its "import_id"

# 2. Record a mapped weekly text section (this dated bulletin only)
<runtime.python> "<plugin-root>/skills/onboarding/scripts/import_bulletin.py" map-section \
  --church-folder "<church-folder>" --import-id <import_id> \
  --section-id collect-of-day --page-start 2 \
  --disposition mapped --scope weekly --service-date 2026-11-15 \
  --text-file worship/liturgy/2026-11-15-collect.txt

# 3. Record a mapped weekly image section (an asset the import already extracted)
<runtime.python> "<plugin-root>/skills/onboarding/scripts/import_bulletin.py" map-section \
  --church-folder "<church-folder>" --import-id <import_id> \
  --section-id entrance-hymn-image --page-start 5 \
  --disposition mapped --scope weekly --service-date 2026-11-15 \
  --asset-path onboarding/imports/<import_id>/assets/page-0005-image-01.png

# 4. After every page has been accounted for (mapped, unresolved, or omitted)
<runtime.python> "<plugin-root>/skills/onboarding/scripts/import_bulletin.py" mark-review-complete \
  --church-folder "<church-folder>" --import-id <import_id> \
  --note "Reviewed all 8 pages; collect and entrance hymn image mapped, rest standing or not applicable."

# 5. Before producing the bulletin that relies on this import
<runtime.python> "<plugin-root>/skills/onboarding/scripts/import_bulletin.py" validate-for-production \
  --church-folder "<church-folder>" \
  --bulletin-file "<resolved-bulletin.json>"
# resolved-bulletin.json is the same weekly input built for `bulletin produce`
```

## What this does not claim

Recording sections and passing `validate-for-production` is source
accounting, not proof of visual fidelity or exhaustive coverage. A page count
is never evidence that everything was found. A missing or declined bulletin
upload must never block onboarding; the fallback interview always remains
available.

For the exported functions behind these CLI commands, see
`skills/onboarding/bulletin_import.py` and `skills/bulletin/source_inventory.py`.
