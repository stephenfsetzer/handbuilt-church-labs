"""Regression tests for standing-readiness and sermon receipt reliability.

Covers two acceptance-visible fixes together:

* church_setup.status() reports standing worship completeness without
  requiring a weekly service-variant choice that only exists at production
  time (see tests/test_worship_resolution.py for the resolver-level tests).
* sermon_workflow receipts fingerprint only the church.yaml fields that
  actually govern each stage, so roster/footer/layout edits do not stale a
  verified reading or research stage, while a real semantic change does, and
  an old whole-file receipt fails closed instead of being mistaken as fresh.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "skills" / "onboarding" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "sermon-research"))

import church_setup  # noqa: E402
from sermon_workflow import orient, record  # noqa: E402
from tests.helpers import make_church, reading_metadata, readings_content, research_brief, research_metadata


class ReliabilityStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.church = make_church(Path(self.temporary.name))
        self.target_date = "2026-09-20"

    def test_legacy_whole_file_dependency_key_fails_closed_not_falsely_verified(self) -> None:
        """A receipt recorded before fingerprint narrowing kept its fields
        under a "church_config" key over a whole-file hash. That key no
        longer matches the new narrower "sermon_config" fingerprint, so
        orient() must fail closed and report the stage stale, not crash and
        not report a false verified."""
        recorded = record(self.church, self.target_date, "readings", readings_content(), reading_metadata())
        self.assertEqual(recorded["status"], "recorded")
        receipt_path = Path(recorded["receipt"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        renamed = False
        for dependency in receipt["dependencies"]:
            if dependency.get("key") == "sermon_config":
                dependency["key"] = "church_config"
                renamed = True
        self.assertTrue(renamed, "fixture receipt did not carry the expected sermon_config dependency")
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        state = orient(self.church, self.target_date)
        self.assertEqual(state["stage_files"]["readings"]["status"], "stale")
        self.assertEqual(state["workflow_state"], "needs_readings")

    def test_directory_edit_after_sermon_completion_leaves_research_recognized(self) -> None:
        """Ties church_setup.status()'s first-result recognition to the
        sermon fingerprint fix: a later roster edit must not make a
        completed research_complete sermon disappear from first_results."""
        record(self.church, self.target_date, "readings", readings_content(), reading_metadata())
        record(self.church, self.target_date, "research", research_brief(), research_metadata())
        before = church_setup.status(self.church)
        self.assertTrue(any(item["kind"] == "sermon_research" for item in before["first_results"]))

        church_setup.update_standing(self.church, {"leadership": {"clergy_and_staff": [
            {"name": "The Rev. New Associate", "role": "Associate Rector"},
        ]}})

        after = church_setup.status(self.church)
        self.assertTrue(any(item["kind"] == "sermon_research" for item in after["first_results"]))


if __name__ == "__main__":
    unittest.main()
