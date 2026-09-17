---
name: onboarding
description: "Set up my church workspace: create or resume a private church folder through website discovery and worship setup. Use when a pastor asks to set up their church workspace, get started, run onboarding, check saved setup, or update standing church preferences."
---

# Set up my church workspace

Create a private church folder, a useful church profile, and a visible progress
record. Recover source facts before asking the pastor for configuration details.

The pastor owns this workspace and may add, edit, replace, or remove its
instructions, skills, and files. This skill governs requested Handbuilt setup.
It does not restrict other work. Read [Workspace customization](../../handbook/workspace-customization.md)
for local skills, custom editing, or updating an existing folder's instructions.

Read supporting references when their stage is reached:

- [Computer preparation and progress](references/computer-preparation.md) at the start or when resuming setup.
- [Connection and visual setup](references/connection-and-brand.md) when creating or resuming a church folder.
- [Website discovery and QR](references/website-discovery.md) for bounded
  website inspection, brand candidates, and QR destinations.
- [Worship onboarding](references/worship-onboarding.md) after the private
  folder exists and the pastor can provide a bulletin or use the fallback
  questions.
  when onboarding identifies more than one recurring service, a reusable part,
  or a scoped change that must carry into later bulletins.

## Source roles

- **Website:** public identity, names, leadership, contact details, service
  times, brand candidates, newcomer information, and likely QR destinations.
- **Recent bulletin:** the initial working template for the order of worship,
  printed responses, music and service structure, recurring sections, role
  slots, and page layout.
- **Pastor:** resolution of conflicts, missing values, local or
  licensed text, and later changes to the working template.

The website proposes public identity values for one bundled confirmation. A
bulletin deliberately supplied for onboarding is the church's working template
until the pastor changes it. Carry its observable structure forward without
asking the pastor to approve each section separately. Keep date-specific
readings, hymns, petitions, announcements, and names as weekly replacements.

For recurring services and reusable parts, follow [Service design](../bulletin/references/service-design.md).
Recover saved choices, recommend the closest order, verify scoped saves, and explain what carries forward.

## Proactive working-template contract

Complete all safe inspection and extraction before asking a question. The
pastor should approve a concrete proposal, not help the agent discover facts
that are already available on the website or in the bulletin.

Ask only when:

- two sources conflict in a way that changes the result;
- a required value cannot be observed and blocks the first useful result;
- local or licensed text needs a confirmed source location; or
- the pastor must choose between materially different outcomes.

Bundle related website facts into one confirmation. Do not ask for a second
confirmation of the bulletin template. Save a clear bulletin structure and
choice as a working default; ask one bundled question only where it is
ambiguous.

Assume the pastor is new to a local agent. Say what you are doing, why it
matters, what happens next, whether anything leaves the computer, and what was
saved. Announce and take the next defined action. Do not wait for the pastor to ask "what's next?"
Evidence ledgers and internal artifacts support the work. Maintain them quietly. Report the useful result and link progress once.

## Required stage sequence

Do not ask a later-stage question while an earlier stage is incomplete:

`workspace runtime ready -> welcome -> website discovery -> identity confirmed -> private
folder created -> worship source chosen -> worship setup -> first useful result
-> optional setup when requested`

At each transition, inspect available sources, take defined safe actions,
explain why the decision matters and what it enables, ask one focused question when needed, then
read back the answer in plain language, then batch and verify the update.
Report the pastor-facing result, not an internal
file inventory.

Ask no more than three questions in one turn, and prefer none when sources
answer them. Use one question for an unfamiliar or consequential choice.
“Later,” “not sure,” “unknown,” and “not applicable” are valid; require no magic confirmation phrase.

## Runtime gate

Give a brief setup orientation, then follow
[Computer preparation and progress](references/computer-preparation.md).
Check all dependencies together, using workspace readiness for this stage:

```bash
python3 "<plugin-root>/tools/handbuilt_runtime.py" doctor --capability workspace --format json
```

After `ready`, use the returned `runtime.python` executable for workflow
commands. `<plugin-root>` is the installed plugin directory containing this
skill, not the private church folder. Quote complete executable and file paths.
Missing PDF tools remain pending until PDF import or bulletin work needs them.
Before that work, run the separate `verify` check described in the reference.

After the private church folder exists, run the app-loaded adapter once:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start onboarding
```

Read the returned skill path and use its exact `launcher` prefix for every
onboarding operation in this task. Do not run `start` again after reading it.
The normal `church-folder/handbuilt.py start onboarding` command remains valid
for a person checking the connection manually.

Run `onboarding status` through the returned launcher and read back saved values
and progress. Use the plugin root's `AGENTS.md` commands for requested tests.

## Welcome
Start with a short orientation before collecting details:

> Welcome. I’ll help set up a private church folder on this computer. It will
> hold your church information, bulletins, and sermon work. I’ll use your
> public website for public facts and, when available, a recent bulletin to
> understand the detailed order of worship. Nothing changes on your website.
> I’ll show you what I find before using it. You can say “not sure” or “later”
> at any point.

Ask for the church website. If there is no website, ask for the formal church
name and a short folder name instead. Never request passwords, payment details,
or private pastoral information about parishioners.

## Website discovery

After receiving a website, read the bounded website reference. Inspect the
homepage first, then only clearly relevant pages such as About, Worship,
Contact, Staff, Newcomers, Give, and Events. Do not crawl the whole site by
default.

Return a concise discovery report with:

- **What I found:** public name, tradition if clearly stated, address, service
  times, public leaders, contact details, and relevant links.
- **Brand preview:** logo candidates, colors, source pages, and print-quality
  concerns.
- **Possible conflicts:** disagreements across pages or with the pastor.
- **Still unknown:** only values that are missing and relevant to the
  first useful result.

Label each value as found on the website, supplied by the pastor, or proposed
from a visual sample. Show source pages before saving a value. A website
candidate is not a confirmed standing setting.

## Identity and private folder

Use website findings to propose the formal name, short name, tradition, city,
address, website, and regular services. Bundle the proposed identity, folder
name, location, and any conflicts into one confirmation. Do not confirm each
website field in a separate turn. Read back the exact folder name and location
before creating it.

The default location is the Desktop. Say what will happen:

> I have the folder name as “...” and the location as “...”. I’ll create that
> private folder now. It will contain a visible onboarding record showing what
> we found, what you confirmed, and what still needs attention.

Follow [Identity setup](references/identity-setup.md) to create the confirmed
folder with `church_setup.py create`, save the supported identity patch, and
verify its files. Immediately record the folder path, website source,
discovery summary, confirmed identity, pending items, and next step in
`ONBOARDING.md`. Tell the pastor the exact private path.

If the folder already exists, switch to update mode. Preserve custom skills,
host instructions, sermons, bulletins, and church-edited notes. Do not restore
intentionally removed files. Reconnection does not replace workspace guidance.

## Route to worship onboarding

Once the private folder exists, ask whether the pastor can provide a recent
bulletin in Word or PDF format. Explain that the website remains important for
identity, leadership, contact, brand, and QR work, while the bulletin can
become the initial working template for detailed worship and bulletin work.

If a usable bulletin is available, read and follow
[Worship onboarding](references/worship-onboarding.md), using the bulletin as
the working template for worship details and recurring bulletin structure. For
a supplied PDF, run the canonical [source import and
inventory](../bulletin/references/source-inventory.md) workflow and account
for every page; a shorter website roster never excuses skipping a supplied
standing directory or recurring section, only a recorded conflict or omission.

If no bulletin is available, read the same reference and use its standard
purpose-first worship questions. Missing a bulletin must not block onboarding
or pressure the pastor to find one.

## Safety and progress

Church-specific information, uploaded bulletins, licensed material, and
receipts belong in the private folder; this public repository holds only
reusable workflows and synthetic tests.

After each meaningful stage, report:

- what is **saved** and verified;
- what is **pending** because a tool or asset needs attention; and
- what is **still unresolved** because the pastor has not decided it.

Batch related changes and update the progress record at meaningful stage boundaries, not for every intermediate edit.

A successful terminal command or helper call is not proof onboarding is
complete: check the folder, progress record, configuration, and first result.

## Bounded setup updates
On return, read existing setup notes and preserve local work. Update requested values only.

When a setup value must be saved or changed, use the skill's
`scripts/church_setup.py` helper. It reads the existing `church.yaml` and `worship/profile.yaml`, validates a
small named patch, and writes only standing settings the bulletin and sermon
workflows already consume; it refuses paths inside the Labs repository,
either plugin cache, or a symlink into those locations. `status` reports
actual folder, bulletin, sermon, and first-result readiness from the files.
Use `--scope standing` for church defaults and `--scope service --service-id
<id>` for a saved service's usual choices. See the service-design reference
for previews, affected services, and stale-update protection. Keep dated
assignments and exceptions in the weekly workflow. This helper never edits
history or sermon files.
For a request that also prepares weekly clergy assignments or bulletin work,
read the bulletin skill and use its orientation and weekly-input guidance.
Finish the standing preference update, then continue that workflow from the
saved church context.
Before closeout, use the returned launcher prefix for `onboarding status`; do
not switch to the mutable church-folder launcher during this task.
Report each workflow from its readiness boolean. `needs_input` and
`partially_ready` never mean both workflows are complete. Correct stored values
from confirmed answers before asking again. Stop when the requested workflow
is ready or the pastor defers it. Call an actual first result only after checking
its output and receipt. The next requests can be “build my bulletin” and
“start my sermon research.” Do not automatically continue into QR, leadership,
layout, research-preference, or other optional questions.
