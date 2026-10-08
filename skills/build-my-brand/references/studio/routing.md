# Model routing for the studio

Roles are assigned to tiers, not to model names. Each host maps tiers to the
models it has. Judgment is never routed to a cheap model; bulk work is never
routed to an expensive one when a script can do it. The earlier routing of
makers to cheaper models drawing from prose is withdrawn as the source of
anything the pastor sees.

| Tier | Needs | Roles |
|---|---|---|
| `judgment` | The most capable model available, with vision | Creative director, senior designer, researcher, and every decision the pastor will see |
| `making` | A capable model that writes precise SVG and follows a brief exactly, or an image tool with the direction board and references in front of it | Makers, producer |
| `script` | No model. Deterministic tools in the workflow interface | Rendering, contact sheets, survival checks, validation, receipts |

## Claude Code

The host session is the creative director and, by default, the senior
designer, because the person who made the direction boards develops the
direction. Spawn workers with the Agent tool for the researcher, the makers
(one per territory, in parallel), and the producer. Set `model` per tier
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
memory between processes.

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
