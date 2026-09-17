# Connect the church folder and finish visual setup

The installed plugin supplies maintained skills and rendering code. The private
folder owns local skills, instructions, church information, and results.
Creating the folder also installs a small
`handbuilt.py` launcher and records its plugin location privately.

For a returning folder, run the app-loaded adapter once for the requested
workflow. A different saved root can be the newer managed release or an
intentional development connection. Do not reconnect merely because roots differ.

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start onboarding
```

If `pinned_connection` is returned, keep the saved connection and start through
that church's `handbuilt.py`. Do not change a development or pinned connection
unless the pastor requests it. For an intentional policy change, follow
[managed workflow updates](../../../handbook/workflow-updates.md).

Read the exact skill path returned by `start` for a Handbuilt operation. Never
infer the plugin location from a previous conversation. If Handbuilt is absent,
repair its installation to use its commands. Other requested work can continue
with local or personal skills and available tools.
Reconnection preserves church work and refuses to overwrite a customized launcher.
It does not replace instruction files, copy over local skills, or restore
deleted guidance. For a requested update to an existing folder's restrictive
instructions, follow [Workspace customization](../../../handbook/workspace-customization.md).

After `start`, use its exact returned `launcher` prefix for supported operations.
Read the selected skill once and do not start again during the task:

```bash
<launcher-prefix> onboarding status
<launcher-prefix> brand status
<launcher-prefix> brand update --patch-file "<church-folder>/.brand-patch.json"
```

The agent prepares the patch. The pastor does not edit JSON. Download or extract
the church's chosen logo into its private `brand/` folder and check the image.
Use the supplied working bulletin's observable visual choices; ask only about
missing choices or conflicts. Explain that these choices control both covers.

Example patch after observing the working template:

```json
{
  "logo": {"mark": "brand/church-logo.png"},
  "logo_status": "provided",
  "colors_status": "confirmed"
}
```

Include the five `colors` values when changing the palette: `ink`, `accent`,
`accent_deep`, `paper`, and `rubric_red`, each a six-digit hex color. If the pastor
has no logo and accepts the neutral palette, save `logo_status: none` and
`colors_status: neutral`. Clear any previously configured logo paths first.
A missing, remote, or unreadable logo remains unfinished. Saying "later"
preserves progress; it does not mark bulletin setup complete.

`church.yaml` remains the authority for church identity. `brand.json.church`
contains only optional print-display overrides. Production merges the current
identity automatically; do not duplicate all church fields into the brand file.

Check both brand status and onboarding status after saving. Report sermon and
bulletin readiness separately. Each launcher run records its installed plugin,
script hash, interpreter, and result under private `.handbuilt/runs/`. A start
receipt proves tool selection, not completion. Final workflow receipts and
the actual research brief or rendered bulletin establish the useful result.
