import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from tools import instruction_recovery as recovery


class InstructionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.church = Path(self.temporary.name) / "church"
        self.church.mkdir(mode=0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, content, mode=0o640):
        path = self.church / name
        path.write_bytes(content)
        os.chmod(path, mode)
        return path

    def digest(self, content):
        return hashlib.sha256(content).hexdigest()

    def test_round_trip_restores_selected_file_and_backs_up_pre_restore_state(self):
        self.write("CLAUDE.md", b"first\n", 0o640)
        self.write("AGENTS.md", b"agents\n", 0o600)
        first = recovery.snapshot(self.church, "connected to this church")
        self.write("CLAUDE.md", b"second\n", 0o644)
        changed = recovery.snapshot(self.church, "observed local change")

        result = recovery.restore(self.church, first["snapshot_id"], "CLAUDE.md", self.digest(b"second\n"))

        self.assertEqual(b"first\n", (self.church / "CLAUDE.md").read_bytes())
        self.assertEqual(0o640, stat.S_IMODE((self.church / "CLAUDE.md").stat().st_mode))
        # The existing changed-state snapshot is a recoverable pre-restore
        # backup, so consecutive-state deduplication may return it.
        self.assertEqual("ok", result["backup"]["status"])
        backed_up = recovery.show_snapshot(self.church, result["backup"]["snapshot_id"], "CLAUDE.md")
        self.assertEqual("second\n", backed_up["text"])
        self.assertEqual(changed["snapshot_id"], result["backup"]["snapshot_id"])

    def test_deduplicates_only_consecutive_identical_states(self):
        self.write("CLAUDE.md", b"one")
        first = recovery.snapshot(self.church, "first observation")
        again = recovery.snapshot(self.church, "same observation")
        self.write("CLAUDE.md", b"two")
        second = recovery.snapshot(self.church, "new observation")
        self.write("CLAUDE.md", b"one")
        third = recovery.snapshot(self.church, "returned observation")

        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["snapshot_id"], again["snapshot_id"])
        self.assertTrue(second["created"])
        self.assertTrue(third["created"])
        listing = recovery.list_snapshots(self.church)
        self.assertEqual(3, len(listing["snapshots"]))
        self.assertEqual("missing", listing["current"]["AGENTS.md"]["presence"])

    def test_missing_and_deleted_files_are_observed_but_not_restored_as_deletions(self):
        self.write("CLAUDE.md", b"present")
        before_delete = recovery.snapshot(self.church, "before a deletion")
        (self.church / "CLAUDE.md").unlink()
        deleted = recovery.snapshot(self.church, "observed deletion")

        shown = recovery.show_snapshot(self.church, deleted["snapshot_id"], "CLAUDE.md")
        self.assertEqual("missing", shown["status"])
        with self.assertRaisesRegex(ValueError, "cannot be restored as a deletion"):
            recovery.restore(self.church, deleted["snapshot_id"], "CLAUDE.md", "missing")
        restored = recovery.restore(self.church, before_delete["snapshot_id"], "CLAUDE.md", "missing")
        self.assertEqual("restored", restored["status"])
        self.assertEqual(b"present", (self.church / "CLAUDE.md").read_bytes())

    def test_conflict_rejection_preserves_bytes(self):
        self.write("AGENTS.md", b"old")
        saved = recovery.snapshot(self.church, "before edit")
        self.write("AGENTS.md", b"new")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            recovery.restore(self.church, saved["snapshot_id"], "AGENTS.md", self.digest(b"other"))
        self.assertEqual(b"new", (self.church / "AGENTS.md").read_bytes())

    def test_rejects_target_and_store_symlinks(self):
        external = Path(self.temporary.name) / "external"
        external.write_text("external")
        (self.church / "CLAUDE.md").symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            recovery.snapshot(self.church, "unsafe target")
        second_church = Path(self.temporary.name) / "other-church"
        second_church.mkdir()
        (second_church / ".handbuilt").symlink_to(Path(self.temporary.name))
        with self.assertRaisesRegex(ValueError, "symlinked"):
            recovery.snapshot(second_church, "unsafe parent")

    def test_rejects_corrupt_snapshot_and_digest(self):
        self.write("CLAUDE.md", b"good")
        saved = recovery.snapshot(self.church, "valid snapshot")
        path = self.church / ".handbuilt" / "recovery" / "snapshots" / (saved["snapshot_id"] + ".json")
        payload = json.loads(path.read_text())
        payload["files"]["CLAUDE.md"]["content_b64"] = base64.b64encode(b"bad").decode("ascii")
        path.write_text(json.dumps(payload))
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ValueError, "hash check"):
            recovery.show_snapshot(self.church, saved["snapshot_id"], "CLAUDE.md")
        with self.assertRaisesRegex(ValueError, "hash check"):
            recovery.list_snapshots(self.church)

    def test_size_limit_and_private_store_permissions(self):
        self.write("CLAUDE.md", b"x" * (recovery.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            recovery.snapshot(self.church, "too large")
        self.write("CLAUDE.md", b"small")
        saved = recovery.snapshot(self.church, "valid size")
        snapshot_path = self.church / ".handbuilt" / "recovery" / "snapshots" / (saved["snapshot_id"] + ".json")
        self.assertEqual(0, stat.S_IMODE(snapshot_path.stat().st_mode) & 0o077)
        self.assertEqual(0, stat.S_IMODE((self.church / ".handbuilt" / "recovery").stat().st_mode) & 0o077)

    def test_list_is_read_only_when_no_store_exists(self):
        listing = recovery.list_snapshots(self.church)
        self.assertEqual("empty", listing["status"])
        self.assertFalse((self.church / ".handbuilt").exists())

    def test_existing_shared_handbuilt_parent_can_hold_private_recovery_store(self):
        parent = self.church / ".handbuilt"
        parent.mkdir(mode=0o755)
        os.chmod(parent, 0o755)
        self.write("CLAUDE.md", b"local instructions")

        saved = recovery.snapshot(self.church, "existing connection state")

        self.assertTrue(saved["created"])
        self.assertEqual(0o700, stat.S_IMODE((parent / "recovery").stat().st_mode))

    def test_cooperating_lock_rejects_second_snapshot_without_writing(self):
        self.write("CLAUDE.md", b"local instructions")
        recovery.snapshot(self.church, "initial snapshot")
        store = self.church / ".handbuilt" / "recovery"
        before = recovery.list_snapshots(self.church)

        with recovery._recovery_lock(store):
            with self.assertRaisesRegex(ValueError, "another recovery operation"):
                recovery.snapshot(self.church, "contended snapshot")

        self.assertEqual(before["snapshots"], recovery.list_snapshots(self.church)["snapshots"])

    def test_final_expected_hash_check_rejects_edit_during_restore(self):
        self.write("CLAUDE.md", b"saved")
        saved = recovery.snapshot(self.church, "saved state")
        self.write("CLAUDE.md", b"reviewed")
        original_observe = recovery._observe_target
        claude_observations = 0

        def edit_before_final_check(church, name):
            nonlocal claude_observations
            if name == "CLAUDE.md":
                claude_observations += 1
                if claude_observations == 3:
                    (church / name).write_bytes(b"outside edit")
            return original_observe(church, name)

        with mock.patch.object(recovery, "_observe_target", side_effect=edit_before_final_check):
            with self.assertRaisesRegex(ValueError, "changed during recovery"):
                recovery.restore(self.church, saved["snapshot_id"], "CLAUDE.md", self.digest(b"reviewed"))
        self.assertEqual(b"outside edit", (self.church / "CLAUDE.md").read_bytes())

    def test_rejects_nonregular_instruction_file(self):
        (self.church / "AGENTS.md").mkdir()
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            recovery.snapshot(self.church, "directory target")


if __name__ == "__main__":
    unittest.main()
