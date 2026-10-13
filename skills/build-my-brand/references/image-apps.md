# Drawing in the pastor's own image app

Most pastors have no image service key, and they should never need one.
When `keys status` shows nothing that can draw, the image app the pastor
already uses becomes the studio. The skill picks the app, writes prompts
for it, tells the pastor exactly where to paste them, and takes the images
back in through `import-images`. This is the normal path, not a fallback.

## Which app to send them to

Recommend one app and name the other as an alternative. Do not list more.

| App | Where | Use it for |
|---|---|---|
| ChatGPT (recommended) | https://chatgpt.com | Follows a long editorial brief closely and makes precise edits to an image you upload. Best for the mark. |
| Gemini | https://gemini.google.com | Keeps a reference image steady across edits. Give it shorter, concrete prompts. |

A free account in either app can make images, with a daily limit; a paid
plan makes more. If the pastor already pays for one of them, send them
there.

## Writing the prompts

- Write one prompt per concept, at most three a round. Each one is the
  maker's editorial brief from [Image briefs](image-briefs.md), rewritten in
  plain words: the use, what the mark must keep, what to avoid, the
  composition, and "one flat dark color on a plain white ground, no text".
  For Gemini, cut it to the three or four most concrete lines.
- End every prompt with: "Make three different versions."
- Put each prompt in its own copyable block, labelled with the concept's
  name, and save them all in
  `brand/staging/explorations/<round>/prompts.md`.

## What to tell the pastor

Say it in four short lines, no more:

1. Open the app (give the link) and start a new chat.
2. Paste the first prompt. Repeat in the same chat for the others.
3. Save every image worth a second look into the church folder's
   `brand/inbox/` folder (create it first and give its full path). An image
   pasted into this chat is not saved as a file, so the folder is the way
   back.
4. Come back and say "done".

## Edits

For a precise change to a chosen image, write a short edit prompt ("Keep
everything the same, but make the arch thicker and open the gap at the
top"). The pastor uploads the chosen image into the same app with that
prompt and saves the result into `brand/inbox/` the same way.

## Taking the images back

Register what arrived with `import-images`, naming the app as the tool:

```bash
python3 "<church-folder>/handbuilt.py" build-my-brand import-images \
  --round <name> --files brand/inbox/<file> ... \
  --prompt-file brand/staging/explorations/<round>/prompts.md --tool "ChatGPT"
```

Then judge the contact sheet and show the pastor two or three, as with any
round. Without Recraft, the senior designer redraws the chosen image as
construction SVG, using it as the reference, and runs the mark checks.
