from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tools import check_version_bump, claude_updates


class VersionBumpTest(unittest.TestCase):
    def test_shipped_paths_need_a_version_and_docs_do_not(self) -> None:
        changed = [
            "skills/sermon-video/SKILL.md",
            "tools/church_workflow.py",
            ".claude/skills/sermon-video/SKILL.md",
            "requirements.txt",
            "README.md",
            "INSTALL.md",
            "tests/test_sermon_video.py",
            ".github/workflows/publication.yml",
            ".claude/status/lanes/x.md",
        ]
        self.assertEqual(
            check_version_bump.shipped(changed),
            [".claude/skills/sermon-video/SKILL.md", "requirements.txt",
             "skills/sermon-video/SKILL.md", "tools/church_workflow.py"],
        )

    def test_versions_compare_numerically(self) -> None:
        self.assertGreater(check_version_bump.parse_version("0.8.10"), check_version_bump.parse_version("0.8.9"))
        with self.assertRaises(ValueError):
            check_version_bump.parse_version("0.8")

    def test_check_against_a_real_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*arguments: str) -> None:
                subprocess.run(["git", "-C", folder, *arguments], check=True, capture_output=True)

            def manifest(version: str) -> None:
                (root / ".claude-plugin").mkdir(exist_ok=True)
                (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))

            git("init", "-q", "-b", "main")
            git("config", "user.email", "test@example.com")
            git("config", "user.name", "Test")
            manifest("1.0.0")
            (root / "skills").mkdir()
            (root / "skills" / "a.md").write_text("one")
            git("add", ".")
            git("commit", "-q", "-m", "base")
            git("checkout", "-q", "-b", "change")
            with mock.patch.object(check_version_bump, "ROOT", root):
                (root / "README.md").write_text("docs only")
                git("add", ".")
                git("commit", "-q", "-m", "docs")
                self.assertTrue(check_version_bump.check("main")[0])

                (root / "skills" / "a.md").write_text("two")
                git("add", ".")
                git("commit", "-q", "-m", "skill")
                passed, message = check_version_bump.check("main")
                self.assertFalse(passed)
                self.assertIn("skills/a.md", message)

                manifest("1.0.1")
                git("add", ".")
                git("commit", "-q", "-m", "bump")
                self.assertTrue(check_version_bump.check("main")[0])


class ClaudeUpdatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.directory = Path(self.folder.name)
        self.settings = self.directory / "settings.json"

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_enable_merges_into_existing_settings_and_keeps_a_backup(self) -> None:
        original = {
            "theme": "dark",
            "env": {"OTHER": "x"},
            "enabledPlugins": {"other@market": True},
            "extraKnownMarketplaces": {
                "handbuilt-church-labs": {"source": {"source": "git", "url": claude_updates.REPOSITORY_URL}}
            },
        }
        self.settings.write_text(json.dumps(original))
        result = claude_updates.enable(self.directory)
        self.assertEqual(result["status"], "turned_on")
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["theme"], "dark")
        self.assertEqual(saved["env"], {"OTHER": "x", "FORCE_AUTOUPDATE_PLUGINS": "1"})
        self.assertTrue(saved["enabledPlugins"]["other@market"])
        self.assertTrue(saved["enabledPlugins"][claude_updates.PLUGIN_ID])
        entry = saved["extraKnownMarketplaces"]["handbuilt-church-labs"]
        self.assertEqual(entry["source"], original["extraKnownMarketplaces"]["handbuilt-church-labs"]["source"])
        self.assertIs(entry["autoUpdate"], True)
        self.assertEqual(json.loads(Path(result["backup"]).read_text()), original)
        self.assertEqual(claude_updates.enable(self.directory)["status"], "already_on")

    def test_enable_creates_settings_and_respects_a_pastors_disable(self) -> None:
        self.assertEqual(claude_updates.enable(self.directory)["status"], "turned_on")
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["extraKnownMarketplaces"]["handbuilt-church-labs"]["source"]["url"],
                         claude_updates.REPOSITORY_URL)
        saved["enabledPlugins"][claude_updates.PLUGIN_ID] = False
        self.settings.write_text(json.dumps(saved))
        result = claude_updates.enable(self.directory)
        self.assertTrue(result["plugin_disabled"])
        self.assertIs(json.loads(self.settings.read_text())["enabledPlugins"][claude_updates.PLUGIN_ID], False)

    def test_enable_refuses_invalid_settings_without_writing(self) -> None:
        self.settings.write_text("{not json")
        with self.assertRaises(claude_updates.SettingsError):
            claude_updates.enable(self.directory)
        self.assertEqual(self.settings.read_text(), "{not json")
        self.assertEqual(list(self.directory.iterdir()), [self.settings])

    def test_status_names_each_gap_and_reports_current(self) -> None:
        record = self.directory / "plugins" / "installed_plugins.json"
        record.parent.mkdir()
        record.write_text(json.dumps({"version": 2, "plugins": {claude_updates.PLUGIN_ID: [{"version": "0.8.7"}]}}))
        with mock.patch.object(claude_updates, "_latest_release", return_value=("0.8.8", None)):
            before = claude_updates.status(self.directory)
            self.assertEqual(before["status"], "needs_attention")
            self.assertIn("Automatic updates are off for the Handbuilt marketplace", before["message"])
            self.assertIn("FORCE_AUTOUPDATE_PLUGINS is not set", before["message"])
            self.assertIn("0.8.7 is installed and 0.8.8", before["message"])
            claude_updates.enable(self.directory)
            record.write_text(json.dumps({"version": 2, "plugins": {claude_updates.PLUGIN_ID: [{"version": "0.8.8"}]}}))
            after = claude_updates.status(self.directory)
        self.assertEqual(after["status"], "current")
        self.assertTrue(after["auto_update_on"] and after["desktop_updates_allowed"] and after["plugin_enabled"])
        with mock.patch.object(claude_updates, "_latest_release", return_value=("0.8.7", None)):
            self.assertEqual(claude_updates.status(self.directory)["status"], "current")

    def test_workflow_start_asks_to_turn_updates_on_only_when_needed(self) -> None:
        from tools import church_workflow

        environment = {"CLAUDE_CONFIG_DIR": self.folder.name, "CLAUDECODE": "1"}
        with mock.patch.dict("os.environ", environment):
            self.assertIsNone(church_workflow.claude_update_settings(), "no Claude Code install, nothing to ask")
            record = self.directory / "plugins" / "installed_plugins.json"
            record.parent.mkdir()
            record.write_text(json.dumps({"version": 2, "plugins": {claude_updates.PLUGIN_ID: [{"version": "0.8.8"}]}}))
            note = church_workflow.claude_update_settings()
            self.assertEqual(note["status"], "updates_off")
            self.assertIn("May I turn them on?", note["next_action"])
            self.assertTrue(note["enable_command"][-2].endswith("tools/claude_updates.py"))
            self.assertFalse(self.settings.exists(), "the check asks; it never writes settings")
            claude_updates.enable(self.directory)
            self.assertIsNone(church_workflow.claude_update_settings())
        with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": self.folder.name, "CLAUDECODE": ""}):
            self.assertIsNone(church_workflow.claude_update_settings(), "other hosts are left alone")

    def test_check_command_asks_without_a_church_folder_and_never_blocks(self) -> None:
        record = self.directory / "plugins" / "installed_plugins.json"
        record.parent.mkdir()
        record.write_text(json.dumps({"version": 2, "plugins": {claude_updates.PLUGIN_ID: [{"version": "0.8.8"}]}}))

        def check(claudecode: str) -> tuple[int, dict]:
            output = io.StringIO()
            with mock.patch.dict("os.environ", {"CLAUDECODE": claudecode}), redirect_stdout(output):
                code = claude_updates.main(["check", "--config-dir", str(self.directory)])
            return code, json.loads(output.getvalue())

        code, result = check("1")
        self.assertEqual((code, result["status"]), (0, "updates_off"))
        self.assertIn("May I turn them on?", result["next_action"])
        self.assertFalse(self.settings.exists(), "the check asks; it never writes settings")
        self.assertEqual(check("")[1], {"status": "nothing_to_ask"}, "other hosts are left alone")
        claude_updates.enable(self.directory)
        self.assertEqual(check("1"), (0, {"status": "nothing_to_ask"}))
        self.settings.write_text("{not json")
        code, result = check("1")
        self.assertEqual((code, result["status"]), (0, "settings_unreadable"))

    def test_sermon_video_asks_the_update_question_without_the_launcher(self) -> None:
        skill = (Path(__file__).resolve().parents[1] / "skills/sermon-video/SKILL.md").read_text(encoding="utf-8")
        self.assertIn('"<app-loaded-plugin-root>/tools/claude_updates.py" check', skill)
        self.assertNotIn("church_workflow.py", skill)

    def test_config_dir_follows_claude_config_dir(self) -> None:
        with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": self.folder.name}):
            self.assertEqual(claude_updates.config_dir(), self.directory)


if __name__ == "__main__":
    unittest.main()
