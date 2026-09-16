# Computer preparation and runtime checks

The pastor should never have to manage Python packages or type setup commands.
The host agent owns this check and presents only the plain-language message from
the result.

## Host workflow

For **Set up my church workspace**, check from the installed plugin directory:

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
```

The sample verifies the computer tools, not a church's actual bulletin. All
source, layout-review, and final approval checks still apply to that bulletin.

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

The plugin prepares Python packages in its existing managed environment and
can install Poppler through a supported system package manager. It does not
bundle or install Python or Homebrew themselves. Computer-level changes use
the host's installer and permission surface. There is no graphical bootstrap
when Python is absent; the host must inspect the computer and guide that
preparation before this Python helper can run. Nothing in this update replaces
the existing installer or changes the church's customizable workspace.
