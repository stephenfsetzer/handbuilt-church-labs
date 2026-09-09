from __future__ import annotations

import json
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
    reading_selection,
    reading_sources,
    readings_content,
    research_brief,
    research_metadata,
)


sys.path.insert(0, str(REPO_ROOT / "skills" / "sermon-research"))
from sermon_workflow import orient, record  # noqa: E402


class SermonQualityContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.church = make_church(Path(self.temporary.name))
        self.target_date = "2026-09-20"

    def _record_readings(self) -> None:
        result = record(
            self.church,
            self.target_date,
            "readings",
            readings_content(),
            reading_metadata(),
        )
        self.assertEqual(result["status"], "recorded")

    def test_four_consecutive_synthetic_sundays_record_verified_readings(self) -> None:
        fixtures = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "sermon_sundays.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(fixtures), 4)
        for fixture in fixtures:
            selection = reading_selection()
            selection.update({
                "service_date": fixture["date"],
                "occasion": fixture["occasion"],
                "year": fixture["year"],
                "track": fixture["track"],
                "optional_verses": fixture["optional_verses"],
            })
            selection["readings"] = dict(selection["readings"])
            selection["readings"]["gospel"] = fixture["gospel"]
            result = record(
                self.church,
                fixture["date"],
                "readings",
                readings_content(selection=selection),
                {"selection": selection, "sources": reading_sources(selection)},
            )
            self.assertEqual(result["status"], "recorded")
            self.assertEqual(orient(self.church, fixture["date"])["workflow_state"], "needs_research")

    def test_search_snippet_cannot_be_research_evidence(self) -> None:
        self._record_readings()
        metadata = research_metadata()
        metadata["sources"][0]["access_result"] = "snippet"
        result = record(self.church, self.target_date, "research", research_brief(), metadata)
        self.assertEqual(result["errors"][0]["code"], "unverified_sources")

    def test_short_heading_only_research_is_blocked(self) -> None:
        self._record_readings()
        short = "\n".join(research_brief().splitlines()[:70])
        short += "\n\n## Questions for reflection\n\nWhat matters?"
        result = record(self.church, self.target_date, "research", short, research_metadata())
        self.assertIn(
            result["errors"][0]["code"],
            {"invalid_research_shape", "reflection_stop_violated", "insufficient_citations", "research_too_short"},
        )

    def test_interpretive_conversations_require_live_questions(self) -> None:
        self._record_readings()
        no_questions = research_brief().replace(
            "### What does the passage ask a disciple to surrender?\n\n",
            "",
        ).replace(
            "### How do judgment and promise remain together?\n\n",
            "",
        )
        result = record(self.church, self.target_date, "research", no_questions, research_metadata())
        self.assertEqual(result["errors"][0]["code"], "invalid_research_organization")

        named_voice = research_brief().replace(
            "### What does the passage ask a disciple to surrender?",
            "### John Example",
        )
        result = record(self.church, self.target_date, "research", named_voice, research_metadata())
        self.assertEqual(result["errors"][0]["code"], "invalid_research_organization")

    def test_visible_guardrails_are_retired(self) -> None:
        self._record_readings()
        brief = research_brief().replace(
            "## References",
            "## Interpretive Guardrails\n\nThis section is retired.\n\n## References",
        )
        result = record(self.church, self.target_date, "research", brief, research_metadata())
        self.assertEqual(result["errors"][0]["code"], "invalid_research_organization")

    def test_visible_scholarship_account_is_retired(self) -> None:
        self._record_readings()
        brief = research_brief().replace(
            "## References",
            "## Scholarship Account\n\nThe source ledger preserves this detail.\n\n## References",
        )
        result = record(self.church, self.target_date, "research", brief, research_metadata())
        self.assertEqual(result["errors"][0]["code"], "invalid_research_organization")

    def test_retired_duplicate_interpretive_sections_are_blocked(self) -> None:
        self._record_readings()
        brief = research_brief().replace(
            "## Contemporary Convergence",
            "## Theological Voices\n\nDuplicate material.\n\n## Contemporary Convergence",
        )
        result = record(self.church, self.target_date, "research", brief, research_metadata())
        self.assertEqual(result["errors"][0]["code"], "invalid_research_organization")

    def test_local_claim_in_research_is_blocked(self) -> None:
        self._record_readings()
        brief = research_brief().replace(
            "## Pastoral Applications",
            "## Pastoral Applications\n\nThis congregation faces this exact issue every week.",
        )
        result = record(self.church, self.target_date, "research", brief, research_metadata())
        self.assertEqual(result["errors"][0]["code"], "research_localization")

    def test_first_canonical_readings_file_can_be_adopted(self) -> None:
        sermon_dir = self.church / "sermons" / self.target_date
        sermon_dir.mkdir(parents=True)
        canonical = sermon_dir / "readings.md"
        canonical.write_text(readings_content().rstrip(), encoding="utf-8")
        result = record(
            self.church,
            self.target_date,
            "readings",
            canonical.read_text(encoding="utf-8"),
            reading_metadata(),
        )
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(orient(self.church, self.target_date)["workflow_state"], "needs_research")

    def test_reading_sources_must_agree_on_normalized_selection(self) -> None:
        metadata = reading_metadata()
        observed = dict(metadata["sources"][1]["observed_selection"])
        observed["readings"] = dict(observed["readings"])
        observed["readings"]["gospel"] = "Contradictory Gospel 9:9"
        metadata["sources"][1]["observed_selection"] = observed
        result = record(self.church, self.target_date, "readings", readings_content(), metadata)
        self.assertEqual(result["errors"][0]["code"], "reading_source_disagreement")

    def test_visible_readings_must_match_normalized_selection(self) -> None:
        content = readings_content().replace("Test Gospel 3:1-5", "Different Gospel 9:9")
        result = record(self.church, self.target_date, "readings", content, reading_metadata())
        self.assertEqual(result["errors"][0]["code"], "reading_content_mismatch")

    def test_reading_selection_date_and_policy_must_match_request_and_config(self) -> None:
        selection = reading_selection()
        selection["service_date"] = "2027-01-01"
        selection["track"] = "Track 1"
        result = record(
            self.church,
            self.target_date,
            "readings",
            readings_content(selection=selection),
            {"selection": selection, "sources": reading_sources(selection)},
        )
        self.assertEqual(result["errors"][0]["code"], "reading_selection_mismatch")

        selection = reading_selection()
        selection["track"] = "Track 1"
        result = record(
            self.church,
            self.target_date,
            "readings",
            readings_content(selection=selection),
            {"selection": selection, "sources": reading_sources(selection)},
        )
        self.assertEqual(result["errors"][0]["code"], "reading_policy_mismatch")

    def test_research_ledger_requires_valid_retrieval_evidence(self) -> None:
        self._record_readings()
        metadata = research_metadata()
        metadata["sources"][0]["retrieved_at"] = "never"
        result = record(self.church, self.target_date, "research", research_brief(), metadata)
        self.assertEqual(result["errors"][0]["code"], "invalid_timestamp")

    def test_research_target_must_match_verified_readings(self) -> None:
        self._record_readings()
        metadata = research_metadata()
        metadata["research_target"]["citation"] = "Different Gospel 9:9"
        result = record(self.church, self.target_date, "research", research_brief(), metadata)
        self.assertEqual(result["errors"][0]["code"], "research_target_mismatch")

    def test_pastor_selected_research_cannot_claim_lectionary_context(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "false-context")
        record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            pastor_selected_reading_metadata(),
        )
        content = research_brief(
            citation="Test Gospel 4:1-8",
            selection_mode="pastor_selected",
        ).replace(
            "**Selection provenance:** Pastor confirmed for this service",
            "**Lectionary:** RCL, Year A\n**Track:** Track 2\n"
            "**Selection provenance:** Pastor confirmed for this service",
        )
        result = record(
            church,
            self.target_date,
            "research",
            content,
            pastor_selected_research_metadata(),
        )
        self.assertEqual(result["errors"][0]["code"], "false_lectionary_context")

    def test_pastor_selected_research_keeps_text_verification_out_of_brief(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "internal-verification")
        record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            pastor_selected_reading_metadata(),
        )
        content = research_brief(
            citation="Test Gospel 4:1-8",
            selection_mode="pastor_selected",
        ).replace(
            "**Selection provenance:** Pastor confirmed for this service",
            "**Selection provenance:** Pastor confirmed for this service\n"
            "**Text verification:** https://bible.invalid/test-gospel-4",
        )
        result = record(
            church,
            self.target_date,
            "research",
            content,
            pastor_selected_research_metadata(),
        )
        self.assertEqual(result["errors"][0]["code"], "invalid_research_header")

    def test_missing_or_mismatched_research_focus_blocks_recording(self) -> None:
        config = self.church / "church.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("  primary_text: gospel", '  primary_text: ""'),
            encoding="utf-8",
        )
        self.assertIsNone(orient(self.church, self.target_date)["research_focus"])
        result = record(self.church, self.target_date, "readings", readings_content(), reading_metadata())
        self.assertEqual(result["errors"][0]["code"], "research_focus_missing")

        config.write_text(
            config.read_text(encoding="utf-8").replace('  primary_text: ""', "  primary_text: gospel"),
            encoding="utf-8",
        )
        content = readings_content().replace(
            "**Primary research text:** Gospel, Test Gospel 3:1-5",
            "**Primary research text:** First, Test Book 1:1-3",
        )
        result = record(self.church, self.target_date, "readings", content, reading_metadata())
        self.assertEqual(result["errors"][0]["code"], "reading_content_mismatch")

    def test_scheduled_research_cannot_use_a_weekly_override(self) -> None:
        record(
            self.church,
            self.target_date,
            "readings",
            readings_content(),
            reading_metadata(),
            mode="scheduled",
        )
        metadata = research_metadata()
        metadata["research_target"] = {
            "role": "first",
            "citation": "Test Book 1:1-3",
            "selection_basis": "pastor_override",
        }
        result = record(
            self.church,
            self.target_date,
            "research",
            research_brief().replace("**Text:** Test Gospel 3:1-5", "**Text:** Test Book 1:1-3"),
            metadata,
            mode="scheduled",
        )
        self.assertEqual(result["errors"][0]["code"], "scheduled_research_focus_required")

    def test_config_change_invalidates_only_active_research_chain(self) -> None:
        self._record_readings()
        record(
            self.church,
            self.target_date,
            "research",
            research_brief(),
            research_metadata(),
        )
        config = self.church / "church.yaml"
        config.write_text(config.read_text(encoding="utf-8") + "\n# changed track policy\n", encoding="utf-8")
        state = orient(self.church, self.target_date)
        self.assertEqual(state["workflow_state"], "needs_readings")
        self.assertEqual(state["stage_files"]["readings"]["status"], "stale")
        self.assertEqual(state["stage_files"]["research"]["status"], "stale")

    def test_legacy_lectionary_profile_keeps_schema_three_receipts_valid(self) -> None:
        config = self.church / "church.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("  selection_mode: lectionary\n", ""),
            encoding="utf-8",
        )
        readings = record(
            self.church,
            self.target_date,
            "readings",
            readings_content(),
            reading_metadata(),
        )
        self.assertEqual(readings["status"], "recorded")
        receipt = json.loads(Path(readings["receipt"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], 3)
        state = orient(self.church, self.target_date)
        self.assertEqual(state["selection_mode"], "lectionary")
        self.assertEqual(state["stage_files"]["readings"]["status"], "verified")

    def test_malformed_receipt_is_ignored_without_advancing(self) -> None:
        sermon_dir = self.church / "sermons" / self.target_date
        receipt_dir = sermon_dir / ".receipts"
        receipt_dir.mkdir(parents=True)
        (sermon_dir / "readings.md").write_text(readings_content(), encoding="utf-8")
        (receipt_dir / "malformed.json").write_text(
            json.dumps({"schema_version": 3, "stage": "readings", "artifact": [], "validation": []}),
            encoding="utf-8",
        )
        state = orient(self.church, self.target_date)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["workflow_state"], "needs_readings")


if __name__ == "__main__":
    unittest.main()
