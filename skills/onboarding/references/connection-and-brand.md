# Connect the church folder and finish visual setup

The installed plugin owns skills and rendering code. The private folder owns
church information and results. Creating the folder also installs a small
`handbuilt.py` launcher and records its plugin location privately.

For every returning folder, compare `.handbuilt/installation.json` with the
plugin root of the skill the app currently exposes. An old cached installation
can still exist after an update; its presence does not make it current. If the
roots differ or the connection is missing, use this installed skill's root and run:

```bash
python3 "<plugin-root>/tools/church_workflow.py" --church-folder "<church-folder>" connect
python3 "<church-folder>/handbuilt.py" start onboarding
```

Read the exact skill path returned by `start`. Never infer the plugin location
from a previous conversation or use a personal skill as a replacement. If the
host has no installed Handbuilt plugin, repair installation before production.
Reconnection preserves church work and refuses to overwrite a customized launcher.

After creation, use the private launcher for supported operations:

```bash
python3 "<church-folder>/handbuilt.py" onboarding status
python3 "<church-folder>/handbuilt.py" brand status
python3 "<church-folder>/handbuilt.py" brand update --patch-file "<church-folder>/.brand-patch.json"
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
