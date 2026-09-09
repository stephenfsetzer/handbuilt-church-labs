# Runtime setup and doctor

The pastor should never have to manage Python packages or type setup commands.
The host agent owns this check and presents only the plain-language message from
the result.

## Host workflow

From the Handbuilt Church Labs repository, check the runtime first:

```bash
python3 tools/handbuilt_runtime.py doctor --format json
```

`doctor` is read-only. It does not create folders, install packages, or change
the pastor's church folder.

Python 3.10 or newer is required. If the bootstrap `python3` is older, locate
a supported interpreter already installed on the computer and pass its exact
path with `--bootstrap-python`. Do not replace an existing older environment
without preserving it and arranging migration.

If the result is `python-package-missing`, prepare the isolated runtime with
one host operation:

```bash
python3 tools/handbuilt_runtime.py setup --format json
```

`setup` uses Python's built-in `venv` support, then installs the exact tested dependency versions only through the
Python executable inside that environment. The doctor checks versions as well
as availability, and setup repairs mismatches. It does not write to global
site-packages or to the church's private folder.

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
| `ready` | The managed packages and PDF verification tools are available. | Continue to the first bulletin. |
| `python-unavailable` | A usable Python 3 runtime could not be found. | Arrange computer-level Python setup. Do not suggest global pip commands. |
| `python-package-missing` | The private runtime is absent or incomplete. | Run `setup` once. |
| `native-tool-missing` | Python is ready, but one or more Poppler tools are absent. | Ask for approval, run the reported native setup plan, then run `doctor` again. |
| `install-failed` | Creating the environment or installing its packages did not finish. | Preserve `technical_detail` for a maintainer. Do not use a global install as a workaround. |

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

This first slice prepares Python packages and reports missing operating-system
tools. It does not install Python itself or Poppler. Those changes need a host
installer with platform-specific permissions and a separate user approval
surface. It also does not yet provide a graphical launcher when no Python
interpreter exists, because a Python program cannot report its own absence.
The host must map a failure to start this helper to `python-unavailable`.
