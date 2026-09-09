from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from skills.bulletin.bulletin_production import finalize, orient, produce
from tests.helpers import bulletin_input, make_church


class BulletinWorkflowTest(unittest.TestCase):
    def test_production_is_separate_from_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            before = orient(church, "2026-09-20")
            self.assertEqual(before["status"], "ok")
            self.assertEqual(before["initialization_state"], "first_run")

            production = produce(church, bulletin_input())
            self.assertEqual(production["status"], "ready_for_review", production)
            receipt_path = Path(production["receipt_path"])
            self.assertTrue(receipt_path.is_file())
            self.assertFalse((church / "bulletins" / "bulletin-log.json").exists())

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            hashes = {item["role"]: item["sha256"] for item in receipt["artifacts"]}
            incomplete_approval = finalize(
                receipt_path,
                {
                    "production_run_id": receipt["run_id"],
                    "approved_by": "Test Reviewer",
                },
            )
            self.assertEqual(incomplete_approval["status"], "blocked")
            self.assertFalse((church / "bulletins" / "bulletin-log.json").exists())
            approval = finalize(
                receipt_path,
                {
                    "production_run_id": receipt["run_id"],
                    "approved_by": "Test Reviewer",
                    "reviewed_artifact_hashes": hashes,
                    "note": "Synthetic automated workflow approval",
                },
            )
            self.assertEqual(approval["status"], "approved", approval)
            self.assertTrue(Path(approval["approval_receipt_path"]).is_file())

            after = orient(church, "2026-09-27")
            self.assertEqual(after["initialization_state"], "returning")
            self.assertEqual(after["last_approved_bulletin"]["date"], "2026-09-20")
            self.assertEqual(after["last_approved_bulletin"]["evidence_label"], "approved_bulletin")


if __name__ == "__main__":
    unittest.main()
