from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    REPO_ROOT,
    make_church,
    make_nonlectionary_church,
    pastor_selected_reading_metadata,
    pastor_selected_readings_content,
    pastor_selected_research_metadata,
    reading_metadata,
    readings_content,
    research_brief,
    research_metadata,
)


class SermonCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.church = make_church(self.root)
        self.date = "2026-09-20"
        self.cli = REPO_ROOT / "skills" / "sermon-research" / "scripts" / "sermon_workflow.py"

    def _write_text(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def _write_json(self, name: str, content: dict) -> Path:
        return self._write_text(name, json.dumps(content))

    def _run(self, *arguments: str) -> dict:
        result = subprocess.run(
            [sys.executable, str(self.cli), *arguments],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def _record(self, stage: str, content: str, metadata: dict) -> dict:
        content_path = self._write_text(f"{stage}.md", content)
        metadata_path = self._write_json(f"{stage}.json", metadata)
        return self._run(
            "record",
            "--church-folder",
            str(self.church),
            "--date",
            self.date,
            "--stage",
            stage,
            "--content-file",
            str(content_path),
            "--metadata-file",
            str(metadata_path),
        )

    def test_cli_runs_complete_research_lifecycle(self) -> None:
        self._record("readings", readings_content(), reading_metadata())
        research = self._record("research", research_brief(), research_metadata())
        self.assertEqual(research["workflow_state"], "research_complete")
        self.assertEqual(research["next_actions"], [])
        oriented = self._run(
            "orient",
            "--church-folder",
            str(self.church),
            "--date",
            self.date,
        )
        self.assertEqual(oriented["workflow_state"], "research_complete")
        self.assertEqual(set(oriented["stage_files"]), {"readings", "research"})

    def test_cli_supports_manual_selection_then_scheduled_research(self) -> None:
        self.church = make_nonlectionary_church(self.root / "nonlectionary")
        empty = self._run(
            "orient",
            "--church-folder",
            str(self.church),
            "--date",
            self.date,
            "--mode",
            "scheduled",
        )
        self.assertEqual(empty["workflow_state"], "awaiting_passage")
        self.assertEqual(empty["next_actions"], [])
        self._record(
            "readings",
            pastor_selected_readings_content(),
            pastor_selected_reading_metadata(),
        )
        content_path = self._write_text(
            "selected-research.md",
            research_brief(
                citation="Test Gospel 4:1-8",
                selection_mode="pastor_selected",
            ),
        )
        metadata_path = self._write_json(
            "selected-research.json",
            pastor_selected_research_metadata(),
        )
        research = self._run(
            "record",
            "--church-folder",
            str(self.church),
            "--date",
            self.date,
            "--stage",
            "research",
            "--content-file",
            str(content_path),
            "--metadata-file",
            str(metadata_path),
            "--mode",
            "scheduled",
        )
        self.assertEqual(research["workflow_state"], "research_complete")


if __name__ == "__main__":
    unittest.main()
