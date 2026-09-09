# AGENTS.md

This repository contains the public Handbuilt Church Labs plugin. Codex and
Claude use the same canonical workflows under `skills/`.

## Repository map

- `skills/` contains the canonical onboarding, bulletin, and sermon research workflows.
- `scaffold/church-folder/` is the template onboarding uses to create a
  church's private operating folder.
- `skills/bulletin/renderer/` contains private rendering details. Public
  callers use the skill-owned production interface rather than invoking those
  scripts directly.
- `handbook/` contains pastor-facing documentation.
- `tests/` contains synthetic regression tests. Generated test artifacts stay
  outside the repository.

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
4. **Verify before reporting completion.** For changes to this plugin, run
   `python3 tools/pii_check.py` and the repository test suite below. For church
   work, use the active skill's saved-file and output checks.

## Repository verification

The suite uses Python's built-in `unittest`. `pytest` is not a dependency and
does not need to be installed. Run the runtime doctor first and use the exact
`runtime.python` path it returns, quoted because it may contain spaces.
From the plugin root:

```bash
python3 tools/handbuilt_runtime.py doctor --format json
"<runtime.python>" -m unittest discover -s tests -p 'test_*.py'
python3 tools/pii_check.py
git diff --check
```

For a targeted onboarding check, use:

```bash
"<runtime.python>" -m unittest tests.test_onboarding_contract tests.test_church_setup -v
```

Replace `<runtime.python>` with the doctor's returned executable, not a second
guessed Python environment. Repository tests check plugin changes; ordinary
church onboarding uses `church_setup.py status` and verifies the saved church
files. Missing developer tools must not become a pastor-facing setup blocker.

## Working in a church folder

Church work belongs in the private church folder created by onboarding. The
installed plugin supplies workflows and reusable implementation. The church
folder owns configuration, licensed music, sermon work, bulletins, history,
and receipts.
