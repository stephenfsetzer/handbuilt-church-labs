# The studio: a design firm's engagement, as agents

After the pastor chooses a direction, the brand is developed the way a good
firm develops a premium engagement: the senior designer who made the
direction boards develops the whole system, a creative director curates
everything the pastor sees, and wide internal exploration happens behind
them, never in front of the pastor. This folder holds one file per role. The
host session is the creative director and may also be the senior designer.
It spawns a worker per role when it can and plays the roles in sequence
otherwise.

| Role | File | Tier | Holds |
|---|---|---|---|
| Creative director | [creative-director.md](creative-director.md) | judgment, with vision; the host session | The direction, every presentation, the kill decision on any internal round, the recommendation |
| Senior designer | [senior-designer.md](senior-designer.md) | judgment, with vision | Direction development and refinement: whole compositions in context, mark and system together |
| Researcher | [researcher.md](researcher.md) | judgment | A reference board of named real work, plus saved reference images in a private scratch path the makers can see |
| Makers | [maker.md](maker.md) | making, or an image tool | Wide internal exploration against the senior designer's brief, including non-literal constructions; never the source of a presentation on their own |
| Producer | [producer.md](producer.md) | making | Clean vectors on a grid, the mark family, the small variant, exports, the sub-brand generator, the survival checks |

Tiers are mapped to models per host in [routing.md](routing.md).

## The phases after direction

1. **Direction development** (`develop`). The senior designer develops the
   chosen direction as a whole system, with the mark designed inside it.
   The pastor sees two or three developed versions on the same real
   applications the direction boards used and more, with a recommendation.
2. **Refinement** (`refine-1`, `refine-2`). Two rounds. Each presents the
   tightened system in the same context and asks for reactions. The chosen
   mark's SVG is recorded with the second refinement.
3. **The system** (`color`, `type`, `voice`, `build`). Color and type are
   confirmed on the developed system. The producer builds the mark family,
   the derived small variant, exports, templates, and the image language, and
   runs the survival checks before the system is staged.
4. **Proof and approval.** Unchanged: real pieces beside the old ones.

## What the interface enforces

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand explore     --round <name> --files <svg|png> ... [--maker <name>] [--dark <hex>]
python3 "<church-folder>/handbuilt.py" build-my-brand redirect    --round <name> --reason "<why>" [--rebrief-file <md>]
python3 "<church-folder>/handbuilt.py" build-my-brand record      --stage develop|refine-1|refine-2 --content-file <md> --metadata-file <json>
python3 "<church-folder>/handbuilt.py" build-my-brand check-marks [--primary <svg> --small <svg>] [--dark <hex>]
```

- **Fidelity only rises.** Every `develop` and `refine` record lists the
  `applications` the pastor was shown and the `boards` they saw them on. The
  interface refuses a record that shows fewer applications than the previous
  presentation. The floor at `develop` is the direction's applications plus
  the sign and the social avatar; `orient` reports the current floor.
- **A recommendation at development.** `develop` records which version the
  firm recommends and why.
- **The mark is recorded at the end of refinement.** `refine-2` records the
  chosen mark as an editable SVG under `brand/staging/`.
- **Internal exploration is kept, not shown.** `explore` lays a round of
  sketches (SVG or PNG) out on a contact sheet under
  `brand/staging/explorations/<round>/` with a receipt. Nothing is scored.
  The guide shows a curated sample; the pastor never sees a raw round.
- **The creative director's redirect is a receipted operation.** `redirect`
  stops a round, records why, and can carry a new brief. The round stays as
  the record of what was considered; the run is not archived.
- **Survival checks are pass/fail scripts at the system stage.** Sign
  distance, 64 px footer, 16 px favicon on the derived small variant, one
  color, reversal (with white actually present), and embroidery minimums.
  `stage-brand` runs them and refuses a failing system. One color and
  reversal cannot be waived; the creative director may waive the others in
  the staged patch with a reason, which the receipt records.
- Every operation writes a receipt.

## Sizing the work

Direction development is the most expensive stage and the one that decides
the brand. Expect the senior designer to spend as long on three developed
boards as the direction round took on three directions, and to run one or
two internal exploration rounds first. Refinement rounds are shorter. The
survival checks take seconds.
