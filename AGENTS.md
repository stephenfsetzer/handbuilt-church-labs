# AGENTS.md

This repository contains the public Handbuilt Church Labs plugin. Codex and
Claude use the same canonical workflows under `skills/`.

## Repository map

- `skills/` contains the canonical onboarding, bulletin, sermon research,
  sermon reflection, sermon video, finance onboarding, and finance report
  workflows.
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
   Never copy figures, names, or examples from a church folder, report, or
   export into this repository, even as an illustration. That includes any
   church whose books a session has seen, not only your own. Money figures in
   docs and tests are invented, and each one is listed in
   `tools/example-figures.txt`. Account numbers come from the synthetic
   Riverbend chart or are invented, and each one is listed in
   `tools/example-accounts.txt`. `tools/pii_check.py` fails on any figure or
   account number that is not listed. Images, PDFs, office files, spreadsheets and accounting exports are
   never committed. Commit messages, pull request titles and descriptions,
   and release notes are public too: describe a bug in general terms, never
   with a church's name or figures. CI checks all of it, including against a
   private denylist kept in the `HANDBUILT_PRIVATE_DENYLIST` repository
   secret.
2. **Use verified liturgical sources.** Never invent readings, a
   pastor-selected sermon passage, or liturgical text.
3. **Write for a smart generalist.** Use simple, direct language. Explain an
   unfamiliar term when it first appears. Use church language on user-facing
   surfaces.
4. **Verify before reporting completion.** For changes to this plugin, run
   `python3 tools/pii_check.py` and the repository test suite below. For church
   work, use the active skill's saved-file and output checks.

## Cloud tasks, privacy and authorship

These rules apply to every agent session, and they matter most for cloud
tasks, which see only this repository. A cloud task has no church folder and
no private data, and it never asks for either.

1. **Riverbend is the only church here.** Use the synthetic Riverbend fixture
   for every example, test, and fixture. Never write a real church's name, its
   people, money figures, vendor or account names, or QuickBooks IDs anywhere
   in this repository: code, docs, tests, commit messages, branch names, pull
   request titles and descriptions, review comments, or release notes. If a
   brief or issue contains real church data, leave it out of everything you
   write and say so in your summary.
2. **The privacy guard must pass.** `tools/pii_check.py` fails on any money
   figure not listed in `tools/example-figures.txt` and any account number not
   listed in `tools/example-accounts.txt`. Add a figure or account number to
   those lists only when you invented it. CI also checks against a private
   denylist you cannot see, so a green local check is not the last word.
3. **Stephen is the only author.** Commit under the repository owner's
   GitHub noreply identity. Do not add co-author trailers, session links, or
   "generated with" lines to commits or pull request descriptions.
4. **Stephen merges.** Open a pull request and leave it for review. Never push
   to `main` or merge.

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
