# Handbuilt Church Labs

Practical AI workflows for small Episcopal and Lutheran churches.

Handbuilt Church Labs helps a pastor set up a private church folder, prepare
cited sermon research, and build worship bulletins for review. It is the Labs
learning and experimentation space for [Handbuilt](https://gethandbuilt.com).
You bring your church's practice and judgment. The plugin gives the agent a
repeatable way to help with the routine work.

## Start with your church

Install the plugin using the instructions below, then ask the agent:

```text
Help me set up my church with Handbuilt Church Labs.
```

The agent can inspect your public church website when you provide one and
propose the details it finds. It asks you to confirm the church identity and
where to create the private church folder. The Desktop is the default location.

A recent bulletin is optional. When you provide one, the agent uses it to
understand the order of worship and recurring sections. It keeps a private
source copy, extracts artwork and music, and records where each reviewed
section will be used. It asks before leaving supplied content out. When you
do not have a bulletin, it asks a short fallback set of worship questions. You can say "not sure"
or "later" for optional details.

The agent saves progress in the private folder and tells you what is ready and
what still needs attention. Sermon and bulletin readiness are reported separately.
Before the first bulletin, it saves a usable local logo and visual choices, or
your explicit choice to proceed without a logo. You do not need to edit
configuration files.

For the pilot, follow this short sequence: set up your church, run sermon
research, then build a bulletin. Review the research sources and bulletin PDF
before using the result in worship.

## Two weekly workflows

### Sermon research

```text
Start my sermon research.
```

The workflow verifies the coming Sunday's lectionary readings against two
published calendars, or records a passage you selected and checks it against a
published text. It produces a cited research brief with historical context,
interpretive possibilities, and questions for reflection. It ends at research.
You decide what to preach and how to draft it.

### Worship bulletins

```text
Build my bulletin for this Sunday.
```

The workflow starts with your saved worship choices, asks for this week's
changes, and produces a bulletin for review. The current renderer offers the
Classic and Modern layouts and booklet output. Importing a bulletin does not
promise an exact reproduction of its design. Some prayers, service-book text,
and music require material supplied by your church. A supplied logo appears on
the cover in both layouts. Large parish directories flow into the bulletin
body, and the church can save its usual closing-hymn position. Recurring
welcome and accessibility information can appear before or after the service.
Supplied event posters and QR artwork can accompany announcements without
being reduced to a text summary.

## Come back to your work

Your private church folder is the home for church details, preferences,
sermons, bulletins, and approved history. Open that folder in the same AI app
when you return, then ask for the work you need:

```text
Open my church folder and show me what is ready.
```

```text
Build this week's bulletin.
```

Use ordinary language to change a preference. Say whether the change is for
one service or for future work:

```text
Use simpler language in future research briefs.
```

```text
Use a different Eucharistic Prayer this Sunday only.
```

A small local launcher connects your church folder to the installed Handbuilt
workflows. It selects the required runtime and records which installation ran.
Skills remain in the plugin. If that connection breaks after an update or move,
ask Handbuilt onboarding to reconnect your existing folder.

The agent reads the current setting, saves the confirmed change, and explains
its scope. Existing approved work remains available. A change that affects an
existing result may require that result to be regenerated. Directory and
layout changes leave verified sermon research intact; changes to the chosen
readings, translation, or research preferences trigger the relevant recheck.

## Installation and support

Install Handbuilt Church Labs version 0.4.3 from [the Handbuilt Church Labs repository](https://github.com/stephenfsetzer/handbuilt-church-labs).
The point-and-click path below is the primary path for pastors. The repository
is public, so manual installation does not require a GitHub access grant.

### ChatGPT and Codex desktop

In the ChatGPT or Codex desktop app:

1. Open **Settings**, choose **Plugins**, then **Add**, and choose **Add plugin
   marketplace**. Enter

   ```text
   https://github.com/stephenfsetzer/handbuilt-church-labs.git
   ```

2. Set **Git ref** to `main` and leave **Sparse paths** blank, then choose **Add
   marketplace**. Adding the marketplace makes the catalog available; it does
   not install or enable the plugin.
3. In **Plugins**, choose **Browse directory**, search for **Handbuilt**, open
   **Handbuilt Church Labs**, and choose **Install**. Confirm that the plugin is
   enabled.
4. Start a fresh task outside the Labs development project and ask Handbuilt
   Church Labs to create your private church folder.

### Claude Chat and Cowork

Use the Claude desktop app in **Chat and Cowork** mode. Choose
**Customize** in the sidebar, then **Plugins**, **Add plugin**, **Add
marketplace**, and **Add from a repository**. Enter:

```text
https://github.com/stephenfsetzer/handbuilt-church-labs.git
```

Choose the offered **Use [pasted URL]** option. Leave **Sync automatically**
off, then choose **Sync**. In **Discover**, choose **Add Handbuilt Church Labs**.
Open **Yours** and confirm that the detail view shows version 0.4.3, three
skills, and **Enable plugin** on. The success message is
“Handbuilt Church Labs is installed and ready to use.”

Manual sync works without a new GitHub App grant. To update later, open
**Manage marketplaces**, find `handbuilt-church-labs`, open its More actions
menu, and choose **Check for updates**. Use the plugin's **Update** button if
it is offered. Start a new Cowork task after installing or updating. For a first setup, choose where to
create the private church work folder. Plain Chat is useful for conversation,
but Cowork is the right place for persistent local church work.

The graphical installation is verified in ChatGPT/Codex desktop, Claude Chat,
and Cowork. The full onboarding and bulletin workflows have been rehearsed in
Codex and Claude Code; the Cowork content workflow remains a pilot item. The
plugin has not been submitted to a public directory. This personal marketplace
path requires adding the marketplace first, so a public directory submission is
not needed for discovery here.

### Advanced CLI installation

These terminal commands are optional advanced routes for users who already
work in a CLI. The `/plugin` commands below are Claude Code terminal commands,
not desktop Chat commands.

#### Codex

In a terminal with Codex CLI installed, run:

```bash
codex plugin marketplace add https://github.com/stephenfsetzer/handbuilt-church-labs.git --ref main --json
codex plugin add handbuilt-church-labs@handbuilt-church-labs --json
```

Start a new task and ask for Handbuilt Church Labs onboarding.

#### Claude Code

In a terminal with Claude Code installed, run:

```bash
claude plugin marketplace add https://github.com/stephenfsetzer/handbuilt-church-labs.git
claude plugin install handbuilt-church-labs@handbuilt-church-labs
```

Inside an existing Claude Code terminal session, the equivalent commands are:

```text
/plugin marketplace add https://github.com/stephenfsetzer/handbuilt-church-labs.git
/plugin install handbuilt-church-labs@handbuilt-church-labs
```

Start a new task and ask for Handbuilt Church Labs onboarding.

### Update an installation

For desktop Claude, use **Manage marketplaces** and **Check for updates** as
described above. CLI users can refresh the marketplace first, then update the
plugin:

```bash
codex plugin marketplace upgrade handbuilt-church-labs --json
codex plugin add handbuilt-church-labs@handbuilt-church-labs --json
```

```bash
claude plugin marketplace update handbuilt-church-labs
claude plugin update handbuilt-church-labs@handbuilt-church-labs
```

Restart the app when required, then start a new task. Confirm that Handbuilt
is enabled in the app's plugin settings. If an update needs troubleshooting,
return to the same private church folder and ask Handbuilt onboarding to
reconnect it. Advanced users can also inspect the installed version with
`codex plugin list` or `claude plugin list`.

### Runtime and support

The agent checks the required local Python and print tools during setup and
guides you through any missing dependencies. See [runtime setup](handbook/runtime-setup.md).
You need Python 3.10 or newer. Handbuilt installs its Python packages into its
own managed environment.

Installation and workflow behavior depend on your app, model, account, and
operating system. The plugin has isolated Codex and Claude Code rehearsals and
automated regression tests; it does not claim every combination has been tested.
A new task is required after installing or updating the plugin. If an existing
church folder needs reconnecting after an update, ask Handbuilt onboarding to
reconnect it before starting weekly work.

Maintainers can find the canonical test commands in
[repository verification](AGENTS.md#repository-verification).

## What stays private

Your church folder is separate from this public repository. It holds church
details, source documents, licensed materials, generated work, and receipts.

The AI service you choose may process messages and file content used during a
conversation under that service's account settings and terms. A local folder
does not make AI processing offline. Do not include passwords, payment
information, or confidential pastoral case details in onboarding.

## Before you begin

The plugin includes a local Sunday text library for the English 1979 Book of
Common Prayer: Rite II prayer choices, Sunday collects and proper prefaces,
and the BCP Psalter. Choose the prayer your church uses; the agent loads its
verified text. It still verifies which readings and occasion apply to the day.
Modern Lutheran licensed texts remain in each church's private folder.

You need an AI app that can load local files, run Python, and open web sources
for the workflow you choose. Website discovery and sermon source research need
an internet connection. Your AI provider's account charges and usage limits
still apply.

The managed runtime keeps Python packages separate from global Python and from
your church folder. Printed music and local service-book text must be material
your church is permitted to reproduce. For Lutheran worship, the plugin does
not redistribute ELW or LSB text. Supply the approved local service text in the
private church folder when your chosen service requires it.

## Current limits

This is an early plugin. The repository has synthetic regression tests
and local workflow rehearsals. Those checks do not establish equivalent
onboarding behavior across every app, model, or operating system. Review church
facts, research claims, worship text, and final pages before use.

The current bulletin output is limited to the Classic and Modern layouts and
the supported 11x17 booklet workflow. The imported bulletin guides content and
recurring structure; it is not an exact design-fidelity guarantee.

When reporting a problem, describe what you expected and what happened. Use a
made-up example or remove private details. Do not attach an unredacted church
folder to a public issue.

See the [handbook](handbook/quickstart.md), [printing guide](handbook/printing-guide.md),
and [FAQ](handbook/faq.md).

## License

The software is released under the [MIT License](LICENSE). Liturgical sources
and other third-party materials retain their own terms; see
[third-party notices](THIRD-PARTY-NOTICES.md).
