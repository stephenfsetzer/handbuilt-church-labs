# Bulletin Templates (v2)

**Status: stable.** The two template standards (classic and modern)
are locked upstream after production use at a working parish; weekly
configs and brand.json values are the editable surface.

Print-ready worship bulletins from a weekly config file, a church brand
file, and the liturgy texts in `liturgy/`. This component is the
shareable heart of the Handbuilt bulletin workflow: it contains no
church-specific data, so any parish can adopt it by supplying its own
brand file, music images, and weekly config.

## The two template standards

| Template | Look | Music | Length |
| --- | --- | --- | --- |
| `classic` | Traditional Anglican: EB Garamond, centered small-cap heads, red rubrics | Full music images | ~15 pages |
| `modern` | Brand-forward: Source Serif 4 and Source Sans 3, accent rules in the church's brand color | Full music images | ~15 pages |

A third standard (`compact`, a four-page order-of-service outline) was
cut on 2026-08-19; its theme is parked in `_archive/` and its builder
code remains in `render_bulletin.py` but is not exposed.

## Generate a bulletin

```bash
python3 render_bulletin.py --config <week>/bulletin-config.json --template classic
python3 impose_booklet.py <week>/bulletin-2026-09-06-classic.pdf
```

The first command writes a sequential US Letter PDF (plus the
intermediate HTML) next to the config. The second writes pre-imposed
2-up saddle-stitch sheets for 11x17 paper. Print the imposed file
double-sided, flip on the SHORT edge, fold the stack, staple on the
fold. If the copier has its own booklet mode, print the sequential PDF
instead and let the copier impose.

## What a church supplies

1. **Brand file** at `shared/brand/brand.json` (repo root): church name,
   address, website, service line and time, logo path, colors, and any
   standing texts (a custom blessing, the communion welcome). Without a
   brand file the renderer falls back to neutral defaults.
2. **Weekly config** `bulletin-config.json` in the week's folder: date,
   occasion, hymns, readings (full text), collect, proper preface,
   announcements, and the resolved `liturgy` choices. The older `options`
   fields are accepted only as a migration input. See
   `example-bulletin-config.json` for a complete example.
3. **Music images** in the week's `hymn-images/` folder: keep a
   `music/` folder of scans the parish is licensed to reproduce and
   copy what the week needs. Images carry DPI metadata; the
   renderer sizes them automatically and trims oversized white borders.
4. **Liturgy texts** in `liturgy/` (this folder): the public shipped
   sources available to the renderer. The church's worship profile selects
   which source is used. Local or copyrighted service-book text belongs in
   the private church folder and is not shipped here.

## Liturgy markdown conventions

- `# Title` names the section; `## Subtitle` marks a musical moment the
  renderer can replace with an image (the Sanctus).
- `Priest<tab>text` is spoken dialogue; `**People<tab>text**` is a bold
  congregational response. Continuation lines start with a tab.
- `*italic line*` is a rubric. `*Presider*` marks prose that follows.
- The congregation reads everything printed in bold. Call-and-response
  pairs are kept together across page breaks automatically.

## Copyright notes

- `general-blessing.md` uses 2 Corinthians 13:14 from the World English
  Bible, which is dedicated to the public domain.
- The 1979 BCP (liturgy and psalter) is public domain.
- Scripture text in the weekly config is NRSV; congregational bulletin
  use falls under the NRSV gratis use policy. Keep the readings in the
  weekly config, not in this shared component.
- Hymn and service music images are the church's responsibility: use
  only music the parish is licensed to reproduce (RiteSong, OneLicense,
  public domain).
