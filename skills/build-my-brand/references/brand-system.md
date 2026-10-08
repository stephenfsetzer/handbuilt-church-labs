# The brand system: what build stages and the schema it declares

## Staging layout

Everything is written under `brand/staging/` first. Approval moves it into
`brand/` and rewrites the paths. Nothing under the live `brand/` paths is
touched until then.

```
brand/staging/
  marks/            SVG masters and PNG exports: mark, small variant, wordmark, lockups, favicon, social avatar
  type/             open-licensed font files the templates and the guide reference
  voice.md          the voice rules
  templates/        bulletin theme, newsletter, social sizes, letterhead, sign concept, announcement
  explorations/     every board the pastor saw, and each internal exploration round under <round>/
  checks/           survival check renders and report.json, written by check-marks and stage-brand
  brand-system.json written by stage-brand; never hand-edited
```

Reference images the researcher saves for the makers live outside staging,
under `.handbuilt/build-my-brand/scratch/references/`, so they are never
moved into the live brand.

## The staged patch

`stage-brand --patch-file` takes one JSON object:

```json
{
  "brand_system": {
    "schema_version": 2,
    "name": {"wordmark": "St. Anne's Church", "short": "St. Anne's"},
    "direction": {"name": "Open Door", "story": "One paragraph a stranger could feel."},
    "marks": {
      "primary": "brand/staging/marks/mark.svg",
      "small": "brand/staging/marks/mark-small.svg",
      "wordmark": "brand/staging/marks/wordmark.svg",
      "lockup_horizontal": "brand/staging/marks/lockup-horizontal.svg",
      "lockup_stacked": "brand/staging/marks/lockup-stacked.svg",
      "favicon": "brand/staging/marks/favicon.png",
      "social_avatar": "brand/staging/marks/avatar-1080.png"
    },
    "lockup_rules": "How a ministry, program, or event name sits inside the identity.",
    "type": {
      "display": {"family": "Fraunces", "license": "SIL Open Font License 1.1",
                  "files": {"regular": "brand/staging/type/Fraunces-Regular.ttf", "bold": "brand/staging/type/Fraunces-Bold.ttf"}},
      "text":    {"family": "Source Sans 3", "license": "SIL Open Font License 1.1",
                  "files": {"regular": "brand/staging/type/SourceSans3-Regular.ttf", "bold": "brand/staging/type/SourceSans3-Bold.ttf", "italic": "brand/staging/type/SourceSans3-Italic.ttf"}}
    },
    "palette": {
      "primary": {"hex": "#2b4a6f", "job": "The sign, the mark, headlines"},
      "deep":    {"hex": "#1a2c44", "job": "Small text on paper, footers"},
      "warm":    {"hex": "#c8a15a", "job": "One accent per page, never body text"},
      "paper":   {"hex": "#fffdf8", "job": "Backgrounds"},
      "ink":     {"hex": "#1c1c1c", "job": "Body text"}
    },
    "imagery": {
      "made_from": "The mark's own parts (the arc, the bar, the ring) composed at large scale and cropped by the frame; no stock photography.",
      "announcement": "The program title in the display face, set large on one palette ground; one mark part cropped as the image; date and time in the text face at the foot; the church lockup small in one corner. Programs differ by composition and ground, never by a new logo.",
      "forbidden": ["a second logo or icon for a program", "photography of crowds", "gradients and drop shadows", "more than two palette colors on one piece", "clip art"],
      "photography": "Where a photograph is used: people doing the thing, daylight, one color cast from the palette."
    },
    "voice": "brand/staging/voice.md",
    "templates": {
      "bulletin_theme": "brand/staging/templates/bulletin-theme.css",
      "newsletter": "brand/staging/templates/newsletter.md",
      "social_square": "brand/staging/templates/social-square.html",
      "social_story": "brand/staging/templates/social-story.html",
      "letterhead": "brand/staging/templates/letterhead.html",
      "sign_concept": "brand/staging/templates/sign-concept.svg",
      "announcement": "brand/staging/templates/announcement.html"
    }
  },
  "colors": {"ink": "#1c1c1c", "accent": "#2b4a6f", "accent_deep": "#1a2c44", "paper": "#fffdf8", "rubric_red": "#8b3a3a"},
  "logo": {"banner": "brand/staging/marks/lockup-horizontal.png", "mark": "brand/staging/marks/mark.png"},
  "waivers": []
}
```

Rules the check enforces:

- `schema_version` is 2. Version 2 added `marks.small` and `imagery`.
- Every path is relative, inside `brand/staging/`, and exists.
- `marks.primary`, `marks.small` (the derived small-size variant), and
  `marks.wordmark` are required. `primary` and `small` are editable SVG
  painted with `currentColor`; other marks are SVG or PNG. Every mark passes
  the same safety check the bulletin logo does.
- **Survival checks run on `primary` and `small` and must pass.** Sign
  distance, 64 px footer, one color, reversal, and embroidery on the
  primary; 16 px, one color, and reversal on the small variant. The report
  and renders go under `brand/staging/checks/`. `waivers` may name `sign`,
  `footer`, `favicon`, or `embroidery` with a `reason`; one color and
  reversal cannot be waived. The reversal check uses `colors.accent_deep` as
  the dark ground.
- `type.display` and `type.text` are required, each with `family`, a named
  `license`, and at least a `regular` file. Font files are TTF, OTF, WOFF, or
  WOFF2.
- Every palette entry has a six-digit `hex` and a `job` in words.
- `imagery` is required: `made_from` (what imagery is made from),
  `announcement` (how a program announcement is composed), and `forbidden`
  (a list). Other text fields such as `photography` are kept. These are the
  rules an agent follows when the pastor says "I need an image for an
  announcement."
- `voice` and every template path exist. Include an `announcement` template
  built from the imagery rules; the church's own test announcement is part
  of the proof.
- `colors`, if supplied, gives all five renderer colors. `logo`, if supplied,
  points at staged marks the bulletin cover can use. Supply both so the
  bulletin renders in the new brand on approval.

The `brand_system` object is additive. It lives beside the fields onboarding
and the bulletin already use in `brand.json`, and the renderer ignores it.
`church.yaml` remains the authority for identity; do not copy church fields
into the brand system.

## What the survival checks measure

Pass or fail, with the measurement in the report. They never drive design;
they catch a mark that would fail in the world.

| Check | On | Passes when |
|---|---|---|
| `sign` | primary | Shrunk to what a sign looks like from across the street (24 px), the ink stays within 60 to 150 percent of the 512 px render |
| `footer` | primary | At 64 px the ink stays within 60 to 150 percent of the 512 px render: nothing drops out, nothing fills in |
| `favicon` | small | At 16 px the ink stays within 50 to 160 percent of the small variant's 512 px render |
| `one_color` | both | The SVG paints with `currentColor`, `none`, black, or white only, with no gradient, pattern, filter, or mask, and the render has no tone between black and white beyond edges |
| `reversal` | both | Rendered white on the dark color, white is present and nothing is darker than the ground |
| `embroidery` | primary | At 25 mm tall, eroding by half a millimetre keeps at least 20 percent of the ink (no stroke thinner than 1 mm) and at least 20 percent of the paper inside the mark (no gap narrower than 1 mm) |

## What build produces

Build writes the assets the weekly loop needs, in the church's brand:

| Template | Purpose |
|---|---|
| Bulletin theme | A CSS theme or overrides the bulletin renderer can use so this Sunday's bulletin is the proof |
| Newsletter | A Markdown or HTML frame with the lockup, type, and a standard section order |
| Social square and story | Sized frames with safe areas, the avatar, and the lockup placed |
| Letterhead | Print-ready page with the lockup and footer |
| Sign concept | A vector concept for the exterior sign, sized to be measured later |
| Announcement | The program image frame built from the imagery rules, with the test announcement as its worked example |

Templates are for one person with little time, or an agent. Every template
says at the top, in one line, what to change and what to leave alone.

## Approval

Approval archives the live `brand.json` and any existing `brand/marks`,
`brand/type`, `brand/templates`, and `brand/voice.md` under
`brand/archive/<timestamp>/`, re-runs the survival checks, moves the staged
tree into `brand/`, rewrites every path, writes `brand_system` (with
`approved_on`, `approved_by`, and the survival report) into `brand.json`,
and applies `colors` and `logo` through the same validated writer
onboarding uses. The bulletin skill reads the result without further steps.
The approval receipt names every file archived and installed.
