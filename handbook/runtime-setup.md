# Computer preparation and runtime checks

The pastor should never have to manage Python packages or type setup commands.
The host agent owns this check and presents only the plain-language message from
the result.

## Host workflow

For **Set up my Church Command Center**, check from the installed plugin directory:

```bash
python3 tools/handbuilt_runtime.py doctor --capability workspace --format json
```

`doctor` is read-only. It does not create folders, install packages, or change
the pastor's church folder.

Both capabilities inspect all dependencies together, including the OS and
architecture, Python, managed packages, PDF tools, and native installer.
`workspace` requires the existing managed Python/packages but allows missing
native PDF tools. The default `bulletin` capability also requires those tools.
Inspect the complete report before presenting one preparation plan. A ready
workspace does not mean PDF work is ready. Existing working installations
should continue without reinstalling anything or asking extra questions.

Use a supported final Python release that meets the reviewed security floor
in `tools/runtime_security.py`. This release supports Python 3.11 through 3.14,
with patch floors 3.11.18, 3.12.16, 3.13.18 and 3.14.10. The known Python 3.15
security floor remains policy data, but runtime setup refuses that branch until
PyYAML has a compatible binary wheel. Python 3.10 and unreviewed branches are
rejected. Review both security floors and wheel coverage when changing support.
The check inspects the managed interpreter itself. Updating another Python on
the computer does not update an existing private environment.

If preparation needs a different host interpreter, inspect an installed,
patched interpreter and pass its exact path with `--bootstrap-python`.
The plugin does not download Python or replace the computer's Python.

If the result is `python-package-missing`, prepare the isolated runtime with
one host operation:

```bash
python3 tools/handbuilt_runtime.py setup --format json
```

`setup` creates a new private runtime generation with `venv --without-pip`.
It uses the inspected patched interpreter to download the published pip wheel
from its approved HTTPS host and checks the pinned SHA-256 before executing
that wheel. The first pip install is offline and has no dependencies. Package
installation then uses patched pip, the explicit PyPI index and `requirements.lock`,
which records the SHA-256 hashes of the reviewed wheels for every exact dependency.
The installer uses `--require-hashes --only-binary=:all:` and verifies a private
snapshot of the lock before using it. A missing compatible wheel stops setup;
there is no fallback to source compilation or an unpinned build environment.
Inherited pip configuration and package-cache writes are disabled.
No command installs into global site-packages or the church's private folder.

The existing runtime remains untouched while the replacement is prepared.
Setup checks package versions and, when native PDF tools are available, renders
and inspects a synthetic sample. It then atomically selects the verified
generation in `active-runtime.json`. Generation paths never move after venv
creation, so executable paths remain valid. Concurrent setup is refused.

If installation or verification fails, setup preserves the previous selection.
If restoring that selection cannot be verified, it keeps both generations and
reports `migration.recovery_required`; preserve them for maintainer recovery.
Never delete a generation named by the active pointer. A malformed or escaping
pointer stops preparation without falling back to another environment.

To select a retained previous generation, use the host operation:

```bash
python3 tools/handbuilt_runtime.py rollback --format json
```

Rollback verifies the previous environment against the current security policy
and requirements. It refuses a downgrade to an affected or incomplete runtime.
The `migration` receipt identifies the selected and retained environments.
The plugin does not remove retained generations as part of setup or rollback.

## Clean up obsolete runtime generations

The host can preview obsolete owned environments with:

```bash
python3 tools/handbuilt_runtime.py prune --format json
```

Review `prune.candidates`, then pause all Handbuilt workflows before applying:

```bash
python3 tools/handbuilt_runtime.py prune --apply --workflows-stopped --format json
```

The host must establish that workflows have stopped. Older processes can still
hold a generation path after an upgrade, so setup never deletes it automatically.
Cleanup holds the runtime lock, verifies the selected tools, and always retains
the selected and previous environments. It skips symlinks, mounted trees,
junctions and unrecognized directories. Recognized obsolete generations have
an ownership record and virtual-environment configuration; the legacy `python/`
directory can be removed once it is outside the selected and previous pair.
The receipt lists candidates, completed removals, skipped paths and errors.
If deletion fails partway, `prune.partial_removal_possible` requires inspection.

From a connected church folder, use `python3 handbuilt.py runtime prune`.
The cleanup flags are host operations; present a plain-language
maintenance plan to the pastor.

## Maintain the wheel lock

`doctor` validates the lock offline and checks its pins against `requirements.txt`.
Missing, malformed or changed lock inputs block readiness and setup. Updating a
pin requires reviewing the official release and refreshing the paired lock
through an inspected security-patched interpreter:

```bash
"<patched-python>" -m tools.lock_runtime_requirements --output requirements.lock
```

This maintainer command reads exact-version PyPI metadata and includes wheel
hashes only. It never runs during pastor setup. Recheck supported interpreter
and platform wheel coverage, run the tests and rehearse setup before shipping.
New installation receipts record the binary-only policy and wheel-lock digest.

## Finish computer preparation

If the result is `native-tool-missing`, read the `native_install` plan from the
JSON result. Explain that this is a computer-level PDF tool, ask for approval,
then run the proposed command through the host workflow:

```bash
python3 tools/handbuilt_runtime.py native-install --format json
```

Run `doctor` again after the operation. On macOS, the supported first adapter
uses Homebrew to install Poppler. On Linux, it uses an available distribution
package manager. If no supported manager is available, do not invent a
download URL or ask the pastor to guess a command.

If Python or Homebrew itself is absent, follow the
[computer preparation reference](../skills/onboarding/references/computer-preparation.md)
for host inspection and official installation guidance. When an installer
needs human interaction, identify the app/window, give one next action, and
verify the result after the person completes it. Preserve progress on retries.

## Verify PDF work

Before importing a bulletin PDF or using the bulletin workflow, run:

```bash
"<runtime.python>" "<plugin-root>/tools/handbuilt_runtime.py" verify --format json
```

`verify` requires the full bulletin dependency check, then renders a small
sample PDF and checks its page count, embedded fonts, extracted text, and page
image. It uses a temporary directory and removes it on completion, without
installing anything or modifying church work. A bounded subprocess failure
reports `install-failed` and `technical_detail`. This detects failures loading
native rendering libraries, such as Pango, that package metadata alone cannot
detect. Use the detail to repair the failing component before retrying; do not
repeat unrelated installations. See the official
[WeasyPrint dependency instructions](https://doc.courtbouillon.org/weasyprint/latest/first_steps.html).

The church launcher uses workspace checks for church settings, brand settings,
and sermon research, and `verify` for bulletin operations. Existing commands
remain valid. To inspect from a connected church folder:

```bash
python3 handbuilt.py runtime doctor --capability workspace
python3 handbuilt.py runtime verify
python3 handbuilt.py runtime setup --bootstrap-python "<inspected patched Python>"
python3 handbuilt.py runtime rollback
```

The sample verifies the computer tools. Every church bulletin still needs its
source, layout-review, and final approval checks.

For workflow version selection, use the app-loaded `church_workflow.py start`
command once before the workflow operation. It can select a verified managed
release outside the host plugin cache. See [managed workflow updates](workflow-updates.md)
for the returned launcher prefix, stable and pinned policies, and offline
fallback.

A dependency-changing release can be deferred because the current runtime does
not meet its requirements. Refresh the host plugin to the security release,
run its explicit `setup` operation with an inspected patched interpreter, then
retry `ensure-latest` and `start`. Older host launchers only validate candidates;
they cannot run migration code they have not received. Keep that validation
gate and intentional pinned connections. A blocked result includes a
`runtime_repair` plan for the host; `doctor` never starts a package install.

Read `runtime.python` from the JSON result and use that exact executable for
bulletin rendering and booklet imposition. Do not fall back to bare `python3`
for production after the managed runtime is ready.

The default runtime location is owned by Handbuilt and scoped to the current
computer user:

- macOS: `~/Library/Application Support/Handbuilt Church Labs/runtime`
- Windows: `%LOCALAPPDATA%/Handbuilt Church Labs/runtime`
- Linux: `$XDG_DATA_HOME/handbuilt-church-labs/runtime`, or the standard local
  data directory when that variable is not set

For tests or managed deployments, `HANDBUILT_RUNTIME_HOME` can override this
location.

## Stable statuses

| Status | Meaning | Host response |
| --- | --- | --- |
| `ready` | Dependencies for the requested capability are available; `verify` also exercises the PDF tools. | Continue that work. Run `verify` before PDF work if only `doctor` has passed. |
| `python-unavailable` | A usable Python 3 runtime could not be found. | Arrange computer-level Python setup. Do not suggest global pip commands. |
| `python-package-missing` | The private runtime is absent or incomplete. | Run `setup` once. |
| `native-tool-missing` | Python is ready, but one or more Poppler tools are absent. | Ask for approval, run the reported native setup plan, then run `doctor` again. |
| `install-failed` | Installation or the working PDF check failed. | Use `technical_detail` to repair the failing component. Do not use a global package install as a workaround. |

Python packages and native PDF tools are reported in separate JSON sections.
This lets onboarding explain whether bulletin creation is blocked or only the
print-verification gate is blocked.

## What the pastor sees

Use the result's `message` and `next_action`, translated into the action the host
agent will take. A normal first-run message can be:

> I need to prepare Handbuilt's private bulletin tools on this computer. This
> stays separate from your church folder. I will check it again before we build
> your bulletin.

Do not ask the pastor to choose package names, virtual environments, or pip
commands.

## Current integration boundary

The plugin prepares and selects verified private runtime generations and can
install Poppler through a supported system package manager. It does not
bundle or install Python or Homebrew themselves. Computer-level changes use
the host's installer and permission surface. There is no graphical bootstrap
when Python is absent; the host must inspect the computer and guide that
preparation before this Python helper can run. Nothing in this update replaces
the existing installer or changes the church's customizable workspace.

Input size and processing limits are documented in [input limits](input-limits.md).
Runtime verification and repository tests use synthetic files, never a church's
financial report or approved bulletin.
