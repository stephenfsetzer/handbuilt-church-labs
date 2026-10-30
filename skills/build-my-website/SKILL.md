---
name: build-my-website
description: Build a church's website from its approved brand kit, in stages that each end at a gate - site map, the pastor's words page by page, what each page says, page scores, design, the rest of the pages, motion, build, and upkeep. Use when a pastor asks to build, redesign or plan the church website, or asks how the website will be kept up. Runs after Build My Brand is approved and writes into the church's private folder.
---

# Build My Website

This workflow builds a finished church website from an approved brand kit.
It exists because a website designed section by section, from a brand that
was never tested on the web, turns into dozens of rounds: the palette grows,
the same section gets copied down the page, and the pastor ends up as the
art director. Here every decision is made once, in order, by the role that
owns it, and frozen when approved.

Work inside the church's private folder. Use this skill's interface for
every stage so the record, the receipts and the gates stay honest.

## Rules that never bend

1. **The brand kit comes first and is not redesigned here.** The workflow
   refuses to start without an approved brand with its web layer (the house
   style, five campaign looks, the photo ledger). If the brand needs to
   change, that is a change to Build My Brand, not to a page.
2. **Pages before words, words before design.** The site map is approved
   first. Then the pastor's words are gathered page by page. Then what each
   page says is approved on a gray-box page. Design can tighten wording to
   fit; it can't add a section, drop one, or change what it says.
3. **Every stage ends at a gate and is then frozen.** The gate is the
   pastor's approval, the critic's pass, or the automated checks. Changing
   a frozen stage takes a change request, which marks every later stage
   stale.
4. **Nobody judges their own work.** The art director plans; the designer
   designs; the [critic](../build-my-brand/references/studio/critic.md),
   a fresh worker that sees only screenshots, passes each piece before the
   pastor sees it.
5. **Never invent the church's words.** The writer drafts only from the
   harvest and the church's own published words. Anything missing is marked
   as a placeholder for the pastor, never filled in.

## Roles

The pastor meets the team by job title. The host session is the creative
director and opens and closes each stage. Spawn a worker per role when the
host can; every worker prompt begins "Work ALONE. Never spawn agents."

| Role | Owns |
|---|---|
| Producer | The site map, the slot calendar, the handoff |
| Writer | The question sheets, the harvest, every word on the site |
| [Art director](../build-my-brand/references/studio/art-director.md) | The page scores; holds the house style and campaign looks |
| Senior designer | Home and one inside page, the section patterns, the rest of the pages |
| Critic | A pass or a redirect on each score, page and pattern, from screenshots |
| Interaction designer | Two or three signature moments of motion |
| Engineer | The built site and its checks |

## 0. Orient

```bash
python3 "<church-folder>/handbuilt.py" start build-my-website
python3 "<church-folder>/handbuilt.py" build-my-website orient
```

`orient` returns whether the brand kit is ready, each stage's state, rounds
used against the budget, hours so far, critic redirects, change requests,
how many usable photos there are, and the next action. If the brand kit is
not ready, it says what Build My Brand still needs; go there first.

Every `record` carries `rounds` (rounds of the pastor's reactions this
stage took) and `hours` (`agent` and `pastor`, rough). Going over a round
budget is warned and recorded, not refused: the first churches are how the
budgets get set. A pastor gate also carries `approved_by`.

```bash
python3 "<church-folder>/handbuilt.py" build-my-website record --stage <stage> --metadata-file <meta.json>
```

## 1. The site map (producer, 1 + 1 rounds)

Read the brief, the discovery, and the current site. Write
`website/sitemap.md`: each page, its job, who it is for, and what it must
let a visitor do. Fewer pages is usually better. Record `sitemap` with
`pages` (`slug`, `title`, `job`, `audience`, `must_let_visitor`); a site map
always includes `home`.

## 2. Your words, page by page (writer, at the pastor's pace)

For each approved page, write one sheet of five to eight questions under
`website/harvest/<page>.md`, each tied to a section the page needs. For a
Visit page: "What do you wish every first-time visitor knew before they
walked in?" "What's the first thing someone will see inside the door?" The
pastor answers by writing or speaking, at length; keep the answers
verbatim. Mine the church's sermons, newsletters and bulletins too, citing
each quote's source. Record `harvest` with `sheets` (one per page: `status`
answered or skipped, `file`, and a `reason` when skipped) and `mined` (each
with `quote` and `source`).

## 3. What each page says (writer, 1 + 1 rounds)

Write `website/content.md`: each page's sections in order, each section's
one message, its real facts, and draft headlines and copy in the pastor's
words. Put service times, the address, staff and links in
`website/site-data.yaml`, once. Show a gray-box preview: gray boxes for
images, the real words in a plain font, sections in order, so the pastor
approves what the page says and how long it is without reacting to design.
Record `content` with `pages` (each page's sections, `id` and `message`),
`preview`, and `placeholders` (how many words the pastor still owes).

## 4. The page scores (art director, critic gate)

For each page, write its score in `website/design-plan.md`, one row per
approved section in order: its job, what leads (`photo`, `type`, `number`,
`art` or `form`), its ground, its scale, its layout, and for a photo, which
one from the ledger. The rules:

- Each section changes at least one of lead, ground, scale or layout from
  the one before it.
- Every page has at least two big shifts, where two or more change at once.
- A page opens on an A photo or on the house style's plan without photos.
  A C photo is never used. A photo of people needs consent.
- No photo appears on two pages.

Check while you work, then have the critic pass each page:

```bash
python3 "<church-folder>/handbuilt.py" build-my-website check-score --metadata-file <scores.json>
python3 "<church-folder>/handbuilt.py" build-my-website critique --stage scores --target <page> --verdict pass|redirect --notes "<why>" [--instead "<what to try>"]
```

Record `scores` with `scores`. The interface refuses a score that adds,
drops or reorders an approved section, and writes each photo's page into
the photo ledger.

## 5. Home and one inside page (senior designer, 1 + 1 rounds)

Design Home and one inside page at 1440 and 375 wide, from the scores, the
house style, and the photos assigned. Name each section pattern you make,
screenshot it at both widths, and say what it may hold, so later pages and
upkeep can follow it. The critic passes both pages before the pastor sees
them. Record `design` with `pages` (each with `screens` at both widths and
the `patterns` it uses) and `patterns` (`name`, `holds`, `screens`).

## 6. The rest of the site (senior designer, 1 round)

Build every remaining page from the approved patterns. A new pattern is
named, documented and passed by the critic on its own (`--target
pattern:<name>`). The critic passes each page; the pastor sees the whole
site once. Record `pages` with the same shape and `whole_site_shown: true`.

## 7. What moves (interaction designer, 1 round)

Write `website/motion.md`: two or three signature moments at most, each
with what it does for a visitor who has asked for reduced motion. Effects
earn their place here or not at all. Record `motion` with `moments`.

## 8. The built site (engineer, checks gate)

Build the site from `content.md` and `site-data.yaml`, never with facts
typed into a page. Run every check the brand kit's `web.checks` names at
both widths, on a private preview link (Cloudflare preview deployments).
Record `build` with `checks` (each check, `pass` at `1440` and `375`),
`site` (where the code lives), and `preview_url`.

## 9. Keeping it up (producer, 1 round)

Upkeep is agent-native: people give direction, the agent owns the look.
Write `website/maintain.md` and a one-page volunteer card: how to ask for a
change and what the agent will do. Set the slot calendar: when each of the
house style's slots (usually the home hero, the announcement band and one
featured page) changes. Name the one approver who sees a preview of every
change and says yes before anything goes live. Then make one real update by
asking the agent, and have the approver approve it. Record `handoff` with
`volunteer_card`, `approver`, `slot_calendar`, and `first_update`
(`request`, `approved_by`).

After handoff, the agent acts first: three weeks before a season it
proposes the season's hero from one of the five campaign looks; it flags an
event whose date has passed and a slot unchanged for eight weeks; and before
a season or event it asks for one or two specific photos with a shot list.
Every change runs the build's checks, plus the critic for anything in the
hero.

## Changing a frozen stage

```bash
python3 "<church-folder>/handbuilt.py" build-my-website change-request --stage <stage> --reason "<why>" --change "<what changes>"
python3 "<church-folder>/handbuilt.py" build-my-website record --stage <stage> --metadata-file <meta.json> --replace
```

Every later stage is marked stale and its critic passes are set aside. Bring
each stale stage up to date in order. Count change requests and their
causes in the retrospective.

## After each church

Write a short retrospective in the church's private folder: rounds against
budget, hours, critic redirects and why, change requests and what caused
them, which patterns were made and which repeated. Generalize any miss the
pastor overruled into the [misses log](../build-my-brand/references/taste/misses.md)
as a note, never with the church's name or words.

## Guarantees you keep

- Nothing goes live without the named approver's yes on a preview.
- Do not create accounts, buy a domain, or publish anywhere without the
  pastor's go-ahead.
- No photo is used without its consent recorded, and none appears on two
  pages.
- Nothing church-specific goes into this plugin.
