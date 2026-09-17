from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.plugin_identity import inspect_installation


class PluginIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.church = self.base / "church"
        self.church.mkdir()

    def test_separate_loaded_and_saved_roots_with_same_version_do_not_match(self):
        loaded = self._plugin("loaded", "0.5.0")
        saved = self._plugin("saved", "0.5.0")
        self._connection(saved)

        report = inspect_installation(loaded, self.church)

        self.assertEqual(report["loaded"]["version"], "0.5.0")
        self.assertFalse(report["connection"]["root_matches"])
        self.assertFalse(report["connection"]["connection_matches"])
        self.assertEqual(report["latest"]["status"], "unknown")

    def test_stale_saved_version_and_hash_are_reported_individually(self):
        loaded = self._plugin("loaded", "0.5.0")
        self._connection(loaded, version="0.4.9", sha="0" * 64)

        report = inspect_installation(loaded, self.church)

        self.assertTrue(report["connection"]["root_matches"])
        self.assertFalse(report["connection"]["version_matches"])
        self.assertFalse(report["connection"]["manifest_sha256_matches"])
        self.assertFalse(report["connection"]["connection_matches"])

    def test_old_cowork_and_new_code_roots_are_classified_from_actual_paths(self):
        cowork = self._plugin("Claude/local-agent-mode-sessions/old/rpm/plugin", "0.4.0")
        code = self._plugin(".codex/plugins/cache/handbuilt/0.5.0", "0.5.0")

        old = inspect_installation(cowork, self.church)
        new = inspect_installation(code, self.church)

        self.assertEqual(old["loaded"]["origin"], "claude-desktop")
        self.assertEqual(old["loaded"]["version"], "0.4.0")
        self.assertEqual(new["loaded"]["origin"], "codex")
        self.assertEqual(new["loaded"]["version"], "0.5.0")

    def test_host_cache_git_metadata_does_not_make_it_a_development_checkout(self):
        for relative, expected in (
            ('.codex/plugins/cache/handbuilt/0.6.1', 'codex'),
            ('.claude/plugins/cache/handbuilt/0.6.1', 'claude-code'),
            ('Claude/local-agent-mode-sessions/session/rpm/plugin', 'claude-desktop'),
        ):
            with self.subTest(origin=expected):
                root = self._plugin(relative, '0.6.1')
                (root / '.git').mkdir()
                self._connection(root)
                report = inspect_installation(root, self.church)
                self.assertEqual(report['loaded']['origin'], expected)
                self.assertFalse(report['connection']['development_connection'])

    def test_development_connection_is_flagged_without_replacement_claim(self):
        loaded = self._plugin(".codex/plugins/cache/handbuilt/0.5.0", "0.5.0")
        development = self._plugin("working-copy", "0.5.0")
        (development / ".git").mkdir()
        self._connection(development)

        report = inspect_installation(loaded, self.church)

        self.assertTrue(report["connection"]["development_connection"])
        self.assertFalse(report["connection"]["connection_matches"])
        self.assertNotIn("replace", json.dumps(report).lower())

    def test_missing_or_malformed_connection_returns_structured_errors(self):
        loaded = self._plugin("loaded", "0.5.0")

        missing = inspect_installation(loaded, self.church)
        self.assertEqual(missing["connection"]["status"], "missing")
        self.assertEqual(missing["connection"]["errors"], [{"code": "connection_missing"}])

        connection = self.church / ".handbuilt" / "installation.json"
        connection.parent.mkdir()
        connection.write_text("not json")
        malformed = inspect_installation(loaded, self.church)
        self.assertEqual(malformed["connection"]["status"], "invalid")
        self.assertEqual(malformed["connection"]["errors"], [{"code": "connection_malformed"}])

    def test_missing_and_inconsistent_manifests_leave_loaded_version_explicitly_unknown(self):
        missing = self.base / "missing"
        missing.mkdir()
        report = inspect_installation(missing, self.church)
        self.assertEqual(report["loaded"]["status"], "invalid")
        self.assertIsNone(report["loaded"]["version"])
        self.assertEqual({error["code"] for error in report["loaded"]["errors"]}, {"manifest_missing"})

        inconsistent = self._plugin("inconsistent", "0.5.0", claude_version="0.4.9")
        report = inspect_installation(inconsistent, self.church)
        self.assertEqual(report["loaded"]["status"], "invalid")
        self.assertIn({"code": "manifest_identity_mismatch"}, report["loaded"]["errors"])
        self.assertIsNone(report["loaded"]["manifest_sha256"])

    def test_latest_metadata_is_reported_separately_without_network_lookup(self):
        loaded = self._plugin("loaded", "0.5.0")
        report = inspect_installation(loaded, self.church, {"name": "handbuilt-church-labs", "version": "0.6.0"})

        self.assertEqual(report["loaded"]["version"], "0.5.0")
        self.assertEqual(report["latest"], {
            "status": "available", "name": "handbuilt-church-labs", "version": "0.6.0",
            "manifest_sha256": None, "errors": [],
        })

    def _plugin(self, relative, version, claude_version=None):
        root = self.base / relative
        self._manifest(root / ".codex-plugin" / "plugin.json", version)
        self._manifest(root / ".claude-plugin" / "plugin.json", claude_version or version)
        return root

    def _manifest(self, path, version):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": "handbuilt-church-labs", "version": version}, indent=2) + "\n")

    def _connection(self, root, version=None, sha=None):
        codex = root / ".codex-plugin" / "plugin.json"
        content = codex.read_bytes()
        data = {
            "plugin_name": "handbuilt-church-labs",
            "plugin_version": version or json.loads(content)["version"],
            "plugin_root": str(root.resolve()),
            "manifest_sha256": sha or hashlib.sha256(content).hexdigest(),
        }
        path = self.church / ".handbuilt" / "installation.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))


if __name__ == "__main__":
    unittest.main()
