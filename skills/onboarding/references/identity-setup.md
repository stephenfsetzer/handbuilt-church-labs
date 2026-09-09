# Create, save, and verify church identity

Use this reference after the pastor confirms the identity and folder location.
Use the existing helper rather than copying files with improvised shell
commands. It checks the private-folder boundary and recognizes a returning
folder without overwriting its contents.

In the commands below, replace `<runtime.python>` with the executable returned
by the runtime doctor, `<plugin-root>` with the installed plugin directory,
and the destination and church paths with the confirmed private location.
Keep the quotes around paths. The destination directory must already exist.

```bash
"<runtime.python>" "<plugin-root>/skills/onboarding/scripts/church_setup.py" create --destination "<destination>" --name "sample-church"
```

If the result is `returning`, read the existing files and update only confirmed
changes. Otherwise, immediately record the confirmed identity, evidence,
unresolved items, and next step in the private `ONBOARDING.md`.

Save a JSON patch in the private folder, using only confirmed values. This is
a synthetic example of the accepted shape; never copy its sample identity
into a real church. Omit fields whose values have not been confirmed.

```json
{
  "church": {
    "name": "Sample Church",
    "short_name": "Sample",
    "tradition": "Episcopal",
    "city": "Sample City",
    "address": "1 Example Street",
    "website": "https://example.org",
    "regular_services": [
      {"day": "Sunday", "time": "10:30 AM", "label": "Eucharist"}
    ]
  },
  "bulletin": {
    "footer": {"address": "1 Example Street", "website": "https://example.org"}
  }
}
```

`regular_services` entries accept `day`, `time`, and optional `label`, not
`name` or `notes`. Keep website conflicts, provenance, and the setup date in
`ONBOARDING.md`. Do not add a `setup` section to the patch. Public contact
details used in print belong in `bulletin.footer`, which also accepts
`contact_name`, `phone`, and `email`.

```bash
python3 "<church-folder>/handbuilt.py" onboarding update --scope standing --patch-file "<church-folder>/.onboarding-standing-patch.json"
python3 "<church-folder>/handbuilt.py" onboarding status
```

Read back `church.yaml` and `ONBOARDING.md` against the confirmed values.
Check the returned `present` entries and that `worship/profile.yaml` exists.
An identity-only stage normally reports `folder_ready: true` with workflow
readiness still false. That means the identity is saved and worship setup is
next, not that the installation failed. Describe that distinction plainly
and continue to the worship-source question in the main skill.
