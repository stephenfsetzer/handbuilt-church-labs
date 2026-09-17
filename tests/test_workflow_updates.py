from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import workflow_updates as updates


def release_bytes(number='0.6.0', extra=None):
    files = {name: b'fixture' for name in updates.REQUIRED}
    for host in ('.codex-plugin', '.claude-plugin'):
        files[host + '/plugin.json'] = json.dumps({'name': 'handbuilt-church-labs', 'version': number}).encode()
    files.update(extra or {})
    manifest = {'schema_version': 1, 'version': number,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['.handbuilt-workflow.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in files.items():
            entry = zipfile.ZipInfo(name)
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, data)
    return output.getvalue()


def install_fixture(root, number='0.5.0'):
    root.mkdir(parents=True)
    data = release_bytes(number)
    updates.unpack_verified(data, hashlib.sha256(data).hexdigest(), root, number)
    return root


class WorkflowUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.current = install_fixture(self.base / 'host')
        self.store = self.base / 'managed'
        self.archive = release_bytes()
        self.digest = hashlib.sha256(self.archive).hexdigest()
        self.urls = {name: f'https://github.com/{updates.REPOSITORY}/releases/download/v0.6.0/{name}'
                     for name in (updates.PACKAGE, updates.CHECKSUM)}
        self.metadata = {'tag_name': 'v0.6.0', 'draft': False, 'prerelease': False,
                         'assets': [{'name': name, 'browser_download_url': url} for name, url in self.urls.items()]}
        self.calls = []

    def download(self, url, limit):
        self.calls.append(url)
        if url == updates.LATEST_URL:
            return json.dumps(self.metadata).encode()
        if url == self.urls[updates.CHECKSUM]:
            return (self.digest + '  ' + updates.PACKAGE).encode()
        if url == self.urls[updates.PACKAGE]:
            return self.archive
        raise AssertionError('Unexpected request: ' + url)

    def select(self, **kwargs):
        return updates.select_release(self.current, self.store, kwargs.pop('validate', lambda root: None),
                                      download=kwargs.pop('download', self.download), now=lambda: 100000, **kwargs)

    def test_valid_release_is_verified_before_selection_and_host_is_unchanged(self):
        before = {p.relative_to(self.current): p.read_bytes() for p in self.current.rglob('*') if p.is_file()}
        validated = []
        result = self.select(validate=lambda root: validated.append(root))
        self.assertEqual(result['status'], 'updated')
        target = Path(result['selected_root'])
        self.assertEqual(updates.verify_installed(target), '0.6.0')
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[-1], target)
        self.assertFalse(result['host_plugin_updated'])
        self.assertEqual(before, {p.relative_to(self.current): p.read_bytes() for p in self.current.rglob('*') if p.is_file()})

    def test_daily_lookup_reuses_metadata_and_does_not_download_current_release(self):
        first = self.select()
        self.calls.clear()
        second = updates.select_release(Path(first['selected_root']), self.store, lambda root: None,
                                        download=self.download, now=lambda: 100010)
        self.assertEqual(second['status'], 'current')
        self.assertEqual(second['freshness'], 'cached')
        self.assertEqual(self.calls, [])

    def test_offline_keeps_current_and_does_not_retry_every_start(self):
        offline = mock.Mock(side_effect=OSError('offline'))
        result = self.select(download=offline)
        self.assertEqual((result['status'], result['selected_root']), ('deferred', str(self.current)))
        self.select(download=offline)
        self.assertEqual(offline.call_count, 1)
        self.assertEqual(result['freshness'], 'unknown')

    def test_development_checkout_never_downloads(self):
        (self.current / '.git').write_text('gitdir: fixture')
        result = self.select()
        self.assertEqual(result['status'], 'pinned')
        self.assertEqual(self.calls, [])

    def test_host_cache_with_git_metadata_still_selects_updates(self):
        self.current = install_fixture(self.base / '.codex/plugins/cache/handbuilt/0.5.0')
        (self.current / '.git').mkdir()
        result = self.select()
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['selected_version'], '0.6.0')
        self.assertIn(updates.LATEST_URL, self.calls)

    def test_checksum_failure_preserves_working_version(self):
        self.digest = '0' * 64
        result = self.select()
        self.assertEqual(result['selected_root'], str(self.current))
        self.assertEqual(result['status'], 'deferred')
        self.assertFalse(list((self.store / 'releases').glob('0.6.0-*')))

    def test_failed_runtime_validation_cannot_select_candidate(self):
        def broken(root):
            raise ValueError('missing runtime package')
        result = self.select(validate=broken)
        self.assertEqual(result['selected_root'], str(self.current))
        self.assertFalse(list((self.store / 'releases').glob('0.6.0-*')))

    def test_missing_assets_and_prereleases_are_not_installed(self):
        for changes in ({'assets': []}, {'prerelease': True}, {'tag_name': 'v0.6.0-rc1'}, {'assets': [None]}):
            with self.subTest(changes=changes):
                self.metadata.update(changes)
                result = self.select(force=True)
                self.assertEqual(result['status'], 'deferred')
                self.assertEqual(result['selected_root'], str(self.current))

    def test_cached_foreign_download_url_is_rejected_before_request(self):
        latest = updates.latest_release(self.download)
        latest['assets'][updates.CHECKSUM] = 'https://foreign.example/checksum'
        updates._atomic_json(self.store / 'latest-check.json', {'checked_at': 100000, 'latest': latest})
        self.calls.clear()
        result = self.select()
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(self.calls, [])

    def test_unsafe_or_modified_archives_are_rejected(self):
        for extra in ({'../escaped.py': b'bad'}, {'/absolute': b'bad'}, {'A': b'a', 'a': b'b'}):
            with self.subTest(extra=extra):
                data = release_bytes(extra=extra)
                with self.assertRaises(ValueError):
                    updates.unpack_verified(data, hashlib.sha256(data).hexdigest(), self.base / 'bad', '0.6.0')
        self.assertFalse((self.base / 'escaped.py').exists())
        target = Path(self.select()['selected_root'])
        (target / 'tools/church_workflow.py').write_text('changed')
        with self.assertRaises(ValueError):
            updates.verify_installed(target)
        self.assertEqual(self.select()['status'], 'deferred')

    def test_symlink_and_bad_file_hash_are_rejected(self):
        for symlink in (True, False):
            raw = release_bytes()
            output = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(output, 'w') as changed:
                for entry in original.infolist():
                    data = original.read(entry)
                    if entry.filename == 'tools/church_workflow.py':
                        if symlink:
                            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                        else:
                            data = b'changed'
                    changed.writestr(entry, data)
            raw = output.getvalue()
            with self.assertRaises(ValueError):
                updates.unpack_verified(raw, hashlib.sha256(raw).hexdigest(), self.base / 'bad', '0.6.0')

    def test_os_lock_is_reusable_after_release(self):
        with updates.update_lock(self.store) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.select()['reason'], 'another_update_in_progress')
        self.assertEqual(self.select()['status'], 'updated')

    def test_unknown_schema_is_not_selected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('.handbuilt-workflow.json', '[]')
        content = data.getvalue()
        with self.assertRaises(ValueError):
            updates.unpack_verified(content, hashlib.sha256(content).hexdigest(), self.base / 'bad', '0.6.0')


if __name__ == '__main__':
    unittest.main()
