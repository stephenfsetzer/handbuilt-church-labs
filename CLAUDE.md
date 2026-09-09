# CLAUDE.md

This is Handbuilt Church Labs: the public machinery for church
operations workflows. Sessions here behave by these rules.

## What this repository is

- `skills/` holds the three workflows (`onboarding`, `bulletin`,
  `sermon-research`). Each SKILL.md is the operating procedure;
  follow it exactly.
- `skills/bulletin/renderer/` holds private bulletin rendering details,
  templates, and liturgy texts. Public callers use the bulletin skill's
  production interface.
- `skills/sermon-research/references/` holds sermon research standards.
- `scaffold/church-folder/` is the template `/onboarding` copies to
  create a church's private folder.
- `handbook/` is plain-language documentation for pastors.

## Architecture principles

1. **Design for a pastor.** Use church language in commands, folders, statuses,
   and errors. A pastor should be able to see where work lives and what happens
   next without learning the internal architecture.
2. **Keep the public product separate from church work.** This repository owns
   reusable workflows and their implementation. Each private church folder
   owns church identity, configuration, licensed material, working files,
   approved history, and receipts.
3. **Build deep workflow modules.** Each skill owns a coherent capability
   behind a small, stable interface. Keep its implementation and supporting
   knowledge close. Add a seam when two real implementations require it. Avoid
   vague layers such as `engine`, `core`, or `utils`.
4. **Maintain one canonical workflow.** Claude and Codex use the same skills
   and production code. Host-specific adapters stay thin and contain no
   workflow decisions.
5. **Make guarantees explicit and enforceable.** Workflow code enforces source
   checks and human gates. Tests prove them. Files and receipts record durable
   state without requiring pastors to manage implementation details.

## Hard rules

1. **Keep the repository publishable.** Every committed file must be safe to
   make public. Church data, personal information, test results, and generated
   rehearsals belong elsewhere. Product specifications belong in the private
   Handbuilt product repository. Tests use synthetic fixtures.
2. **Use verified liturgical sources.** Never invent readings, a
   pastor-selected sermon passage, or liturgical text.
3. **Write for a smart generalist.** Use simple, direct language. Explain an
   unfamiliar term when it first appears. Use church language on user-facing
   surfaces.
4. **Verify before reporting completion.** For plugin changes, follow
   [repository verification](AGENTS.md#repository-verification). The suite uses
   built-in `unittest`, not `pytest`. For church work, use the active skill's
   saved-file and output checks instead of running developer tests after each
   onboarding stage.

## Working on a church (not on the Labs)

If a session starts here but the user wants their own church work,
find their church folder (onboarding records its location) and work
there. This repository is only edited to improve the machinery.
