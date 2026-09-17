from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from tools.package_workflow import PackageError, build_package


class WorkflowPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "plugin"
        self.root.mkdir()
        self._write_fixture()
        self._git("init")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Synthetic Test")
        self._git("add", ".")
        self._git("commit", "-m", "fixture")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def _write(self, relative: str, contents: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def _write_fixture(self) -> None:
        manifests = {
            ".codex-plugin/plugin.json": {"name": "handbuilt-church-labs", "version": "1.2.3"},
            ".claude-plugin/plugin.json": {"name": "handbuilt-church-labs", "version": "1.2.3"},
        }
        for relative, manifest in manifests.items():
            self._write(relative, json.dumps(manifest) + "\n")
        for relative in (
            "requirements.txt",
            "LICENSE",
            "tools/church_workflow.py",
            "tools/handbuilt_runtime.py",
            "tools/workflow_updates.py",
            "tools/plugin_identity.py",
            "tools/instruction_recovery.py",
            "handbook/instruction-recovery.md",
            "scaffold/church-folder/handbuilt.py",
            "skills/bulletin/SKILL.md",
            "skills/onboarding/SKILL.md",
            "skills/sermon-research/SKILL.md",
        ):
            self._write(relative, f"synthetic file: {relative}\n")
        self._write("scaffold/church-folder/church.yaml", "name: Synthetic Parish\n")

    def test_build_is_deterministic_and_records_source_hashes(self) -> None:
        first = build_package(self.root, Path(self.temp.name) / "out-one")
        second = build_package(self.root, Path(self.temp.name) / "out-two")
        first_zip = Path(first["zip"]).read_bytes()
        second_zip = Path(second["zip"]).read_bytes()
        self.assertEqual(first_zip, second_zip)
        self.assertEqual(Path(first["sha256"]).read_bytes(), Path(second["sha256"]).read_bytes())
        self.assertEqual(first["zip_sha256"], second["zip_sha256"])
        with zipfile.ZipFile(first["zip"]) as archive:
            names = archive.namelist()
            self.assertEqual(names[-1], ".handbuilt-workflow.json")
            metadata = json.loads(archive.read(names[-1]))
            self.assertEqual(metadata["schema_version"], 1)
            self.assertEqual(metadata["version"], "1.2.3")
            self.assertEqual(metadata["files"], first["files"])
            self.assertNotIn(".handbuilt-workflow.json", metadata["files"])
            self.assertTrue(all("/" not in name or not name.startswith("/") for name in names))

    def test_includes_tracked_public_template_and_excludes_private_or_test_files(self) -> None:
        self._write("scaffold/church-folder/private-church-data/secret.yaml", "secret\n")
        self._write("scaffold/church-folder/tests/fixture.txt", "test\n")
        self._git("add", ".")
        self._git("commit", "-m", "private fixture")
        result = build_package(self.root, Path(self.temp.name) / "out")
        with zipfile.ZipFile(result["zip"]) as archive:
            names = set(archive.namelist())
        self.assertIn("scaffold/church-folder/church.yaml", names)
        self.assertNotIn("scaffold/church-folder/private-church-data/secret.yaml", names)
        self.assertNotIn("scaffold/church-folder/tests/fixture.txt", names)

    def test_rejects_mismatched_manifest_name(self) -> None:
        manifest = self.root / ".claude-plugin/plugin.json"
        manifest.write_text(json.dumps({"name": "other-plugin", "version": "1.2.3"}), encoding="utf-8")
        with self.assertRaisesRegex(PackageError, "must name"):
            build_package(self.root, Path(self.temp.name) / "out")

    def test_rejects_mismatched_manifest_version(self) -> None:
        manifest = self.root / ".claude-plugin/plugin.json"
        manifest.write_text(json.dumps({"name": "handbuilt-church-labs", "version": "1.2.4"}), encoding="utf-8")
        with self.assertRaisesRegex(PackageError, "same version"):
            build_package(self.root, Path(self.temp.name) / "out")

    def test_rejects_symlink_inputs(self) -> None:
        link = self.root / "tools" / "linked.py"
        os.symlink("church_workflow.py", link)
        self._git("add", "tools/linked.py")
        self._git("commit", "-m", "symlink fixture")
        with self.assertRaisesRegex(PackageError, "Symlink inputs"):
            build_package(self.root, Path(self.temp.name) / "out")

    def test_rejects_missing_required_input(self) -> None:
        (self.root / "skills" / "bulletin" / "SKILL.md").unlink()
        with self.assertRaisesRegex(PackageError, "missing or not a file"):
            build_package(self.root, Path(self.temp.name) / "out")

    def test_rejects_output_inside_source(self) -> None:
        with self.assertRaisesRegex(PackageError, "outside the source root"):
            build_package(self.root, self.root / "dist")
        self.assertFalse((self.root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
