# Worship text and source records

Use this reference when a bulletin needs church supplied or locally formatted
worship text. When that text originated as a page in a bulletin imported
during onboarding, also record the mapping in
[source import and inventory](source-inventory.md) alongside this text's
source record; the two are complementary, not a replacement for each other. The source record belongs beside the private formatted text:
`worship/liturgy/example.txt.source.json`. A source record binds the source
snapshot and the formatted text by hash. It records an agent or pastor's
verification assertion. It does not prove that a public page or private copy
is authentic by itself.

After checking the source against the formatted text, record it with the
managed runtime:

```bash
<runtime.python> <skill-dir>/scripts/liturgy_source.py record \
  --church-folder PATH \
  --file worship/liturgy/example.txt \
  --source-file worship/sources/original.txt \
  --label LABEL \
  --location URL-or-private-origin \
  --verified-on YYYY-MM-DD \
  --method public_source
```

Use `--method church_supplied` for a private church source. A public source
must retain a distinct source snapshot and an `http` or `https` location. To
inspect a record, use `inspect` with the church folder and text file:

```bash
<runtime.python> <skill-dir>/scripts/liturgy_source.py inspect \
  --church-folder PATH --file worship/liturgy/example.txt
```

An older text without a verified sidecar blocks worship dependent production.
Any later edit to the formatted text or source snapshot requires a new
verification record. Never reconstruct a missing prayer from memory.

## Format and check imported prayers

Use the bundled liturgy files as format examples: a `#` heading, italic
rubrics, and a literal tab between a speaker and the words. For a congregation
response, bold the complete speaker-and-text line. Blank lines separate
paragraphs. Source notes belong in HTML comments and do not print.

Compare the formatted text with every paragraph of the relevant source pages
before recording verification. Preserve general petitions, responses, and
local wording even when adjacent paragraphs contain weekly names. A petition
for the poor or refugees is not date-specific merely because it follows a
named petition. Keep changing names and dates as weekly inputs, but do not
replace whole prayer paragraphs with invisible comments. Comments are notes,
not working placeholders or an automatic substitution mechanism.

For a dated service, prepare any changed local prayer as a separate private
weekly text, verify it, and pass its path through worship resolution's weekly
source override. Do not overwrite the standing source to prepare one week.
Compare the rendered prayer with that week's supplied or confirmed wording.

When preparing reading input, use `reading.paragraphs` as a list of strings
whose boundaries come from the verified source. Omit displayed verse numbers
from ordinary prose. Preserve poetry with `reading.format: poetry`; do not
guess paragraph boundaries from one-verse-per-line source formatting or strip
numbers with a broad regular expression. Psalms keep their verse numbers.
The selected psalm format controls response bolding, so do not assume a
responsive layout. A weekly input may explicitly override the saved mode.
