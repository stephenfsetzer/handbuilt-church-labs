# FAQ

**Where does my church's data live?**

Your church data lives in the private church folder on your computer, on the
Desktop unless you choose another location. This repository contains reusable
workflows. It does not receive your church folder or generated files.

The AI service you choose may process messages and file content used during a
conversation under its own account settings and terms. Local storage and AI
processing are separate. Do not enter passwords, payment details, or
confidential pastoral case information during onboarding.

**Do I need to know how to code?**

No. You talk to the agent in plain language. Onboarding explains each decision,
saves progress, and shows what to do next. You can return to the private folder
in a later task without repeating the whole interview.

**Which AI tools can run the workflows?**

This release provides a Codex plugin manifest and a Claude Code plugin
manifest. The maintained local rehearsal routes install the repository as a marketplace
in Codex CLI or Claude Code CLI. New tasks then load the installed workflows. The repository has not established a
complete matrix across apps, models, operating systems, or account types.
Availability depends on the host and account. See the [installation guide](../README.md#installation-and-support).

**Can I use the church website and a bulletin together?**

Yes. The website proposes public identity details such as the church name,
address, leaders, contact details, and service schedule. A recent bulletin is
optional and supplies detailed order-of-worship and recurring-section evidence.
The agent bundles the website facts into one confirmation, then uses the
bulletin for the worship setup. Dated assignments and announcements stay
weekly material.

**Can I print the music in my bulletins?**

Only music your parish is licensed to reproduce, such as material covered by
your hymnal license, OneLicense, or the public domain. Keep your scans in the
private folder's `music/` directory. The public plugin does not ship copyrighted
church music.

**What about scripture text?**

The sermon workflow verifies either the appointed readings or the passage you
selected. Scripture printed in a bulletin must follow the chosen translation's
congregational-use terms. The shipped 1979 Book of Common Prayer liturgy text
is public domain.

**What does Lutheran support require?**

The Lutheran pack provides vocabulary and workflow rules for Holy Communion. It
does not redistribute ELW, LSB, or other copyrighted service-book text. Supply
the approved local service text in the private church folder when your selected
service requires it. The workflow reports a missing required source before
production and does not substitute another prayer or service text.

**What are the hidden sermon receipts?**

Receipts are machine records under the sermon folder's hidden `.receipts/`
directory. They bind each visible file to its content, source evidence, and
completed checks. The workflow recalculates those relationships before
continuing. Pastors do not need to open or edit receipts.

**Can the optional Monday automation write the sermon?**

No. When activated, it verifies readings and prepares the cited research brief,
then stops at the same `research_complete` state as a manual run. A
pastor-selected passage must first be confirmed for that service. Reflection,
outlining, drafting, and review are outside the Labs research workflow.

**How do I change the sermon research preferences?**

Use a plain-language request such as:

```text
Use simpler language in future research briefs.
```

The agent reads the current preference, clarifies scope only when needed, saves
the confirmed setting, and explains its effect. `church.yaml` holds standing
research preferences. A church-specific research template exists only when the
pastor explicitly asks for an override. Previous briefs remain history and do
not silently become templates for later weeks.

**The bulletin looks different from my current one.**

The current renderer offers two layouts: Classic and Modern. A supplied
bulletin helps establish recurring content and worship structure. It does not
guarantee exact reproduction of the source design. Review the generated pages
before printing. See the [printing guide](printing-guide.md).

**How does the bulletin know which worship prayers to use?**

Onboarding records the church's worship profile in `worship/profile.yaml`. The
bulletin workflow reads that profile and asks about unresolved or week-specific
choices. The renderer does not choose a Eucharistic Prayer or Prayers of the
People form from a hidden default. If a required local source is missing, it
waits for the church to supply the approved text.
