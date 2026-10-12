# Install Handbuilt Church Labs with your AI agent

This page is written for the AI agent a pastor asks to install Handbuilt
Church Labs. If you are a pastor, you can paste this into your AI app:

```text
Please install the Handbuilt Church Labs plugin from
https://github.com/stephenfsetzer/handbuilt-church-labs
and keep it updated. Follow its INSTALL.md, and explain each step to me.
```

## For the agent: how to treat the pastor

Assume the pastor has never used a terminal and may not know what a plugin,
GitHub, or Homebrew is. Follow
[Guided computer setup](skills/onboarding/references/guided-setup.md) for
tone, plain-language explanations, and common snags. In short:

- Do the work yourself. Hand a step to the pastor only when a person must act:
  a password, an installer or permission window, or a sign-in.
- Before each step, say what you are doing, why it matters, and what they
  will see. After it, check the result yourself and say what comes next.
- Explain each new word once, briefly. Treat errors as normal and fixable.
- Keep the machinery out of what you say. Do not name commands, file paths,
  backup files, slash commands, or terms like "marketplace" or "catalog" unless
  the pastor asks. Say "I'm adding Handbuilt to Claude's list of add-ons", not
  "running the claude installer command against the marketplace catalog".
- Never ask for a password in chat, and never change settings beyond this
  page without a yes.

Open with a short welcome, for example:

> Let's get Handbuilt Church Labs installed. It's a free set of church
> workflows (sermon research, bulletins, sermon videos and more) that your AI
> app loads like an add-on. I'll do the installing and explain each step.
> You'll only need to help if your computer asks for your password or a click.
> It usually takes a few minutes.

Use these progress labels and say which one you are on: **Plugin installed**,
**Updates turned on**, **Ready for church setup**.

## 1. Find out where you are running

Identify the host app before installing. Check what you can observe (your own
tools, environment, and the operating system) instead of asking the pastor.

- **Claude Code**, including the **Code** tab of the Claude desktop app: use
  section 2.
- **Claude Chat or Cowork**: you cannot install plugins from here. Give the
  pastor the point-and-click steps in the README's
  [Claude Chat and Cowork](README.md#claude-chat-and-cowork) section, one step
  at a time.
- **Codex**, in the ChatGPT desktop app's **Codex** mode, the Codex app, or
  the Codex CLI: use section 2b.
- **ChatGPT Chat or Work**: you cannot install plugins from here. Give the
  pastor the point-and-click steps in the README's
  [ChatGPT and Codex desktop](README.md#chatgpt-and-codex-desktop) section,
  one step at a time.

## 2. Install in Claude Code

The marketplace name and plugin name are both `handbuilt-church-labs`.

**Check Git first.** Installing from GitHub needs Git. Run `git --version`.
On a Mac without Apple's Command Line Tools, this opens an install pop-up.
That is expected: explain it with the guided-setup wording, have the pastor
click **Install**, wait, and check again.

**Preferred route, when `claude` is available in your shell:**

```bash
claude plugin marketplace add https://github.com/stephenfsetzer/handbuilt-church-labs.git
claude plugin install handbuilt-church-labs@handbuilt-church-labs
claude plugin list
```

The `.git` address uses HTTPS, so the pastor does not need a GitHub account or
key. Confirm `handbuilt-church-labs` appears in the list and is enabled.

If the list already shows `handbuilt-church-labs@synced`, the pastor added
Handbuilt through Claude's **Customize** panel earlier, and claude.ai shares it
here. Install anyway: the copy installed here takes precedence and gets
updates from this marketplace. Tell the pastor so in one sentence.

**Fallback, when `claude` is not on the path:** declare the marketplace in the
user settings file, `~/.claude/settings.json`. Tell the pastor you are adding
Handbuilt to the app's own settings file and why. Read the file first, keep
every existing setting, save a backup copy beside it, and merge in:

```json
{
  "extraKnownMarketplaces": {
    "handbuilt-church-labs": {
      "source": {
        "source": "git",
        "url": "https://github.com/stephenfsetzer/handbuilt-church-labs.git",
        "ref": "main"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "handbuilt-church-labs@handbuilt-church-labs": true
  }
}
```

Check that the file is still valid JSON. Claude Code downloads the plugin
when the next session starts.

## 2b. Install in Codex

The marketplace name and plugin name are both `handbuilt-church-labs`.

**Check Git first,** exactly as in section 2.

**Preferred route, when `codex` is available in your shell:**

```bash
codex plugin marketplace add https://github.com/stephenfsetzer/handbuilt-church-labs.git --ref main --json
codex plugin add handbuilt-church-labs@handbuilt-church-labs --json
codex plugin list
```

Confirm `handbuilt-church-labs` appears in the list and is enabled. These
commands download from GitHub and write to Codex's own settings folder, so
Codex may ask the pastor to approve them. Explain the request before it
appears: "Codex will ask permission to download Handbuilt from GitHub and
add it to its plugin list. Choose to allow it."

**Fallback, when `codex` is not on the path or the commands are refused:**
the point-and-click steps live in the Codex and ChatGPT desktop apps, not in
the Codex terminal (CLI), which has no Settings or Plugins screen. If you are
running in a desktop app, give the pastor the steps in the README's
[ChatGPT and Codex desktop](README.md#chatgpt-and-codex-desktop) section, one
step at a time: **Settings**, **Plugins**, **Add**, **Add plugin
marketplace**, paste the address, set **Git ref** to `main`, then **Browse
directory** and **Install**. If you are running in the Codex CLI, hand the
first two commands above to the pastor one at a time instead, using
[Guided computer setup](skills/onboarding/references/guided-setup.md#run-one-command-in-the-terminal).
Do not edit Codex configuration files by hand.

**Updates in Codex:** the marketplace follows `main`. Codex has no
automatic-update switch documented for this marketplace, so do not claim one,
and do not lead with its absence. Tell the pastor that Handbuilt checks for
verified workflow updates each time church work starts (see section 3), and
that the agent can refresh the app's
copy on request with `codex plugin marketplace upgrade handbuilt-church-labs --json`
followed by the `codex plugin add` line above.

## 3. Keep it updated

Claude Code leaves automatic updates off for marketplaces like this one. Turn
them on by making sure the `handbuilt-church-labs` entry in
`extraKnownMarketplaces` (user settings) has `"autoUpdate": true`, using the
same careful merge as above. The preferred route already writes that entry
without `autoUpdate`; add the field to it and keep its `source`. Explain it to the pastor in one sentence:

> I've turned on automatic updates, so new Handbuilt improvements arrive on
> their own. When one arrives, starting a new session picks it up.

Separately, once the church folder exists, Handbuilt checks for verified
workflow updates each time church work starts. See
[managed workflow updates](handbook/workflow-updates.md). Both keep the
church's own settings and files.

## 4. Hand off to church setup

A new plugin loads in a new session. Tell the pastor exactly what to do:

> Handbuilt is installed. To start using it, open a new session: click
> **New session** at the top of the sidebar, keep the same folder, and type
> **Set up my Church Command Center.** That starts a guided setup of your
> Church Command Center, a private folder on this computer for your church's
> details, sermons, bulletins, and skills. I'll check your computer, ask for
> your church's website, and show you what I find before saving anything.

In Codex, say instead: "Start a new task, outside this one, and type
**Set up my Church Command Center.**" The plugin is available in new Codex
tasks, and church work continues there.

Do not mention `/reload-plugins` to the pastor. **New session** is the one
step to give. Only in the terminal version of Claude Code, when the pastor
asks to stay in this session, may you suggest it, then confirm the
`onboarding` skill is available before continuing.

This install lives in Claude Code, which includes the desktop app's **Code**
tab. It does not appear in Claude Chat or Cowork. Say it as where to work,
not as a limit, for example: "Your church work happens here in the Code tab."
If the pastor asks about Chat or Cowork, give them the point-and-click steps
in the README's [Claude Chat and Cowork](README.md#claude-chat-and-cowork)
section; an agent cannot do that part for them.

From there, the [onboarding skill](skills/onboarding/SKILL.md) takes over,
including any missing computer tools, with the same guided approach.

## If something goes wrong

- Read the actual error before acting, and match it against the snags table
  in [Guided computer setup](skills/onboarding/references/guided-setup.md).
- Retry a failed step once only when you have changed something. A second
  identical failure means stop, explain plainly what you learned, and offer
  the next best route (for example the point-and-click steps in the README).
- Do not install other tools, change system settings, or delete anything to
  work around a problem without the pastor's yes.
