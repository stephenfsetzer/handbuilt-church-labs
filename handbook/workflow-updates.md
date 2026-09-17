# Managed workflow updates

Handbuilt has three version identities. Keep them separate when diagnosing an
update:

1. **Latest stable release** is the newest published package from the official
   Handbuilt release channel.
2. **App-loaded plugin** is the plugin directory the current AI app loaded for
   this task. Its displayed version and host manifest integrations belong to
   the app.
3. **Saved working release** is the plugin root recorded in the church's
   `.handbuilt/installation.json`, including a verified managed release stored
   outside the host plugin cache.

The app-loaded launcher is the entry point for selection. After the private
church folder exists, run it once at the start of the workflow:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" start <workflow>
```

For a stable connection, that start check consults the official release channel
at most once each day. If a newer release is available, it downloads the
packaged skills and tools into Handbuilt's managed workflow store, verifies the
asset checksum and file manifest, checks the package identity and runtime, and
only then saves the new connection. The release check sends no church content
or credentials. A package that cannot pass validation is not selected.

The start result reports the app-loaded identity, the selected working release,
and an exact `launcher` command prefix. Read the returned skill at the path it
provides, then use that returned prefix for every operation in the task. This
keeps one workflow version in use while the task is running. Run `start` once
per workflow task. Do not call it again after reading the returned skill or
switch to the mutable `church-folder/handbuilt.py` launcher for that task.

If the release check is offline or unavailable, the last verified saved working
release remains available. A development plugin directory outside the app caches containing `.git`,
and a church connection explicitly saved as `pinned`, remain pinned and skip the
stable release check. Host caches may contain Git metadata and still receive
automatic updates. A stable connection can be selected again with the
app-loaded launcher when the pastor requests it:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" connect --update-policy stable
```

To keep the current app-loaded workflow fixed, use:

```bash
python3 "<app-loaded-plugin-root>/tools/church_workflow.py" \
  --church-folder "<church-folder>" connect --update-policy pinned
```

These commands save the selected policy and connection. They do not change a
host plugin cache. Do not reconnect merely because the app-loaded root and the
saved root differ. Run `start` first so the selector can inspect both roots and
choose the verified working release. Use `connect` only when the requested
stable or pinned policy is clear.

The managed workflow update is separate from the host app update. A new
bootstrap needs one host plugin update so the app-loaded tools include this
selector. After that, the managed release can update its packaged skills and
tools outside the host cache. It cannot change the version displayed by Claude
Cowork, update a host manifest integration, or promise that the app's plugin
controls need no manual action. Host marketplace controls remain the source of
truth for those identities.

For Claude Code, enable automatic plugin updates through `/plugin` >
**Marketplaces** > `handbuilt-church-labs` > **Enable auto-update**. Third-party
marketplaces default to off; follow any reload notification after an update.
See [Claude Code's documented behavior](https://code.claude.com/docs/en/discover-plugins#configure-auto-updates).

Cowork's **Sync automatically** setting controls GitHub marketplace sync.
Do not disable a working automatic-sync setup. For organization marketplaces,
enabling it requires repository admin access and approved GitHub App
permissions. Those permissions are not required to install this public
marketplace. If enabling sync requests permissions the user lacks, finish the
installation through **Sync** and use Handbuilt's managed workflow updates.
See [Claude's organization sync requirements](https://support.claude.com/en/articles/13837433-manage-plugins-for-your-organization).
Neither setting changes the managed stable or pinned selection described here.

Missing runtime packages during initial onboarding remain a guided setup issue.
Run the workspace doctor, follow its supported setup action, and check the
result again. A release check does not replace runtime preparation, and pending
PDF tools do not block workspace setup or sermon research.

## Release-owner procedure

To publish a workflow update, bump both plugin manifests to the same strict
`X.Y.Z` version and pass the full regression suite, hygiene scan, package check,
and skill validators before publishing. Rehearse an actual upgrade with
`python tests/smoke_managed_updates.py` from a prepared managed runtime.
The deterministic package includes tools, skills, scaffold, referenced handbook
pages, plugin manifests, root documentation, requirements, license, and notices.

Publish the matching tag and GitHub release. The publication workflow rebuilds
and validates that tagged package, then its `release-assets` job attaches
`handbuilt-workflow.zip` and `handbuilt-workflow.sha256` only after checks pass.
A release without both valid assets is unavailable to the updater. Never replace
an existing release's assets; publish a new version for any correction.

An ordinary git push or marketplace refresh does not publish a managed workflow
update. Inspect the successful asset job and release contents before announcing
that an update is available. The next daily release check can then select it.
