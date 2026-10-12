# Install Handbuilt Church Labs with your AI agent

This page is written for the AI agent a pastor asks to install Handbuilt
Church Labs. If you are a pastor, you can paste this into your AI app:

```text
Please install the Handbuilt Church Labs plugin from
https://github.com/stephenfsetzer/handbuilt-church-labs
and turn on automatic updates so I always have the newest version.
Follow its INSTALL.md, and explain each step to me.
```

Later, to check that Handbuilt is current, the pastor can ask: "Check that
Handbuilt Church Labs is up to date." Section 3 covers that request.

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
- Never ask for a password in chat, and never change settings beyond this
  page without a yes.

Open with a short welcome, for example:

> Let's get Handbuilt Church Labs installed. It's a free set of church
> workflows (sermon research, bulletins, sermon videos and more) that your AI
> app loads like an add-on. I'll do the installing and explain each step.
> You'll only need to help if your computer asks for your password or a click.
> It usually takes a few minutes.

Use these progress labels and say which one you are on: **Plugin installed**,
**Updates turned on**, **Church Labs connected**, **Ready for church setup**.

## 1. Find out where you are running

Identify the host app before installing. Check what you can observe (your own
tools, environment, and the operating system) instead of asking the pastor.

- **Claude Code**, including the **Code** tab of the Claude desktop app: use
  section 2.
- **Claude Chat or Cowork**: you cannot install plugins from here. Give the
  pastor the point-and-click steps in the README's
  [Claude desktop app](README.md#claude-desktop-app) section, one step
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

Then turn on automatic updates (section 3) before anything else. An install
without them stays on the version it started with.

If the list already shows `handbuilt-church-labs@synced`, the pastor added
Handbuilt through Claude's **Customize** panel earlier, and claude.ai shares it
here. Install anyway and turn on updates for this copy too, so whichever copy
loads is current. Ask the pastor to confirm that **Sync automatically** is on
for the Handbuilt marketplace in that panel (README,
[Claude desktop app](README.md#claude-desktop-app)). Tell them so in one
sentence.

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
  "env": {
    "FORCE_AUTOUPDATE_PLUGINS": "1"
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
give the pastor the point-and-click steps in the README's
[ChatGPT and Codex desktop](README.md#chatgpt-and-codex-desktop) section, one
step at a time: **Settings**, **Plugins**, **Add**, **Add plugin
marketplace**, paste the address, set **Git ref** to `main`, then **Browse
directory** and **Install**. Do not edit Codex configuration files by hand.

**Updates in Codex:** the marketplace follows `main`. Codex has no
automatic-update switch documented for this marketplace, so do not claim one.
Tell the pastor that Handbuilt checks for verified workflow updates each time
church work starts (see section 3), and that the agent can refresh the app's
copy on request with `codex plugin marketplace upgrade handbuilt-church-labs --json`
followed by the `codex plugin add` line above.

## 3. Keep it updated

Claude Code needs two settings before Handbuilt updates itself, and an install
has neither by default:

- `"autoUpdate": true` on the `handbuilt-church-labs` marketplace. Claude Code
  leaves automatic updates off for marketplaces outside Anthropic's own.
- `FORCE_AUTOUPDATE_PLUGINS=1` in the settings `env`. The Claude desktop app
  starts its Code sessions with Claude Code's own updater switched off, and
  that also stops plugin updates unless this is set.

Handbuilt includes a script that merges both into the user settings file,
keeps every other setting, and saves a backup first. After the preferred
route, run it from the marketplace copy Claude Code just downloaded:

```bash
python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/marketplaces/handbuilt-church-labs/tools/claude_updates.py" enable
```

It prints `turned_on` or `already_on`. If it reports an error, the settings
file was left unchanged: read the message, and fall back to the careful manual
merge shown in section 2. The fallback route's settings already include both.

Then confirm the result:

```bash
python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/marketplaces/handbuilt-church-labs/tools/claude_updates.py" status
```

`status` reports the installed version, the latest release, and whether both
settings are on. Explain it to the pastor in one sentence:

> I've turned on automatic updates, so new Handbuilt improvements arrive on
> their own. When one arrives, starting a new session picks it up.

**When the pastor asks whether Handbuilt is up to date,** run `status`. If it
reports `current`, say so. If a setting is off, run `enable`. If the installed
version is older than the latest release, update now rather than waiting:

```bash
claude plugin marketplace update handbuilt-church-labs
claude plugin update handbuilt-church-labs@handbuilt-church-labs
```

Then tell the pastor to start a new session, which loads the new version.

Handbuilt also checks for itself. When a church workflow starts in Claude Code
and an install has automatic updates off, however it was installed, the start
result includes `claude_updates` with a question for the pastor and the
`enable` command to run on a yes.

Separately, once the church folder exists, Handbuilt checks for verified
workflow updates each time church work starts. See
[managed workflow updates](handbook/workflow-updates.md). Both keep the
church's own settings and files.

## 3b. Connect Church Labs

The plugin brings **Church Labs**, Handbuilt's connection for the cohort. With
it, the pastor can send Stephen a question or report a problem from any chat,
and see his answers there. It needs a one-time sign-in to Handbuilt. Do this
step before the hand-off, and tell the pastor first:

> One more thing: I'm connecting Church Labs, so you can send Stephen
> questions from here. A Handbuilt page will open in your browser. Sign in
> with the **same email you used to join the cohort**, then press **Connect**
> and come back here.

If they have no Handbuilt account yet, tell them to choose **Continue with
Google** or **Create an account** on that page.

**In Codex,** the plugin adds Church Labs but does not sign in by itself. Run:

```bash
codex mcp login church-labs
```

It opens the Handbuilt page and finishes once the pastor presses **Connect**.
Codex may ask permission first; explain that this signs in to Handbuilt.
`codex mcp list` should then show `church-labs` without "Not logged in". If
Codex says its model needs a newer version of Codex, update Codex first, then
run the sign-in again.

**In Claude Code,** a new plugin's connection loads in a new session, so this
happens right after the hand-off in section 4. In that new session, ask the
pastor to type `/mcp`, choose **church-labs**, then choose the option to
sign in (Claude Code may call it **Authenticate**). The same Handbuilt page
opens.

**In the Claude app** (Chat or Cowork, with the plugin added from the
**Customize** panel), Church Labs is on the plugin's **Connectors** tab: the
pastor chooses **Connect** there.

To check it worked, ask Church Labs for the pastor's answers. A new pastor
sees "Nothing yet." If the answer says the account isn't enrolled, they signed
in with a different email than the one they joined with: sign them out of
Handbuilt and connect again with that email. If the tools can't be found
later, run the sign-in step again.

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

In the terminal version of Claude Code, `/reload-plugins` also works. If the
pastor wants to stay in this session, try that first, then confirm the
`onboarding` skill is available before continuing.

This install lives in Claude Code, which includes the desktop app's **Code**
tab. It does not appear in Claude Chat or Cowork. Tell the pastor so in one
sentence, and that their church work happens in the Code tab. If they also
want Handbuilt in Chat or Cowork, give them the point-and-click steps in the
README's [Claude desktop app](README.md#claude-desktop-app) section;
an agent cannot do that part for them.

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
