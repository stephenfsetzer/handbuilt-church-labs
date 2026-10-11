# Guided computer setup

Read this whenever computer preparation needs something the agent cannot
finish alone: a missing tool, an installer, a password, a permission window,
or an error. It also applies during plugin installation (see the repository's
`INSTALL.md`).

Most pastors have never opened a terminal. Many have never heard of Homebrew,
Python, or Git. Treat each snag as a chance to teach one small thing. The
pastor should finish setup knowing what was installed, why, and where it lives.

## How to guide

1. **Do it yourself first.** Run every check and install the agent's own shell
   can complete. Hand a step to the pastor only when a person must act: typing
   a computer password, clicking a button in an installer or permission
   window, or signing in.
2. **One step at a time.** Give one action, then wait. Never paste a list of
   five commands and ask the pastor to work through them.
3. **Before each step, say four things in plain words:** what we are about to
   do, why it matters for their church work, what they will see on screen,
   and roughly how long it takes when that is known.
4. **After each step, check it yourself.** Confirm the result from the
   computer before moving on. A finished download does not prove an install.
   Tell the pastor briefly that it worked and what comes next.
5. **Explain a word the first time it appears.** Use the short explanations
   below. Say each one once, and do not lecture.
6. **Name the snag kindly.** Errors during setup are normal and usually mean
   one missing piece. Say what the message means, that nothing is broken, and
   the next action. Never blame the pastor or their computer.
7. **Keep a running picture.** Use the four progress labels from
   [Computer preparation and progress](computer-preparation.md): Plugin
   installed, Computer prepared, Church folder created, First useful result.
   Say which one you are on.
8. **Stop and ask before anything outside the plan.** Do not change system
   settings, remove software, or install extra tools to work around a problem
   without explaining and getting a yes first. Never ask for a password in
   chat. The computer's own prompt is the only place to type it.

## Plain-language explanations

Use these as written or in your own warm words. Keep each to two or three
sentences.

- **Terminal.** A window where you type instructions to your computer instead
  of clicking. I can run most of these myself; I'll only ask you to open it
  when your computer needs your password or your hands.
- **Command.** One line of instructions typed into the Terminal. You paste it,
  press Return, and wait until the Terminal shows a new blank line ending in
  `%` or `$`. That means it finished.
- **Homebrew.** A free, widely used app installer for Macs that works from the
  Terminal. Handbuilt uses it to add one small tool that reads PDF files, so
  it can import your bulletins. It lives in its own folder and does not change
  your other apps.
- **Command Line Tools (Apple).** A free package from Apple that many
  developer tools need, including Homebrew and Git. A Mac usually offers it in
  a pop-up window. It can take 5 to 20 minutes to download.
- **Python.** A programming language. Handbuilt's helpers are written in it,
  the way a document is written in English. Handbuilt keeps its own private
  copy of the pieces it needs, separate from the rest of your computer.
- **PDF tools (Poppler).** A small free tool that reads and checks PDF pages.
  Bulletin import and printing checks need it. Church setup and sermon
  research work without it, so it can wait.
- **Git and GitHub.** GitHub is a public website where Handbuilt's workflows
  are published. Git is the tool that downloads them and fetches updates. You
  will not need to use either directly.
- **Plugin.** A package of skills that teaches your AI app how to do church
  work the same careful way each time. Installing it does not give anyone
  access to your files.
- **Your computer password.** The password you use to unlock your Mac. When
  the Terminal asks for it, nothing appears as you type, not even dots. That
  is normal and keeps it private. Type it and press Return.
- **Administrator.** An account allowed to install software. On a personal
  Mac you almost always are one. On a church or diocese computer, someone else
  may manage it.

## Hand a step to the pastor

When a step needs the pastor's hands, give these instructions in order, one
message at a time, and wait for their reply between them.

### Open the Terminal on a Mac

> Press **Command and the Space bar** together. A search box appears in the
> middle of the screen. Type **Terminal** and press **Return**. A plain window
> with a blinking cursor opens. Tell me when you see it.

### Run one command in the Terminal

Give exactly one command in its own code block, then:

> Click inside the Terminal window, paste it with **Command and V**, and press
> **Return**. Let it run until you see a new line ending in `%`. Then copy
> what the Terminal shows (or take a screenshot) and paste it here so I can
> check it.

Read what the pastor sends back. Decide the next step from that output, not
from what you expected.

### Type the computer password

> The Terminal is asking for your Mac password. Type the password you use to
> unlock this computer and press **Return**. Nothing will appear while you
> type. That is normal.

If the Terminal says `Sorry, try again`, say the password did not match and
invite one more try. After three misses, pause and check whether this account
can install software.

### Click through an installer or permission window

Name the window title and the exact button, for example:

> A window titled "Install Command Line Developer Tools" should appear. Click
> **Install**, then **Agree**. It may say it will take a while. Leave it
> running and tell me when it says the software was installed.

For a macOS privacy prompt such as "would like to access files in your
Desktop folder", explain what is asking and why, then let the pastor choose.

### Open the Terminal on Windows

> Click **Start**, type **PowerShell**, and press **Enter**.

On Windows, prefer the official Python installer or `winget` when the host
reports it is available, and check the official instructions before giving a
command. Bulletin PDF tools on Windows have no supported installer in this
plugin yet; say so plainly, and continue with church setup and sermon
research.

## Common snags

Read the actual message first. Match it to a row only when the evidence fits.

| What the pastor sees | What it means | What to do |
| --- | --- | --- |
| A pop-up asking to install "command line developer tools" | The Mac needs Apple's Command Line Tools for Git or Homebrew. | Explain it, ask them to click **Install**, wait, then check with `xcode-select -p`. Do not trigger it again while it is running. |
| `command not found: brew` | Homebrew is not installed, or it is installed but this window cannot find it yet. | Check `/opt/homebrew/bin/brew` and `/usr/local/bin/brew` first. If it exists, use its full path and follow the "Next steps" lines Homebrew printed. If it is absent, install it (below). |
| Homebrew install stops at `Password:` | Homebrew needs permission to create its folder. | Hand the step to the pastor in the Terminal. The agent's shell cannot type a password. |
| `Need sudo access` or "not an administrator" | This account cannot install software. | Stop installing. Explain that church setup and sermon research can continue, and that bulletin PDF tools need someone with an administrator account. |
| A message that Homebrew does not support this Mac, or an Intel processor (`uname -m` prints `x86_64`) | Homebrew's support for Intel Macs is being phased out. | Check the current [Homebrew support tiers](https://docs.brew.sh/Support-Tiers) before advising. Continue with workspace and sermon research. Record bulletin PDF tools as pending, and do not loop on installs. |
| `python3` opens an Apple install pop-up or reports an old version | The Mac has a placeholder Python, not a usable one. | Look for a newer installed Python first. Otherwise use the official [python.org macOS installer](https://www.python.org/downloads/macos/) and walk them through its window. |
| `Operation not permitted` on a Desktop or Documents folder | macOS privacy settings blocked the app from that folder. | Explain the prompt, and let the pastor choose to allow it or pick another folder location. |
| Network errors, timeouts, or `Could not resolve host` | The internet connection dropped or a network blocks the download. | Ask them to check Wi-Fi, then retry once. On a church or diocese network, offer to wait until they are on another network. |
| The same error twice after a retry | Repeating will not help. | Stop, explain what you learned, and either try a different supported route or record the item as pending with one clear next step. |

## Install Homebrew with the pastor

Only install Homebrew when the doctor reports PDF tools missing, the host is a
Mac with Apple silicon or a supported tier, and the pastor wants bulletin work
now. Otherwise record it as pending.

1. Explain Homebrew in one or two sentences and ask whether to go ahead.
2. Read the [official installation guide](https://docs.brew.sh/Installation)
   or [brew.sh](https://brew.sh) for the current install command. Do not
   rewrite it from memory.
3. Have the pastor open the Terminal and run that one command (see above). It
   asks for their password, then may ask them to press Return to continue.
   It can take 5 to 15 minutes and may install Apple's Command Line Tools.
4. At the end, Homebrew prints "Next steps" with lines to run. Ask the pastor
   to paste that output. Give those lines back one at a time if they are
   needed.
5. Check `brew --version` yourself using the full path, then return to the
   runtime doctor and its `native-install` plan. That step installs the PDF
   tool without a password.

## Close each step

After every repaired item, say in one or two sentences what is now installed,
where it lives when that helps, and the next step. When setup is done, give a
short recap the pastor could repeat to a colleague, for example:

> Your computer is ready. We added Handbuilt's private Python helpers, and
> Homebrew with a small PDF reader so I can import your bulletins. None of it
> touches your other apps. Next, we'll set up your church folder.
