# Quickstart

## Set up my church workspace

1. Choose your app:

   - **ChatGPT or Codex desktop:** Open **Settings**, choose **Plugins**, then
     **Add**, **Add plugin marketplace**. Enter
     `https://github.com/stephenfsetzer/handbuilt-church-labs.git`, set **Git ref**
     to `main`, leave **Sparse paths** blank, and choose **Add marketplace**.
     Then choose **Browse directory**, search **Handbuilt**, open **Handbuilt
     Church Labs**, and choose **Install**. Adding the marketplace alone does
     not install or enable the plugin.
   - **Claude Chat and Cowork:** In the Claude desktop app, choose **Chat and
     Cowork** mode, then choose **Customize** in the sidebar, **Plugins**, **Add
     plugin**, **Add marketplace**, and **Add from a repository**. Enter
     `https://github.com/stephenfsetzer/handbuilt-church-labs.git`, then choose
     the offered URL option, then choose **Sync**. In **Discover**, choose
     **Add Handbuilt Church Labs**. Open
     **Yours** and confirm version 0.6.3, three skills, and **Enable plugin** on.
     Automatic sync does not need to be disabled. If enabling it asks for
     GitHub permissions you do not have, use **Sync** to finish installing.
     See the [installation and support guide](../README.md#installation-and-support) for optional
     Codex CLI and Claude Code CLI routes.
2. Start a fresh task in your chosen host. In Claude, start a Claude Cowork task
   with local folder access. For a first setup, choose where to create the
   private church work folder. In Codex, use a task outside the Labs
   development project. Ask:

   ```text
   Set up my church workspace.
   ```

3. Give the agent your church website when you have one. It proposes public
   identity details for one confirmation. A recent bulletin is optional and
   helps it understand your order of worship. Without a bulletin, it asks a
   short fallback set of questions.
4. Confirm the private folder name and location. The Desktop is the default.
   The agent writes the folder and an onboarding record, then tells you what
   is ready and what remains pending.

The website supplies public identity facts. The bulletin supplies the detailed
order of worship and recurring sections. Weekly assignments, announcements,
and other dated material remain weekly input.

The agent shows progress from plugin installed to computer prepared, church
folder created, and the first useful result. If something needs installation,
it explains the preparation together and gives one next action at a time.
An already-working computer proceeds without extra setup. Missing PDF tools
can wait while you set up the workspace or begin sermon research.
If you stop, return to the same task or open the church folder and say
“Continue setting up my church workspace.” The agent checks saved progress
and resumes what remains.

## Your first result

After setup, ask for one useful result:

```text
Start my sermon research.
```

or:

```text
Build my bulletin for this Sunday.
```

The sermon workflow shows its work in two files:

1. `readings.md`: the verified readings or pastor-confirmed passage.
2. `research-brief.md`: cited research with several interpretive possibilities.

The bulletin workflow creates a reviewable PDF and an 11x17 booklet PDF when
the selected source requirements are present. Read the result and approve it
before printing. Reflection, outlining, drafting, and sermon review are outside
the research workflow.

For the pilot, use the sequence above: finish onboarding, run sermon research,
then build and review a bulletin.

## Return to the private folder

Your church folder is the home for every sermon, bulletin, preference, source,
and approved record. It lives outside this repository. In a later task, open
the same folder in the AI app and say:

```text
Open my church folder and show me what is ready.
```

Then request the next action:

```text
Build this week's bulletin.
```

```text
Show me the preferences saved in my church folder.
```

If the folder is in a different location, use the app's open-folder control or
give the agent its path. It should read the existing `ONBOARDING.md` before
asking setup questions again.

Return to the same private church folder for weekly work. Your agent checks for
routine workflow updates automatically, while preserving your church settings,
local skills, and saved content. You do not need to track version numbers.

## Update the plugin

Existing installations need one app-level update to receive the automatic
workflow updater. Follow the [host update instructions](../README.md#update-an-installation),
confirm Handbuilt is enabled, and start a new task. Your private church folder
stays in place. The app's plugin panel may display a different version from the
working tools. See [managed workflow updates](workflow-updates.md) for advanced
troubleshooting and intentional version pinning.

## Change a preference

Your workspace can grow beyond the supplied workflows. Add local skills,
change the agent's instructions, and use other tools as needed. See
[Make your church workspace your own](workspace-customization.md).

Use ordinary language and state the scope:

```text
Use simpler language in future research briefs.
```

```text
Use Prayer B this Sunday only.
```

```text
Our usual service time is now 10:30.
```

The agent should read the current value, confirm an ambiguous scope, update the
relevant setting, verify it, and explain the effect. Approved history and
pastor-authored files remain in place. If an existing result depends on the
changed preference, the agent should tell you that it needs regeneration.

## Worship profile

The worship profile is `worship/profile.yaml`. It records the church's
tradition, service book, and standing choices such as the Eucharistic Prayer,
Lord's Prayer, and Prayers of the People. A weekly bulletin can override a
standing choice only when the pastor supplies and reviews that change.

You can state standing worship preferences in ordinary language, for example:

```text
Use the traditional doxology from now on.
```

The agent saves the named private setting and tells you what future bulletins
will do. A psalm format stays open until you choose responsive half verse,
responsive whole verse, unison, or plain text. A custom doxology is a private
text file with a source record. A change for one Sunday belongs in that dated
bulletin and does not change the standing preference.

For Episcopal Rite II, standard BCP prayers load from the plugin's verified
Sunday library. You do not need to find a prayer's public source or manage a
copy of it. The agent can also look up BCP Sunday collects, prefaces, and
psalms locally. Lutheran Holy Communion uses the church's licensed text. For public lectionary and scripture
sources, the agent retrieves and verifies published sources when the host can
reach them, then records the evidence. If retrieval fails, it reports that
research dependency and explains the next step. For Lutheran worship, the
plugin does not redistribute ELW or LSB service-book text. Supply approved
local service text in the private church folder when production needs it. If a
required church-supplied or licensed source is absent, the agent explains
what is needed and helps prepare it from a permitted bulletin or export.
You do not need to create the underlying technical files yourself.

When you supply local worship text, keep the original source beside the
formatted copy in the private church folder. The bulletin workflow records
the source location, verification date, method, and hashes before it uses the
text. Public sources need a retained source copy and a web address. An edited
copy must be checked and recorded again.

The separate doxology setting applies to the Episcopal service plan. In the
Lutheran service plan, keep any doxology within the church's verified local
order or Great Thanksgiving text so it is not printed twice.
