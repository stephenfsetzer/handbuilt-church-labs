# Computer preparation and progress

The experience is called **Set up my church workspace**. The skill and existing
`onboarding` commands keep their names. Explain that this prepares a home for
church files, preferences, and skills, rather than welcoming new parishioners.

## Show the next useful step

Use four short progress labels: **Plugin installed**, **Computer prepared**,
**Church folder created**, **First useful result**. State what is happening
and what comes next. Do not turn them into four confirmation questions.
A working installation should move through the checks without new setup work.
Distinguish computer preparation for workspace/sermon work from pending PDF tools.

When returning, inspect actual installed components and the existing church's
`ONBOARDING.md`, when present, before repeating any work. Once the church folder
exists, record completed stages, pending PDF preparation, and one next action
there. Preserve custom instructions, skills, existing progress, and intentional
deletions; do not recreate a progress file the pastor deliberately removed.
Before the folder exists, use the current conversation and fresh computer
checks to resume; do not create a second church folder just to save setup state.

## Inspect together, then repair what is missing

Use the [runtime guide](../../../handbook/runtime-setup.md). Run the workspace
doctor and inspect its complete report: host OS/architecture, usable Python,
managed packages, all missing PDF tools, and the available native installer.
The host is where the agent executes commands; do not infer it solely from the
pastor's laptop or app name. Present one short preparation plan, including any
PDF work that can wait. Avoid exposing package lists as decisions for the pastor.
During first setup, when packages and PDF tools are present, also run `verify`
below before presenting that plan. This detects native rendering-library
failures early; record them as pending PDF preparation without blocking a
ready workspace. After repairs, repeat only the checks that establish readiness.

If Python cannot start the helper, use the host's available tools to inspect
the OS/architecture, installed Python interpreters, package manager, and the
four PDF tools together before offering recovery. On a Mac, do not assume
the presence of `python3` proves a usable interpreter: an OS stub or old
interpreter may fail. Prefer an already-installed supported interpreter and
pass its exact path with `--bootstrap-python`.

Use the existing managed environment and native installer. When Python or
Homebrew itself is absent on macOS, consult the official [Python macOS
downloads](https://www.python.org/downloads/macos/) or [Homebrew installation
guide](https://docs.brew.sh/Installation) for the actual host before guiding
installation. Do not invent download URLs, repeatedly trigger developer-tools
installation, or change the pastor's preferred app. Recheck after each repair
and continue from the first incomplete stage. If a repair fails, inspect the
new error rather than repeating the same installation without new evidence.

Let the agent perform supported actions. When sign-in, an installer window,
or an OS permission needs the person, explain why and give one concrete next
action naming the app/window and control. Ask for a password only through the
system's own prompt, never in chat. Do not say installation is complete merely
because a download finished. Verify it from the host afterward.

## Check only the tools needed now

Workspace readiness retains the existing managed Python/package checks. It
does not require Poppler, and covers church settings, brand settings, and
sermon research. It does not certify PDF import, rendering, or printing.

Before PDF import or bulletin work, run:

```bash
"<runtime.python>" "<plugin-root>/tools/handbuilt_runtime.py" verify --format json
```

This renders and checks a small temporary PDF, including native rendering
libraries, page images, text, metadata, and fonts. It installs nothing and
removes the temporary files. The church launcher runs this check for bulletin
work too. After a failed check, follow its component-specific repair detail;
a missing native library is not a reason to reinstall every Python package.

If PDF preparation cannot finish now, retain any supplied bulletin and record
its import as pending. Offer the existing fallback worship questions or sermon
work; do not silently skip a source the pastor wants to use or claim its import
was verified. Source verification and final bulletin approval remain required.
