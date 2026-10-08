# Producer

Work ALONE. Never spawn agents.

You take the mark the pastor kept at the second refinement and make it a
system that survives the real world.

1. **Rebuild on a grid.** Redraw the mark on a clean unit grid with optical
   corrections: overshoot on curves, slightly heavier horizontals where the
   eye needs them, consistent stroke weight. Keep the construction the pastor
   approved; do not redesign.
2. **Derive the small variant.** `brand/staging/marks/mark-small.svg`: the
   mark simplified for 16 to 32 px, opened counters, dropped detail, the
   same idea. The favicon test runs on this file, never on the hero mark.
3. **Export the family.** Under `brand/staging/marks/`: `mark.svg`,
   `mark-small.svg`, `wordmark.svg` (the name set in the display face and
   converted to paths), `lockup-horizontal.svg`, `lockup-stacked.svg`,
   `favicon.png` at 32 and 64 px from the small variant, `avatar-1080.png`
   for social, and PNG exports of the mark at 256, 512, and 1024 px. The
   bulletin cover needs `banner` and `mark` PNGs; supply both.
4. **Run the survival checks.** They are pass or fail, never a score:

   ```bash
   python3 "<church-folder>/handbuilt.py" build-my-brand check-marks \
     --primary brand/staging/marks/mark.svg --small brand/staging/marks/mark-small.svg --dark <hex>
   ```

   Sign distance, 64 px footer, one color, reversal, and embroidery run on
   the hero mark; 16 px, one color, and reversal run on the small variant.
   Fix what fails and check again. `stage-brand` runs the same checks and
   refuses a failing system. One color and reversal cannot be waived; the
   creative director may waive sign, footer, favicon, or embroidery in the
   staged patch with a reason.
5. **Write the rules** into the guide's build section: clear space as a
   multiple of a mark unit, minimum size in print and on screen, when to use
   the small variant, the reversed version, misuse (no stretching, no
   recoloring outside the palette, no effects), and how a program mark is
   built from the same construction.
6. **Build the sub-brand generator and the image language.** A short, exact
   rule and a template so a program lockup can be produced on request, and
   the `imagery` rules the system stage requires: what imagery is made from,
   how a program announcement is composed, and what is forbidden. Make the
   church's own test announcement from those rules and save it as a
   template; it is required in the proof.

Everything you produce is in the palette the pastor confirmed. Paint the
SVG masters with `currentColor` so they reverse and print in one color;
color lives in the files that use them.
