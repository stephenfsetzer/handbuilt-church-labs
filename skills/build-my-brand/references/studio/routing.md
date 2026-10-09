# Model routing for the studio

Roles are assigned to tiers, not to model names. Each host maps tiers to the
models it has. Judgment is never routed to a cheap model; bulk work is never
routed to an expensive one when a script can do it. Makers no longer draw
the symbol from prose: a language model cannot draw a church mark. The
symbol comes from an image model through the interface's image studio
(`draw`, `edit`, `vectorize`, `import-images`), and makers are logo
designers who write its briefs.

| Tier | Needs | Roles |
|---|---|---|
| `judgment` | The most capable model available, with vision | Creative director, senior designer, researcher, and every decision the pastor will see |
| `making` | A capable model that writes a precise editorial brief, judges images against the direction board, and writes clean construction SVG | Makers (logo designers who write image briefs and run draw, edit, and vectorize), producer |
| `image` | An image model, reached through the image studio or the host's own image tool | The symbol itself: every round of form-finding and every precise edit |
| `script` | No model. Deterministic tools in the workflow interface | Flattening onto white, vectorizing and folding to one path, rendering, contact sheets, survival checks, validation, receipts |

## Image services

`draw` defaults to OpenAI's image model (`gpt-image-1`, or the model named
in `HANDBUILT_OPENAI_IMAGE_MODEL`); `--provider gemini` uses Gemini's image
model (`HANDBUILT_GEMINI_IMAGE_MODEL`), and `--provider recraft` uses Recraft
(`HANDBUILT_RECRAFT_IMAGE_MODEL`). `edit` uses OpenAI, or Gemini with
`--provider gemini`. Use Gemini when it is the only drawing key on the
computer: it keeps a reference image steady across edits, and it follows a
long editorial brief less literally than OpenAI, so keep its briefs short
and concrete. `vectorize` uses Recraft. Keys come from `OPENAI_API_KEY`,
`GEMINI_API_KEY` and `RECRAFT_API_KEY`, or from the
key file in the Handbuilt support folder on this computer; `keys status`
shows which are set without printing them. A hosted Handbuilt image service
is planned and not yet available. A host with its own image tool makes
images there and registers them with `import-images`.

## Claude Code

The host session is the creative director and, by default, the senior
designer, because the person who made the direction boards develops the
direction. Spawn workers with the Agent tool for the researcher, the makers
(one per territory, in parallel, each writing briefs and running the
image studio), and the producer. Set `model` per tier
from the session's available models: `judgment` on the session's top model,
`making` on a capable model. Each worker prompt starts with "Work ALONE.
Never spawn agents." and names the role file to read, the church folder,
and the round.

## Codex

The host session is the creative director and senior designer. Run the
researcher, makers, and producer as bounded `codex exec` processes with the
role file's content as the prompt and the church folder as the working
directory. Choose the model and reasoning effort per tier: `judgment` on the
most capable model at high effort; `making` on the coding model at medium
effort. Makers can run in parallel; the interface's state is the shared
memory between processes. Codex's built-in image generator may make a
round's images from the maker's brief; register them with `import-images`
so they reach the same contact sheet and receipt.

## Either host, no workers available

Play the roles in sequence in fresh context: read only the role file, do the
role's work, record it through the interface, then move to the next role.
The interface, not the conversation, carries state between roles.

## Verifying model ids

Model names change. Before a run, confirm the host's current model list
(`/model` in Claude Code, the host's configuration for Codex) rather than
trusting a name written here. Record the models used by passing `--maker`
names that include the model, for example `maker-crop@opus`, and by naming
the model in the develop and refine guide sections.
