# The plan: the first thing the pastor sees

Before any work, the pastor sees the whole engagement on one page: the
phases, what they will see at each, what they will decide, and roughly how
long each takes. A pastor is never surprised by the shape of the process,
and never has to ask whether a choice is final. The `roadmap` stage records
the plan, and every later section opens with "where you are, what you
decide today, what you will see next," written by the interface.

## Writing the plan

Write it for the pastor, in under a page. Four short parts:

1. **What this is.** Two sentences: the brand will be designed and the
   reasoning taught as each decision is made, so the church can keep its
   brand after the work ends.
2. **The phases.** One line each, plain, with what the pastor sees and
   decides. The table below is appended by the interface from the metadata;
   the prose can add what the table cannot, such as that the direction
   choice commits an idea and not a color.
3. **How decisions work.** Each round is a short lesson, two or three
   concrete things to compare, and one pick. The pastor is never asked to
   describe a feeling. Every decision is written down with its reason.
4. **What never happens without the pastor.** The live brand changes only at
   approval; the old one is kept; nothing is published or bought.

## Metadata

`phases` is a list, each with `title`, `stages` (the workflow stage keys the
phase covers), `you_see`, `you_decide`, and `time`. Every stage after the
plan must belong to exactly one phase. A natural grouping:

```json
{"phases": [
  {"title": "Getting to know you", "stages": ["fork", "discover", "interview", "identity"],
   "you_see": "How your church looks today, through a designer's eyes, and the brief in your words",
   "you_decide": "Keep your mark or start new; one identity for everything", "time": "One sitting"},
  {"title": "The idea", "stages": ["direction", "develop", "refine-1", "refine-2"],
   "you_see": "Two or three directions on your own bulletin, announcement, and website; then one direction developed and tightened twice",
   "you_decide": "The direction, then the version, then the mark you keep", "time": "Three short sessions"},
  {"title": "The system", "stages": ["color", "type", "voice", "build", "prove"],
   "you_see": "The palette, the type, your voice, then your latest bulletin in the new brand beside the old one",
   "you_decide": "Each in turn, then whether the new brand goes live", "time": "Two sessions"},
  {"title": "Keeping it", "stages": ["connect", "handoff"],
   "you_see": "Where the brand travels and a one-page card for anyone who helps", "you_decide": "Nothing", "time": "Half an hour"}
]}
```

Stage keys: `fork`, `discover`, `interview`, `identity`, `direction`,
`develop`, `refine-1`, `refine-2`, `color`, `type`, `voice`, `build`,
`prove`, `connect`, `handoff`.

## A run that began before the plan existed

A church that recorded its first stages under the earlier scheme owes the
plan. `orient` reports it in `owed_stages`, and the interface refuses the
next stage until the plan is recorded. Write the plan with the pastor's
actual position in it; the interface's opening line says "this plan arrives
with the work already under way" and names the step they are at. Recorded
late, the plan still reads first in the guide.
