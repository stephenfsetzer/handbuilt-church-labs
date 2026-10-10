# Image briefs

An image model draws the symbol. It draws what the brief says, so the brief
does the design thinking. Write one brief per concept, never one brief for a
whole round. A short prompt ("a church logo with a door") gets clip art; an
editorial brief gets a mark.

Save each brief as Markdown under `.handbuilt/build-my-brand/scratch/briefs/`
and pass it to `draw --brief-file`. The receipt records the brief's path and
hash, so the record shows exactly what the model was told.

## The template

```markdown
# Concept: <a short name for the idea>

Use case: <where the mark lives and what it must do there: the bulletin
cover, the street sign, a stitched banner, the social avatar>.

The mark must keep: <the one idea, in concrete shapes; the proportions or
gesture from the direction board; what the pastor said they liked, in their
words>.

Avoid: <the clichés for this subject; anything the pastor rejected;
gradients, shading, outlines around the whole mark, text, letters unless the
concept is a letterform>.

Composition: <centered or cropped by the frame; how much white ground;
nothing touching the edge unless the crop is the idea; one shape or a few>.

Color: one flat dark color on a plain white ground. No second color, no
tone, no texture.
```

## An example, with invented wording

```markdown
# Concept: the river as the threshold

Use case: the primary mark for an invented riverside parish. It sits on the
bulletin cover at about 30 mm, on a sign read from across the street, and
is stitched on a banner.

The mark must keep: one wide arch whose lower edge is a single river line
running out of the frame on both sides; the arch is open at the bottom, so
the river is the doorstep. The direction board's long, low proportions.

Avoid: a cross on top, a dove, a building outline, waves drawn as three
repeated curves, shading, a circle or badge around the mark, any text.

Composition: centered, about two thirds of the frame wide, generous white
ground above and below; only the river line touches the edges.

Color: deep navy, flat, on plain white.
```

## Edits

After the pastor reacts, change one chosen image with `edit`. The
instruction says what stays as plainly as what changes: "Keep the arch and
the river exactly. Make the river line about half again as heavy and end it
a little before the frame on the right."

## Before you send a brief

- It names one concept, not a menu.
- It says what to keep in shapes, not adjectives.
- It names the clichés to avoid for this subject.
- It asks for one flat dark color on white, so the result can be
  vectorized into a mark that prints in one color and reverses.
