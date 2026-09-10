from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from tests.helpers import (
    REPO_ROOT,
    make_church,
    reading_metadata,
    readings_content,
    research_brief,
    research_metadata,
)

sys.path.insert(0, str(REPO_ROOT / "skills" / "sermon-research"))
from sermon_workflow import record  # noqa: E402


class ResearchReceiptTimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.church = make_church(Path(self.temporary.name))
        self.target_date = "2026-09-20"

    def _record_readings(self, metadata: dict) -> dict:
        return record(self.church, self.target_date, "readings", readings_content(), metadata)

    def _record_research(self, metadata: dict) -> dict:
        self.assertEqual(self._record_readings(reading_metadata())["status"], "recorded")
        return record(self.church, self.target_date, "research", research_brief(), metadata)

    # -- readings stage: retrieved_at is optional -----------------------------

    def test_omitted_retrieved_at_is_accepted(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        for source in metadata["sources"]:
            del source["retrieved_at"]
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")

    def test_null_retrieved_at_is_accepted(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        metadata["sources"][0]["retrieved_at"] = None
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")

    def test_valid_past_retrieved_at_is_accepted(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        metadata["sources"][0]["retrieved_at"] = past
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")

    def test_z_suffixed_past_retrieved_at_is_accepted(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata["sources"][0]["retrieved_at"] = past
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")

    def test_retrieved_at_within_clock_skew_tolerance_is_accepted(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        soon = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        metadata["sources"][0]["retrieved_at"] = soon
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")

    # -- rejections -------------------------------------------------------------

    def test_future_retrieved_at_is_rejected_with_actionable_error(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        future = (datetime.now(timezone.utc) + timedelta(hours=13)).isoformat()
        metadata["sources"][0]["retrieved_at"] = future
        result = self._record_readings(metadata)
        error = result["errors"][0]
        self.assertEqual(error["code"], "invalid_timestamp")
        self.assertIn("future", error["message"])
        self.assertIn("omit", error["message"].lower())

    def test_naive_retrieved_at_is_rejected(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        metadata["sources"][0]["retrieved_at"] = "2026-08-26T12:00:00"
        result = self._record_readings(metadata)
        error = result["errors"][0]
        self.assertEqual(error["code"], "invalid_timestamp")
        self.assertIn("timezone", error["message"])

    def test_malformed_retrieved_at_is_rejected(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        metadata["sources"][0]["retrieved_at"] = "not a timestamp"
        result = self._record_readings(metadata)
        error = result["errors"][0]
        self.assertEqual(error["code"], "invalid_timestamp")
        self.assertIn("omit", error["message"].lower())

    def test_blank_string_retrieved_at_is_treated_as_omitted(self) -> None:
        metadata = copy.deepcopy(reading_metadata())
        metadata["sources"][0]["retrieved_at"] = "   "
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")

    # -- research stage: same rule applies ---------------------------------------

    def test_research_sources_also_accept_omitted_retrieved_at(self) -> None:
        metadata = copy.deepcopy(research_metadata())
        for source in metadata["sources"]:
            del source["retrieved_at"]
        result = self._record_research(metadata)
        self.assertEqual(result["status"], "recorded")

    def test_research_sources_reject_future_retrieved_at(self) -> None:
        metadata = copy.deepcopy(research_metadata())
        future = (datetime.now(timezone.utc) + timedelta(hours=13)).isoformat()
        metadata["sources"][0]["retrieved_at"] = future
        result = self._record_research(metadata)
        self.assertEqual(result["errors"][0]["code"], "invalid_timestamp")

    # -- created_at stays the machine's own clock record, independent of callers --

    def test_receipt_created_at_is_independent_of_supplied_retrieved_at(self) -> None:
        before = datetime.now(timezone.utc)
        metadata = copy.deepcopy(reading_metadata())
        for source in metadata["sources"]:
            del source["retrieved_at"]
        result = self._record_readings(metadata)
        self.assertEqual(result["status"], "recorded")
        receipt_path = Path(result["receipt"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(receipt["created_at"])
        after = datetime.now(timezone.utc)
        self.assertIsNotNone(created_at.tzinfo)
        self.assertGreaterEqual(created_at, before - timedelta(seconds=5))
        self.assertLessEqual(created_at, after + timedelta(seconds=5))
        # No source in the recorded metadata supplied a retrieved_at at all;
        # created_at was still generated by the runtime's own clock.
        for source in metadata["sources"]:
            self.assertNotIn("retrieved_at", source)


if __name__ == "__main__":
    unittest.main()
