from __future__ import annotations

import json
import subprocess
import sys
import unittest

from tests.helpers import REPO_ROOT


class CrossHostPackagingTest(unittest.TestCase):
    def test_plugin_and_church_folder_support_codex_and_claude(self) -> None:
        manifest = json.loads((REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "handbuilt-church-labs")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["author"]["name"], "Handbuilt")
        self.assertEqual(manifest["interface"]["displayName"], "Handbuilt Church Labs")
        codex_marketplace = json.loads(
            (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(codex_marketplace["name"], "handbuilt-church-labs")
        self.assertEqual(codex_marketplace["plugins"][0]["name"], manifest["name"])
        self.assertEqual(codex_marketplace["plugins"][0]["source"], {"source": "local", "path": "."})
        claude_manifest = json.loads(
            (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(claude_manifest["name"], manifest["name"])
        claude_marketplace = json.loads(
            (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(claude_marketplace["name"], "handbuilt-church-labs")
        self.assertEqual(claude_marketplace["plugins"][0]["source"], "./")
        for skill in ("onboarding", "bulletin", "sermon-research"):
            canonical = f"skills/{skill}/SKILL.md"
            for host in (".agents", ".claude"):
                pointer = REPO_ROOT / host / "skills" / skill / "SKILL.md"
                self.assertTrue(pointer.is_file())
                pointer_text = pointer.read_text(encoding="utf-8")
                self.assertIn(canonical, pointer_text)
                self.assertLessEqual(len(pointer_text.splitlines()), 10)
        church = REPO_ROOT / "scaffold" / "church-folder"
        self.assertTrue((church / "AGENTS.md").is_file())
        self.assertTrue((church / "CLAUDE.md").is_file())
        self.assertFalse((church / "voice").exists())
        self.assertFalse((REPO_ROOT / "exemplar").exists())
        church_config = (church / "church.yaml").read_text(encoding="utf-8")
        self.assertNotIn("labs_location", church_config)
        self.assertNotIn("calibrate_from_latest_approved_brief", church_config)
        self.assertIn("selection_mode:", church_config)
        for research_field in (
            "research_preferences:",
            "priority_voices:",
            "preferred_resources:",
            "voices_to_avoid:",
            "language_depth:",
            "human_sciences:",
            "contemporary_context:",
            "additional_domain:",
        ):
            self.assertIn(research_field, church_config)
        sermon_skill = (
            REPO_ROOT / "skills" / "sermon-research" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("sermon.selection_mode", sermon_skill)
        self.assertIn("pastor_selected", sermon_skill)
        self.assertIn("two independent", sermon_skill)
        self.assertIn("sermon.research_preferences", sermon_skill)
        default_brief_template = (
            REPO_ROOT
            / "skills"
            / "sermon-research"
            / "references"
            / "research-brief-template.md"
        )
        church_brief_template = church / "sermons" / "research-brief-template.md"
        self.assertTrue(default_brief_template.is_file())
        self.assertFalse(church_brief_template.exists())
        self.assertFalse((REPO_ROOT / "specs").exists())
        self.assertFalse((REPO_ROOT / "test-runs").exists())
        quickstart = (REPO_ROOT / "handbook" / "quickstart.md").read_text(encoding="utf-8")
        for host_name in ("Codex", "Claude Code", "Claude Cowork"):
            self.assertIn(host_name, quickstart)
        for artifact in ("readings.md", "research-brief.md"):
            self.assertIn(artifact, quickstart)
        self.assertNotIn("sermon-draft.md", quickstart)
        faq = (REPO_ROOT / "handbook" / "faq.md").read_text(encoding="utf-8")
        self.assertIn("hidden sermon receipts", faq)
        self.assertIn("research_complete", faq)
        self.assertIn("optional Monday automation", faq)

    def test_rehearsal_output_is_blocked_inside_public_repository(self) -> None:
        target = REPO_ROOT / "generated-rehearsal"
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tests" / "run_workflow_rehearsal.py"),
                "--output",
                str(target),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the public repository", result.stdout)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
