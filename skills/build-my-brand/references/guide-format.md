# The guide: how each section is written

`brand/guide.md` is created at the first recorded stage, the plan, and grows
one section per stage. It is the education artifact, the decision log, and
the volunteer handoff document at once. There is no separate guide-writing
step.

## Section shape

The interface wraps each stage in markers, adds the heading, and opens the
section with three lines it writes itself:

```
**Where you are:** step 7 of 16, Your direction, developed, in the phase "The idea".
**You decide today:** Which developed version of your direction to carry forward.
**Next you will see:** First refinement.
```

Write only the body. For a decision round the body is:

1. **The lesson**, two to five short paragraphs in church language. Define
   any unfamiliar term in the sentence that uses it.
2. **What was shown**, with images at relative paths under `brand/` or
   `brand/staging/` so the rendered PDF includes them. A table works well for
   comparing options side by side. From direction development on, include a
   curated sample of the exploration that was set aside, three or four
   ideas with one line each on why, so the pastor sees how many ideas were
   considered without sitting through them.
3. **What the pastor said when choosing**, in their words where possible.

The interface then appends, in a fixed block, whichever of these apply:

```
**Options considered:** a; b; c
**Shown on:** the bulletin cover; the church's own test announcement; the website's first screen; the sign at street distance; the social avatar at real size
**Recommended:** version B, because ...
**Decision:** the pick
**Why:** the rationale
```

The plan's section gets a table of its phases instead. The rendered guide
sets the opening lines and the decision lines apart so a reader skimming
can find where they are and every decision.

## Images and side-by-side proof

Reference images as `![caption](brand/discovery/website-home.png)`. For the
proof, a table with the old and new bulletin covers and the test
announcement reads well:

```
| Before | After | The announcement |
|---|---|---|
| ![Before](brand/discovery/bulletin-before.png) | ![After](brand/staging/proof/bulletin-after.png) | ![Announcement](brand/staging/proof/announcement.png) |
```

Keep page images under about 1600 pixels wide so the PDF stays small.

## Revising a section

`record --replace` rewrites one section in place and marks every later stage
stale. Revisit stale stages before approval; the interface refuses to approve
while any are stale. The pastor may also edit the guide by hand at any time;
the workflow replaces only the text between a stage's markers. A plan
recorded late, for a run that began before the plan stage existed, is
placed first in the guide.

## Rendering

`render-guide` produces `brand/guide.pdf` set in the church's own brand:
the cover carries the mark and wordmark on the primary color, chapters start
on new pages, and decisions are marked in the rubric color. Before approval
it renders from the staged system and says so on the cover. Check the cover
and the first decision page before handing the PDF over.
