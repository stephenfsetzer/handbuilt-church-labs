# BCP Sunday text sources

This directory contains public-domain English 1979 Book of Common Prayer
material needed across ordinary Sunday bulletin preparation: 70 contemporary
collect entries, 22 preface entries, and the 150 Psalms. It is not a complete
prayer book, calendar, lectionary, or music collection. Special services may
need additional verified material.

The official Episcopal Church PDF URL, edition, source PDF checksum, and
verification date are in `sunday.json`. Every entry identifies its source
pages. `manifest.json` records release checksums for the data and the prepared
fixed-text Markdown files under `../../renderer/liturgy/`. Runtime lookup
checks these against the released manifest before using bundled sources.
Checksums detect accidental changes; they do not replace source review.

To reproduce the data from the exact source PDF, run from the repository root:

```bash
python3 tools/import_bcp_sunday.py --pdf /path/to/book-of-common-prayer-2006.pdf --output-dir /tmp/bcp-review
```

The importer rejects a different PDF checksum. It needs Poppler's `pdftotext`
only during maintenance, not during a pastor's normal workflow. Compare the
new data with this release and inspect rendered source pages before accepting
an update. Do not refresh manifest hashes merely to bypass a failed check.

Line wrapping is folded to spaces. Collect and preface alternatives retain
separate identifiers; bracketed source choices must be resolved for the day.
Psalm verses preserve numbers and printed asterisk divisions. Eleven verses
have no printed asterisk, represented by `asterisk: null` and an empty second
half. Their words are preserved without an invented split.

Fixed files are prepared selections. Source comments document omitted optional
names, selected alternatives, and editorial speaker labels. Short Eucharistic
files are congregation leaflets with source response cues, not complete
celebrant texts. Full A and B require a selected proper preface; C and D do not.
The general blessing compatibility file is explicitly editorial, not a fixed
BCP formula. Local adaptations belong in private church folders.

See the repository's `THIRD-PARTY-NOTICES.md` for the publisher's public-domain
statement and the distinction from licensed modern Lutheran resources.
