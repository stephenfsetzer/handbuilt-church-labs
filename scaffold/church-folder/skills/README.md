# Your church's skills

Use this folder for skills you create or adapt for your church. Each skill
has its own folder with a `SKILL.md` file describing when to use it and what
to do. Keep its templates, examples, and scripts beside that file.

For example, ask your agent:

```text
Create a local newsletter skill in skills/parish-newsletter/SKILL.md.
Use my preferred tone and save a draft for me to review each week.
```

Then ask it to read and use that skill. The supplied `CLAUDE.md` and
`AGENTS.md` tell the agent to look here for relevant local skills. If you
change or remove those instructions, you can still give it the skill's path.
Putting a skill here does not automatically register it in an app's skill
menu; ask the agent to set up that app's discovery mechanism if you want one.

To adapt a Handbuilt skill, ask the agent to create a local version with a
distinct name and make your requested changes there. It should check every
relative reference and needed helper; copying only a SKILL.md may leave broken
references. A local skill can use installed Handbuilt tools for supported
operations and other tools for custom work. It must describe what it actually
checked and must not claim Handbuilt approval for changed or unchecked files.

These skills are yours. Edit or delete them whenever you need. Reconnecting
Handbuilt leaves them alone. Local adaptations do not automatically inherit
future plugin changes; ask your agent to compare versions when useful.
