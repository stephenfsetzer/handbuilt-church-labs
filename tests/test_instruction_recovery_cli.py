"""Exercise recovery through the church's actual launcher."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import make_church
from tools import church_workflow as bridge


class InstructionRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = make_church(Path(self.temp.name).resolve())
        self.instructions = self.church / "CLAUDE.md"
        self.custom = b"# Our church\n\n## Sermon help\nAsk about my week first.\n"
        self.instructions.write_bytes(self.custom)
        self.connected = bridge.connect(self.church)

    def command(self, *arguments, expected=0):
        result = subprocess.run(
            [sys.executable, str(self.church / "handbuilt.py"), "recovery", *arguments],
            cwd=self.church.parent, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_launcher_recovers_chosen_customization_and_keeps_newer_copy(self):
        saved = self.connected["instruction_recovery"]["snapshot_id"]
        changed = b"# A later requested edit\n"
        self.instructions.write_bytes(changed)
        self.command("history")
        shown = self.command("show", "--snapshot", saved, "--file", "CLAUDE.md")
        self.assertIn("Ask about my week first.", json.dumps(shown))
        self.command("restore", "--snapshot", saved, "--file", "CLAUDE.md",
                     "--expected-sha256", hashlib.sha256(changed).hexdigest())
        self.assertEqual(self.instructions.read_bytes(), self.custom)
        history = self.command("history")
        self.assertGreaterEqual(len(history["snapshots"]), 2)

    def test_stale_hash_is_rejected_and_custom_files_remain_unchanged(self):
        saved = self.connected["instruction_recovery"]["snapshot_id"]
        newer = b"# Another session's newer choice\n"
        self.instructions.write_bytes(newer)
        self.command("restore", "--snapshot", saved, "--file", "CLAUDE.md",
                     "--expected-sha256", hashlib.sha256(self.custom).hexdigest(), expected=2)
        self.assertEqual(self.instructions.read_bytes(), newer)

    def test_start_records_deletion_without_restoring_instruction_file(self):
        self.instructions.unlink()
        with mock.patch.object(bridge, "_doctor", return_value={"status": "ready", "runtime": {"python": sys.executable}}):
            result, code = bridge._start(self.church, "sermon-research", skip_update=True)
        self.assertEqual(code, 0, result)
        self.assertIn("instruction_recovery", result)
        self.assertFalse(self.instructions.exists())
        history = self.command("history")
        self.assertGreaterEqual(len(history["snapshots"]), 2)

    def test_returning_setup_retains_custom_file_bytes_and_modes(self):
        self.instructions.chmod(0o640)
        before = {name: (self.church / name).read_bytes() for name in ("CLAUDE.md", "AGENTS.md")}
        bridge._load_setup().create(self.church.parent, self.church.name)
        self.assertEqual(before, {name: (self.church / name).read_bytes() for name in before})
        self.assertEqual(self.instructions.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()
