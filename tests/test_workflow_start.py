from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import make_church
from tools import church_workflow as bridge
from tools import workflow_updates as updates


class WorkflowStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.church = make_church(self.base)
        self.store = self.base / 'support' / 'workflows'
        self.host = self.base / 'host'
        for relative in ('tools', 'skills', 'scaffold', '.codex-plugin', '.claude-plugin'):
            shutil.copytree(bridge.ROOT / relative, self.host / relative, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(bridge.ROOT / 'requirements.txt', self.host)
        self.change_version(self.host, '0.5.0')
        self.new = self.store / 'releases' / '0.6.0-fixture'
        shutil.copytree(self.host, self.new)
        self.change_version(self.new, '0.6.0')
        self.seal(self.new)
        self.root_patch = mock.patch.object(bridge, 'ROOT', self.host)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.runtime_patch = mock.patch('tools.handbuilt_runtime.default_runtime_root', return_value=self.store.parent / 'runtime')
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.doctor_patch = mock.patch.object(bridge, '_doctor', return_value={'status': 'ready', 'runtime': {'python': sys.executable}})
        self.doctor_patch.start()
        self.addCleanup(self.doctor_patch.stop)
        bridge.connect(self.church)
        self.calls = []

    @staticmethod
    def change_version(root, number):
        for host in ('.codex-plugin', '.claude-plugin'):
            path = root / host / 'plugin.json'
            value = json.loads(path.read_text())
            value['version'] = number
            path.write_text(json.dumps(value))

    @staticmethod
    def seal(root):
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in root.rglob('*') if p.is_file() and p.name != '.handbuilt-workflow.json'}
        (root / '.handbuilt-workflow.json').write_text(json.dumps({'schema_version': 1, 'version': updates.package_version(root), 'files': files}))

    def dispatch(self, command, **kwargs):
        self.calls.append(command)
        entry = Path(command[1])
        if entry.name == 'handbuilt_runtime.py':
            return subprocess.CompletedProcess(command, 0, json.dumps({'status': 'ready'}), '')
        self.assertEqual(entry.name, 'church_workflow.py')
        with mock.patch.object(bridge, 'ROOT', entry.parent.parent):
            value, code = bridge._start(self.church, command[-2], skip_update=True)
        return subprocess.CompletedProcess(command, code, json.dumps(value), '')

    def connection(self):
        return json.loads((self.church / '.handbuilt/installation.json').read_text())

    def test_automatic_update_selects_skill_and_keeps_church_work_unchanged(self):
        before = {p.relative_to(self.church): p.read_bytes() for p in self.church.rglob('*')
                  if p.is_file() and '.handbuilt' not in p.parts and p.name != 'handbuilt.py'}
        result = {'status': 'updated', 'selected_root': str(self.new), 'selected_version': '0.6.0',
                  'latest': {'name': 'handbuilt-church-labs', 'version': '0.6.0'}, 'host_plugin_updated': False}
        with mock.patch.object(updates, 'select_release', return_value=result), mock.patch.object(bridge.subprocess, 'run', side_effect=self.dispatch):
            started, code = bridge._start(self.church, 'bulletin')
        self.assertEqual(code, 0)
        self.assertEqual(started['skill'], str(self.new / 'skills/bulletin/SKILL.md'))
        self.assertEqual(started['launcher'][1], str(self.new / 'tools/church_workflow.py'))
        self.assertEqual(started['app_loaded_identity']['version'], '0.5.0')
        self.assertEqual(self.connection()['plugin_version'], '0.6.0')
        self.assertEqual(before, {p.relative_to(self.church): p.read_bytes() for p in self.church.rglob('*')
                                 if p.is_file() and '.handbuilt' not in p.parts and p.name != 'handbuilt.py'})

    def test_offline_old_app_start_keeps_saved_newer_release(self):
        with mock.patch.object(bridge, 'ROOT', self.new):
            bridge.connect(self.church)
        def offline(root, store, validate):
            self.assertEqual(root, self.new)
            return {'status': 'deferred', 'selected_root': str(root), 'host_plugin_updated': False}
        with mock.patch.object(updates, 'select_release', side_effect=offline), mock.patch.object(bridge.subprocess, 'run', side_effect=self.dispatch):
            result, code = bridge._start(self.church, 'bulletin')
        self.assertEqual(code, 0)
        self.assertEqual(result['installation']['plugin_version'], '0.6.0')
        self.assertEqual(self.connection()['plugin_root'], str(self.new))

    def test_newer_host_with_failed_runtime_falls_back_to_saved_release(self):
        with mock.patch.object(bridge, 'ROOT', self.new):
            bridge.connect(self.church)
        self.change_version(self.host, '0.7.0')
        def dispatch(command, **kwargs):
            if Path(command[1]) == self.host / 'tools/handbuilt_runtime.py':
                return subprocess.CompletedProcess(command, 2, json.dumps({'status': 'blocked'}), '')
            return self.dispatch(command, **kwargs)
        with mock.patch.object(updates, 'select_release', side_effect=lambda root, *_: {'selected_root': str(root), 'status': 'deferred'}), mock.patch.object(bridge.subprocess, 'run', side_effect=dispatch):
            result, code = bridge._start(self.church, 'bulletin')
        self.assertEqual(code, 0)
        self.assertEqual(result['installation']['plugin_version'], '0.6.0')

    def test_newer_saved_host_installation_is_kept_when_old_app_starts(self):
        cached = self.base / 'other-host-cache'
        shutil.copytree(self.new, cached)
        with mock.patch.object(bridge, 'ROOT', cached):
            bridge.connect(self.church)
        with mock.patch.object(updates, 'select_release', side_effect=lambda root, *_: {'selected_root': str(root), 'status': 'deferred'}), mock.patch.object(bridge.subprocess, 'run', side_effect=self.dispatch):
            result, code = bridge._start(self.church, 'bulletin')
        self.assertEqual(code, 0)
        self.assertEqual(result['launcher'][1], str(cached / 'tools/church_workflow.py'))
        self.assertEqual(self.connection()['plugin_root'], str(cached))

    def test_racing_newer_connection_cannot_be_reported_as_ready_on_old_root(self):
        with mock.patch.object(updates, 'select_release', return_value={'selected_root': str(self.host)}), mock.patch.object(bridge, 'connect', return_value={'status': 'preserved'}):
            result, code = bridge._start(self.church, 'bulletin')
        self.assertEqual((code, result['code']), (2, 'connection_changed'))
        self.assertNotIn('launcher', result)

    def test_git_backed_codex_cache_defaults_to_stable_and_checks_updates(self):
        cached = self.base / '.codex/plugins/cache/handbuilt/0.5.0'
        shutil.copytree(self.host, cached)
        (cached / '.git').mkdir()
        with mock.patch.object(bridge, 'ROOT', cached):
            bridge.connect(self.church)
            self.assertEqual(self.connection()['update_policy'], 'stable')
            with mock.patch.object(updates, 'select_release', return_value={'selected_root': str(cached), 'status': 'current'}) as select:
                result, code = bridge._start(self.church, 'bulletin')
            select.assert_called_once()
            self.assertEqual(code, 0)
            self.assertEqual(result['identity']['loaded']['origin'], 'codex')
            bridge.connect(self.church, update_policy='pinned')
            with mock.patch.object(updates, 'select_release') as select:
                result, code = bridge._start(self.church, 'bulletin')
            select.assert_not_called()
            self.assertEqual(result['updates']['status'], 'pinned')

    def test_pinned_development_connection_survives_old_app_start(self):
        (self.new / '.git').write_text('gitdir: fixture')
        with mock.patch.object(bridge, 'ROOT', self.new):
            bridge.connect(self.church, update_policy='pinned')
        before = (self.church / '.handbuilt/installation.json').read_bytes()
        with mock.patch.object(updates, 'select_release') as select:
            result, code = bridge._start(self.church, 'bulletin')
        select.assert_not_called()
        self.assertEqual((code, result['code']), (2, 'pinned_connection'))
        self.assertEqual(before, (self.church / '.handbuilt/installation.json').read_bytes())

    def test_connection_write_failure_rolls_back_both_files(self):
        old = {p: p.read_bytes() for p in (self.church / 'handbuilt.py', self.church / '.handbuilt/installation.json')}
        original = bridge._atomic_bytes
        calls = 0
        def fail_once(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('write failure')
            return original(path, data)
        with mock.patch.object(bridge, '_atomic_bytes', side_effect=fail_once), mock.patch.object(bridge, 'ROOT', self.new):
            with self.assertRaises(OSError):
                bridge.connect(self.church)
        self.assertEqual(old, {p: p.read_bytes() for p in old})

    def test_fixed_command_prefix_survives_another_tasks_connection_change(self):
        with mock.patch.object(updates, 'select_release', return_value={'selected_root': str(self.host)}):
            started, code = bridge._start(self.church, 'sermon-research')
        with mock.patch.object(bridge, 'ROOT', self.new):
            bridge.connect(self.church)
        self.assertEqual(code, 0)
        self.assertEqual(started['launcher'][1], str(self.host / 'tools/church_workflow.py'))
        with mock.patch.object(bridge, '_record', return_value=self.church / 'receipt.json'), mock.patch.object(bridge.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{}', '')) as run:
            bridge.execute(self.church, 'sermon-research', 'orient', [])
        self.assertEqual(Path(run.call_args.args[0][1]), self.host / 'skills/sermon-research/scripts/sermon_workflow.py')
        bridge.connect(self.church, _automatic=True)
        self.assertEqual(self.connection()['plugin_root'], str(self.new))


if __name__ == '__main__':
    unittest.main()
