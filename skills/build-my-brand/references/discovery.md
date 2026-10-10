# Discovery: how you look today

Discovery is the first lesson, and it asks nothing. The pastor sees their own
church through a designer's eyes before deciding anything. Complete every safe
inspection before writing a word.

## What to inspect

| Source | Where | What to read |
|---|---|---|
| Current logo | `brand/` and `brand.json` `logo` | Legibility at small sizes, whether it survives one color, what it depicts, how old it feels |
| Website | `church.yaml` `website` | Home page above the fold, type, color, photography, the first three words a stranger reads |
| Public social page | the church's page URL if known | Profile image, cover image, cadence, whether church and personal posts mix |
| Recent bulletins | most recent folders under `bulletins/` | Cover, type, color, how the logo is used, what the footer says |
| Print and signage | anything the pastor drops into `brand/discovery/` | Exterior sign, flyers, letterhead, banners |

Take screenshots with the tools the host offers and save them under
`brand/discovery/` inside the church folder. Reference them from the guide
section as relative paths so the rendered PDF shows them.

Do not read `onboarding/imports/` or `music/` for public-facing evidence.

## How to write the section

Write for the pastor, not for another designer. Four short parts:

1. **What a stranger sees first.** One paragraph on the first impression from
   the website and the sign, in plain words.
2. **What is working.** Be honest and specific. Every church has something.
3. **What is accidental.** Where the image was never decided: mismatched
   type, colors that came from a template, a logo that fails small, a social
   page that mixes voices. Name the cause, not just the symptom.
4. **What this means for the rounds ahead.** Two or three sentences that
   preview the decisions the pastor will make and why the audit matters to
   them.

Avoid design jargon. If a term is needed, define it once in the sentence
that uses it.

## Recording

Metadata `sources` is a list of what was inspected, each with `label`,
`kind` (`logo`, `website`, `social`, `bulletin`, `print`, `signage`), and
`location` (a path or URL). At least one is required. Record the stage after
the section is written and its screenshots are in place.
