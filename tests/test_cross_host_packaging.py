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
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["author"]["name"], "Handbuilt")
        self.assertEqual(manifest["interface"]["displayName"], "Handbuilt Church Labs")
        codex_marketplace = json.loads(
            (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(codex_marketplace["name"], "handbuilt-church-labs")
        self.assertEqual(codex_marketplace["plugins"][0]["name"], manifest["name"])
        codex_entry = codex_marketplace["plugins"][0]
        self.assertEqual(codex_entry["version"], manifest["version"])
        self.assertEqual(codex_entry["source"], {"source": "local", "path": "./"})
        self.assertEqual(
            codex_entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        self.assertEqual(codex_entry["category"], "Productivity")
        claude_manifest = json.loads(
            (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(claude_manifest["name"], manifest["name"])
        self.assertEqual(claude_manifest["version"], manifest["version"])
        claude_marketplace = json.loads(
            (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(claude_marketplace["name"], "handbuilt-church-labs")
        claude_entry = claude_marketplace["plugins"][0]
        self.assertEqual(claude_entry["name"], claude_manifest["name"])
        self.assertEqual(claude_entry["version"], claude_manifest["version"])
        self.assertEqual(claude_entry["source"], "./")
        self.assertEqual(claude_entry["author"], claude_manifest["author"])
        self.assertEqual(claude_entry["homepage"], "https://github.com/stephenfsetzer/handbuilt-church-labs")
        self.assertEqual(claude_entry["category"], "productivity")
        self.assertIsInstance(claude_entry["keywords"], list)
        self.assertTrue(
            claude_entry["keywords"]
            and all(isinstance(keyword, str) and keyword for keyword in claude_entry["keywords"])
        )
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
