# Worship text and source records

Use this reference when a bulletin needs church supplied or locally formatted
worship text. The source record belongs beside the private formatted text:
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

When preparing reading input, use `reading.paragraphs` as a list of strings
whose boundaries come from the verified source. Omit displayed verse numbers
from ordinary prose. Preserve poetry with `reading.format: poetry`; do not
guess paragraph boundaries from one-verse-per-line source formatting or strip
numbers with a broad regular expression. Psalms keep their verse numbers.
The selected psalm format controls response bolding, so do not assume a
responsive layout. A weekly input may explicitly override the saved mode.
