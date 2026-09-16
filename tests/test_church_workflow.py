from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import church_workflow as bridge
from tests.helpers import make_church


class ChurchConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.church = make_church(self.base)
        self.doctor = {"status": "ready", "runtime": {"python": sys.executable}}

    def test_create_connects_new_folder_and_returning_run_preserves_work(self):
        setup = bridge._load_setup()
        created = setup.create(self.base, "new-church")
        church = Path(created["church_folder"])
        self.assertEqual(created["connection"]["status"], "connected")
        note = church / "sermons" / "pastor-notes.md"
        note.parent.mkdir(exist_ok=True)
        note.write_text("Keep my notes")
        self.assertEqual(setup.create(self.base, "new-church")["status"], "returning")
        self.assertEqual(note.read_text(), "Keep my notes")
        self.assertTrue((church / "skills" / "README.md").is_file())
        self.assertFalse((church / "skills" / "bulletin").exists())

    def test_returning_setup_preserves_local_instructions_skills_and_deletions(self):
        setup = bridge._load_setup()
        church = Path(setup.create(self.base, "custom-church")["church_folder"])
        local_files = {
            "CLAUDE.md": "Use my parish newsletter skill when I request the newsletter.\n",
            "AGENTS.md": "Use my local skills and follow my editing preferences.\n",
            "skills/parish-newsletter/SKILL.md": "# Parish newsletter\nSave a draft for review.\n",
            "skills/parish-newsletter/template.md": "# This week\n",
        }
        for relative, content in local_files.items():
            path = church / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        removed = [church / "START-HERE.md", church / "skills/README.md"]
        for path in removed:
            path.unlink()
        before = setup.status(church)
        result = setup.create(self.base, "custom-church")
        self.assertEqual(result["status"], "returning")
        for relative, content in local_files.items():
            self.assertEqual((church / relative).read_text(), content)
        self.assertTrue(all(not path.exists() for path in removed))
        self.assertEqual(result["readiness"]["workflow_readiness"], before["workflow_readiness"])

        # A pastor may later remove the local skill and both host instructions.
        shutil.rmtree(church / "skills/parish-newsletter")
        for name in ("CLAUDE.md", "AGENTS.md"):
            (church / name).unlink()
        bridge.connect(church)
        setup.create(self.base, "custom-church")
        self.assertFalse((church / "skills/parish-newsletter").exists())
        self.assertTrue(all(not (church / name).exists() for name in ("CLAUDE.md", "AGENTS.md")))
        self.assertEqual(setup.status(church)["workflow_readiness"], before["workflow_readiness"])

    def test_launcher_missing_connection_blocks_without_running_workflow(self):
        result = subprocess.run([sys.executable, str(self.church / "handbuilt.py"),
                                 "start", "bulletin"], cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "handbuilt_not_connected")
        self.assertIn("Other work", json.loads(result.stdout)["message"])

    def test_missing_installation_blocks_and_does_not_search_personal_skills(self):
        bridge.connect(self.church)
        path = self.church / ".handbuilt/installation.json"
        info = json.loads(path.read_text())
        info["plugin_root"] = str(self.base / "missing-installation")
        path.write_text(json.dumps(info))
        result = subprocess.run([sys.executable, str(self.church / "handbuilt.py"),
                                 "start", "sermon-research"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "handbuilt_not_connected")

    def test_connect_preserves_custom_launcher_and_rejects_escaped_metadata(self):
        launcher = self.church / "handbuilt.py"
        launcher.write_text("custom content")
        with self.assertRaises(ValueError):
            bridge.connect(self.church)
        self.assertEqual(launcher.read_text(), "custom content")
        launcher.unlink()
        (self.church / ".handbuilt").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            bridge.connect(self.church)
        self.assertFalse((self.base / "installation.json").exists())

    def test_runtime_failure_cannot_invoke_a_workflow(self):
        blocked = {"status": "blocked", "code": "runtime_not_ready"}
        with mock.patch.object(bridge, "_doctor", return_value=blocked), mock.patch.object(bridge.subprocess, "run") as run:
            result, code = bridge.execute(self.church, "bulletin", "produce", [])
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_pdf_failure_blocks_bulletin_but_not_workspace_or_research(self):
        actual_run = subprocess.run
        runtime_calls = []

        def with_pdf_tools_unavailable(command, **kwargs):
            if any(str(value).endswith("/handbuilt_runtime.py") for value in command):
                runtime_calls.append(command)
                if "--capability" in command and command[command.index("--capability") + 1] == "workspace":
                    report = {**self.doctor, "native_tools": {"missing": ["pdftoppm"]}}
                    return subprocess.CompletedProcess(command, 0, json.dumps(report), "")
                report = {"status": "native-tool-missing", "next_action": "Prepare the missing PDF tools."}
                return subprocess.CompletedProcess(command, 2, json.dumps(report), "")
            return actual_run(command, **kwargs)

        with mock.patch.object(bridge.subprocess, "run", side_effect=with_pdf_tools_unavailable):
            workspace, workspace_code = bridge.execute(self.church, "onboarding", "status", [])
            research, research_code = bridge.execute(self.church, "sermon-research", "orient", ["--date", "2026-09-13"])
            bulletin, bulletin_code = bridge.execute(self.church, "bulletin", "produce", ["--input", "missing.json"])
        self.assertEqual(workspace_code, 0)
        self.assertEqual(research_code, 0)
        self.assertTrue(Path(workspace["handbuilt_run"]).is_file())
        self.assertTrue(Path(research["handbuilt_run"]).is_file())
        self.assertEqual((bulletin["code"], bulletin_code), ("runtime_not_ready", 2))
        self.assertEqual(bulletin["next_action"], "Prepare the missing PDF tools.")
        self.assertIn("verify", runtime_calls[-1])

    def test_working_check_failure_is_not_reported_as_another_package_install(self):
        report = {"status": "install-failed", "next_action": "Repair the native rendering library."}
        with mock.patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 20, json.dumps(report), "")):
            result = bridge._doctor("bulletin")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["next_action"], report["next_action"])

    def test_verify_cannot_be_requested_with_workspace_only_requirements(self):
        bridge.connect(self.church)
        result = subprocess.run([sys.executable, str(self.church / "handbuilt.py"),
                                 "runtime", "verify", "--capability", "workspace"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify always checks all PDF tools", json.loads(result.stdout)["message"])

    def test_pending_brand_blocks_bulletin_but_allows_research_orientation(self):
        brand = self.church / "brand.json"
        data = json.loads(brand.read_text())
        data["logo_status"] = "pending"
        data["colors_status"] = "pending"
        brand.write_text(json.dumps(data))
        with mock.patch.object(bridge, "_doctor", return_value=self.doctor):
            result, code = bridge.execute(self.church, "bulletin", "produce", ["--input", "missing.json"])
            research, research_code = bridge.execute(self.church, "sermon-research", "orient", ["--date", "2026-09-13"])
        self.assertEqual((result["code"], code), ("brand_not_ready", 2))
        self.assertEqual(research_code, 0)
        receipt = json.loads(Path(research["handbuilt_run"]).read_text())
        self.assertEqual(receipt["workflow"], "sermon-research")
        self.assertEqual(receipt["runtime_python"], sys.executable)
        self.assertEqual(receipt["installation"]["plugin_root"], str(bridge.ROOT))
        self.assertEqual(receipt["script_sha256"], __import__("hashlib").sha256(Path(receipt["script"]).read_bytes()).hexdigest())

    def test_arguments_cannot_switch_church_or_finalize_another_church(self):
        with self.assertRaises(ValueError):
            bridge.execute(self.church, "sermon-research", "orient", ["--church-folder=/tmp/another"])
        with mock.patch.object(bridge, "_doctor", return_value=self.doctor):
            with self.assertRaises(ValueError):
                bridge.execute(self.church, "bulletin", "finalize", ["--receipt", "../other.json"])

    def test_connection_tracks_actual_installed_copy(self):
        installed = self.base / "installed-plugin"
        for relative in [".codex-plugin/plugin.json", "tools/church_workflow.py",
                         "skills/onboarding/scripts/church_setup.py", "scaffold/church-folder/handbuilt.py"]:
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bridge.ROOT / relative, target)
        with mock.patch.object(bridge, "ROOT", installed):
            result = bridge.connect(self.church)
        self.assertEqual(result["installation"]["plugin_root"], str(installed))
        self.assertEqual(json.loads((self.church / ".handbuilt/installation.json").read_text())["plugin_root"], str(installed))


if __name__ == "__main__":
    unittest.main()
