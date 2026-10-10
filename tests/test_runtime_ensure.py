"""Synthetic preparation tests: no real package installs or church records."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import handbuilt_runtime as runtime
from tools.workflow_updates import file_lock
from tools import church_workflow as bridge


class PackageRunner:
    def __init__(self):
        self.commands = []
        self.installed = {}
        self.fail_install = False
        self.fail_verify = False

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if command[1:3] == ['-m', 'venv']:
            python = Path(command[3]) / 'bin/python'
            python.parent.mkdir(parents=True)
            python.touch()
            return subprocess.CompletedProcess(command, 0, '', '')
        if command[1:4] == ['-m', 'pip', 'install']:
            if self.fail_install:
                raise subprocess.TimeoutExpired(command, 900)
            requirements = Path(command[-1]).read_text().splitlines()
            values = {name: 'synthetic' for name in runtime.PACKAGE_IMPORTS}
            values.update(dict(line.split('==') for line in requirements if line and not line.startswith('#')))
            self.installed[command[0]] = values
            return subprocess.CompletedProcess(command, 0, '', '')
        if runtime.VERSION_PROBE in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({'version': [3, 12, 1]}), '')
        if runtime.PACKAGE_PROBE in command:
            values = self.installed.get(command[0], {})
            # Match normalized names as the production package probe does.
            normalized = {runtime._normalize_distribution(k): v for k, v in values.items()}
            observed = []
            for item in command[command.index(runtime.PACKAGE_PROBE) + 1:]:
                name, module = item.split('\x1f')
                version = normalized.get(runtime._normalize_distribution(name))
                observed.append({'distribution': name, 'module': module, 'installed': version, 'importable': version is not None})
            return subprocess.CompletedProcess(command, 0, json.dumps(observed), '')
        if any(str(item).endswith('/runtime_probe.py') for item in command):
            value = {'ok': not self.fail_verify, 'checks': sorted(runtime.NATIVE_TOOLS + ('render',))}
            return subprocess.CompletedProcess(command, int(self.fail_verify), json.dumps(value), '')
        raise AssertionError(command)


class RuntimeEnsureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        (self.repo / 'requirements.txt').write_text('pypdf==1.0\n')
        self.store = self.base / 'support/runtime'
        self.runner = PackageRunner()

    def manager(self, missing=()):
        return runtime.RuntimeManager(repo_root=self.repo, runtime_root=self.store,
                                      bootstrap_python='/synthetic/python', system='Darwin',
                                      runner=self.runner,
                                      which=lambda name: None if name in missing else name)

    def ensure(self, **kw):
        return self.manager().ensure(**kw)

    def pip_commands(self):
        return [cmd for cmd in self.runner.commands if cmd[1:4] == ['-m', 'pip', 'install']]

    def test_first_use_installs_once_and_repeated_start_preserves_generation(self):
        first = self.ensure(capability='workspace')
        self.assertEqual(first['status'], 'ready')
        self.assertTrue(first['changed'])
        again = self.ensure(capability='workspace')
        self.assertEqual(first['runtime'], again['runtime'])
        self.assertFalse(again['changed'])
        self.assertEqual(len(self.pip_commands()), 1)
        self.assertEqual(self.pip_commands()[0][0], first['runtime']['python'])
        self.assertFalse((self.store / 'python').exists())

    def test_dependency_update_and_rollback_keep_two_tasks_on_distinct_runtimes(self):
        old = self.ensure(capability='workspace')
        (self.repo / 'requirements.txt').write_text('pypdf==2.0\n')
        new = self.ensure(capability='workspace')
        self.assertNotEqual(old['runtime']['root'], new['runtime']['root'])
        self.assertEqual(self.runner.installed[old['runtime']['python']]['pypdf'], '1.0')
        self.assertEqual(self.runner.installed[new['runtime']['python']]['pypdf'], '2.0')
        (self.repo / 'requirements.txt').write_text('pypdf==1.0\n')
        self.assertEqual(self.ensure(capability='workspace')['runtime'], old['runtime'])
        self.assertEqual(len(self.pip_commands()), 2)

    def test_failed_install_and_interruption_publish_nothing_and_retry_new_generation(self):
        self.runner.fail_install = True
        first = self.ensure(capability='workspace')
        self.assertEqual(first['status'], 'install-failed')
        self.assertFalse(list(self.store.rglob('selected.json')))
        self.runner.fail_install = False
        retry = self.ensure(capability='workspace')
        self.assertEqual(retry['status'], 'ready')
        self.assertNotEqual(first['runtime']['root'], retry['runtime']['root'])

    def test_failed_pdf_validation_preserves_previous_selection(self):
        old = self.ensure()
        marker = next(self.store.rglob('selected.json')).read_bytes()
        (self.repo / 'requirements.txt').write_text('pypdf==2.0\n')
        self.runner.fail_verify = True
        failed = self.ensure()
        self.assertEqual(failed['status'], 'install-failed')
        self.assertEqual(next(self.store.rglob('selected.json')).read_bytes(), marker)
        self.assertTrue(Path(old['runtime']['python']).exists())
        self.assertEqual(len(list(self.store.rglob('selected.json'))), 1)

    def test_mismatch_repairs_with_new_generation_instead_of_upgrading_running_task(self):
        old = self.ensure(capability='workspace')
        self.runner.installed[old['runtime']['python']]['pypdf'] = 'wrong'
        new = self.ensure(capability='workspace')
        self.assertNotEqual(new['runtime']['python'], old['runtime']['python'])
        self.assertEqual(self.runner.installed[old['runtime']['python']]['pypdf'], 'wrong')

    def test_concurrent_preparation_cannot_install_or_publish(self):
        identity = runtime.dependency_fingerprint(self.repo / 'requirements.txt', 'Darwin', [3, 12])
        with file_lock(self.store / 'environments' / identity / 'prepare.lock') as acquired:
            self.assertTrue(acquired)
            busy = self.ensure(capability='workspace')
        self.assertEqual(busy['status'], 'install-failed')
        self.assertIn('runtime_preparation_busy', busy['technical_detail'])
        self.assertFalse(self.pip_commands())
        self.assertEqual(self.ensure(capability='workspace')['status'], 'ready')

    def test_native_tools_remain_explicit_and_workspace_still_works(self):
        manager = self.manager(missing=runtime.NATIVE_TOOLS)
        workspace = manager.ensure(capability='workspace')
        self.assertEqual(workspace['status'], 'ready')
        blocked = manager.ensure()
        self.assertEqual(blocked['status'], 'native-tool-missing')
        self.assertEqual(len(self.pip_commands()), 1)
        self.assertFalse(any('poppler' in cmd for cmd in self.runner.commands))

    def test_unpinned_requirements_do_not_install(self):
        (self.repo / 'requirements.txt').write_text('pypdf\n')
        self.assertEqual(self.ensure()['status'], 'install-failed')
        self.assertFalse(self.pip_commands())

    def test_missing_bootstrap_does_not_create_a_runtime(self):
        failed = self.manager(missing=('/synthetic/python',)).ensure(capability='workspace')
        self.assertEqual(failed['status'], 'python-unavailable')
        self.assertFalse(self.store.exists())

    def test_selected_pointer_cannot_escape_generation_store(self):
        report = self.ensure(capability='workspace')
        identity = report['dependency_fingerprint']
        marker = self.store / 'environments' / identity / 'selected.json'
        value = json.loads(marker.read_text())
        value['root'] = str(self.repo)
        marker.write_text(json.dumps(value))
        self.assertIsNone(runtime.selected_runtime(self.store, identity))

    def test_offline_ready_generation_does_not_attempt_package_downloads(self):
        old = self.ensure(capability='workspace')
        self.runner.fail_install = True
        self.assertEqual(self.ensure(capability='workspace')['runtime'], old['runtime'])
        self.assertEqual(len(self.pip_commands()), 1)

    def test_failed_migration_keeps_matching_legacy_runtime_read_only(self):
        legacy = self.store / 'python/bin/python'
        legacy.parent.mkdir(parents=True)
        legacy.touch()
        values = {name: 'synthetic' for name in runtime.PACKAGE_IMPORTS}
        values['pypdf'] = '1.0'
        self.runner.installed[str(legacy)] = values
        self.runner.fail_install = True
        report = self.ensure(capability='workspace')
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(report['runtime_fallback'], 'legacy')
        self.assertEqual(report['runtime']['python'], str(legacy))
        self.assertNotEqual(self.pip_commands()[0][0], str(legacy))
        (self.repo / 'requirements.txt').write_text('pypdf==2.0\n')
        self.assertEqual(self.ensure(capability='workspace')['status'], 'install-failed')
        (self.repo / 'requirements.txt').write_text('pypdf\n')
        self.assertEqual(self.ensure(capability='workspace')['code'], 'invalid_requirements')

    def test_permission_denial_is_reported_without_selection(self):
        with mock.patch('tools.workflow_updates.file_lock', side_effect=PermissionError('synthetic denied')):
            failed = self.ensure(capability='workspace')
        self.assertEqual(failed['status'], 'install-failed')
        self.assertIn('permissions', failed['message'])
        self.assertFalse(self.store.exists())

    def test_startup_prepares_but_task_operations_check_pinned_runtime_without_installing(self):
        report = {'status': 'ready', 'runtime': {'root': '/synthetic/runtime', 'python': '/synthetic/runtime/python'}}
        with mock.patch.object(bridge.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(report), '')) as run:
            bridge._doctor('sermon-research', prepare=True)
            self.assertIn('ensure', run.call_args.args[0])
            bridge._doctor('sermon-research', runtime_root='/synthetic/runtime')
            self.assertIn('doctor', run.call_args.args[0])
            self.assertNotIn('ensure', run.call_args.args[0])
            self.assertIn('/synthetic/runtime', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
