from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.helpers import (
    REPO_ROOT,
    make_church,
    make_nonlectionary_church,
    pastor_selected_reading_metadata,
    pastor_selected_readings_content,
    pastor_selected_research_metadata,
    reading_metadata,
    reading_sources,
    readings_content,
    research_brief,
    research_metadata,
)


sys.path.insert(0, str(REPO_ROOT / "skills" / "sermon-research"))
from sermon_workflow import orient, record  # noqa: E402


class SermonWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.church = make_church(Path(self.temporary.name))
        self.target_date = "2026-09-20"

    def _record_research(self, church: Path | None = None) -> None:
        church = church or self.church
        readings = record(
            church,
            self.target_date,
            "readings",
            readings_content(),
            reading_metadata(),
        )
        self.assertEqual(readings["status"], "recorded")
        research = record(
            church,
            self.target_date,
            "research",
            research_brief(),
            research_metadata(),
        )
        self.assertEqual(research["status"], "recorded")

    def test_complete_lifecycle_ends_at_research_in_both_modes(self) -> None:
        self.assertEqual(orient(self.church, self.target_date)["workflow_state"], "needs_readings")

        blocked = record(
            self.church,
            self.target_date,
            "research",
            research_brief(),
            research_metadata(),
        )
        self.assertEqual(blocked["errors"][0]["code"], "stage_out_of_order")

        self._record_research()
        for mode in ("manual", "scheduled"):
            state = orient(self.church, self.target_date, mode=mode)
            self.assertEqual(state["workflow_state"], "research_complete")
            self.assertEqual(state["next_actions"], [])
            self.assertEqual(state["stop_after"], "research")
            self.assertEqual(set(state["stage_files"]), {"readings", "research"})

    def test_retired_stages_are_rejected(self) -> None:
        for stage in ("reflections", "draft", "review"):
            result = record(self.church, self.target_date, stage, "retired", {})
            self.assertEqual(result["errors"][0]["code"], "unknown_stage")

    def test_existing_pastor_files_and_historical_receipts_are_preserved_and_ignored(self) -> None:
        sermon_dir = self.church / "sermons" / self.target_date
        receipt_dir = sermon_dir / ".receipts"
        receipt_dir.mkdir(parents=True)
        reflection = sermon_dir / "reflections.md"
        draft = sermon_dir / "sermon-draft.md"
        historical = receipt_dir / "draft-historical.json"
        reflection.write_text("Pastor-owned reflection\n", encoding="utf-8")
        draft.write_text("Pastor-owned draft\n", encoding="utf-8")
        historical.write_text(json.dumps({"stage": "draft", "historical": True}), encoding="utf-8")

        self._record_research()
        state = orient(self.church, self.target_date)

        self.assertEqual(state["workflow_state"], "research_complete")
        self.assertEqual(reflection.read_text(encoding="utf-8"), "Pastor-owned reflection\n")
        self.assertEqual(draft.read_text(encoding="utf-8"), "Pastor-owned draft\n")
        self.assertTrue(historical.is_file())
        self.assertNotIn("reflections", state["stage_files"])
        self.assertNotIn("draft", state["stage_files"])

    def test_readings_require_two_distinct_verified_hosts(self) -> None:
        sources = reading_sources()
        sources[1] = dict(sources[0])
        blocked = record(
            self.church,
            self.target_date,
            "readings",
            readings_content(),
            {"selection": reading_metadata()["selection"], "sources": sources},
        )
        self.assertEqual(blocked["errors"][0]["code"], "duplicate_source_host")

    def test_pastor_selected_passage_enters_the_same_research_workflow(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "nonlectionary")
        readings = record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            pastor_selected_reading_metadata(),
        )
        self.assertEqual(readings["workflow_state"], "needs_research")
        research = record(
            church,
            self.target_date,
            "research",
            research_brief(citation="Test Gospel 4:1-8", selection_mode="pastor_selected"),
            pastor_selected_research_metadata(),
            mode="scheduled",
        )
        self.assertEqual(research["workflow_state"], "research_complete")

    def test_scheduled_empty_nonlectionary_week_waits_for_the_pastor(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "empty")
        state = orient(church, self.target_date, mode="scheduled")
        self.assertEqual(state["workflow_state"], "awaiting_passage")
        self.assertEqual(state["next_actions"], [])
        self.assertEqual(state["selection_mode"], "pastor_selected")

    def test_selection_modes_reject_cross_branch_reading_roles(self) -> None:
        lectionary = reading_metadata()
        lectionary["selection"]["readings"]["selected"] = "Test Gospel 4:1-8"
        lectionary["sources"] = reading_sources(lectionary["selection"])
        blocked_lectionary = record(
            self.church,
            self.target_date,
            "readings",
            readings_content(),
            lectionary,
        )
        self.assertEqual(blocked_lectionary["errors"][0]["code"], "invalid_reading_roles")

        church = make_nonlectionary_church(Path(self.temporary.name) / "cross-branch")
        selected = pastor_selected_reading_metadata()
        selected["selection"]["readings"]["gospel"] = "Test Gospel 3:1-5"
        blocked_selected = record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            selected,
        )
        self.assertEqual(blocked_selected["errors"][0]["code"], "invalid_reading_roles")

    def test_pastor_selected_passage_requires_date_bound_confirmation(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "unconfirmed")
        metadata = pastor_selected_reading_metadata()
        metadata.pop("selection_confirmation")
        blocked = record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            metadata,
        )
        self.assertEqual(blocked["errors"][0]["code"], "pastor_selection_unconfirmed")

        metadata = pastor_selected_reading_metadata()
        metadata["selection_confirmation"]["service_date"] = "2026-09-27"
        blocked = record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            metadata,
        )
        self.assertEqual(blocked["errors"][0]["code"], "pastor_selection_date_mismatch")

    def test_scheduled_run_cannot_choose_a_pastor_selected_passage(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "scheduled")
        blocked = record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            pastor_selected_reading_metadata(),
            mode="scheduled",
        )
        self.assertEqual(blocked["errors"][0]["code"], "scheduled_selection_required")

    def test_selected_research_target_must_match_confirmed_passage_and_basis(self) -> None:
        church = make_nonlectionary_church(Path(self.temporary.name) / "target")
        record(
            church,
            self.target_date,
            "readings",
            pastor_selected_readings_content(),
            pastor_selected_reading_metadata(),
        )
        metadata = pastor_selected_research_metadata()
        metadata["research_target"]["citation"] = "Test Gospel 4:1-7"
        blocked = record(
            church,
            self.target_date,
            "research",
            research_brief(citation="Test Gospel 4:1-7", selection_mode="pastor_selected"),
            metadata,
        )
        self.assertEqual(blocked["errors"][0]["code"], "research_target_mismatch")

        metadata = pastor_selected_research_metadata()
        metadata["research_target"]["selection_basis"] = "church_profile"
        blocked = record(
            church,
            self.target_date,
            "research",
            research_brief(citation="Test Gospel 4:1-8", selection_mode="pastor_selected"),
            metadata,
        )
        self.assertEqual(blocked["errors"][0]["code"], "invalid_research_target")

    def test_replacing_readings_makes_research_stale(self) -> None:
        self._record_research()
        replacement = record(
            self.church,
            self.target_date,
            "readings",
            readings_content("two"),
            reading_metadata(),
            replace=True,
        )
        self.assertEqual(replacement["workflow_state"], "needs_research")
        state = orient(self.church, self.target_date)
        self.assertEqual(state["stage_files"]["readings"]["status"], "verified")
        self.assertEqual(state["stage_files"]["research"]["status"], "stale")

    def test_directory_footer_and_layout_changes_do_not_stale_verified_sermon_stages(self) -> None:
        self._record_research()
        config_path = self.church / "church.yaml"
        text = config_path.read_text(encoding="utf-8")
        text += (
            "\nleadership:\n"
            "  clergy_and_staff:\n"
            "    - name: The Rev. New Associate\n"
            "      role: Associate Rector\n"
            "bulletin:\n"
            "  template: modern\n"
            "  footer:\n"
            "    contact_name: New Contact\n"
        )
        config_path.write_text(text, encoding="utf-8")
        state = orient(self.church, self.target_date)
        self.assertEqual(state["stage_files"]["readings"]["status"], "verified")
        self.assertEqual(state["stage_files"]["research"]["status"], "verified")
        self.assertEqual(state["workflow_state"], "research_complete")

    def test_reformatted_church_yaml_with_unchanged_values_does_not_stale_stages(self) -> None:
        self._record_research()
        config_path = self.church / "church.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        # Reordered keys and an inline comment; every value is unchanged.
        reformatted = "# reformatted for the reliability regression\n" + yaml.safe_dump(
            dict(reversed(list(config.items()))), sort_keys=False
        )
        config_path.write_text(reformatted, encoding="utf-8")
        state = orient(self.church, self.target_date)
        self.assertEqual(state["stage_files"]["readings"]["status"], "verified")
        self.assertEqual(state["stage_files"]["research"]["status"], "verified")

    def test_translation_change_stales_readings_and_cascades_to_research(self) -> None:
        self._record_research()
        config_path = self.church / "church.yaml"
        text = config_path.read_text(encoding="utf-8").replace(
            "translation: Synthetic Test Translation",
            "translation: Revised Synthetic Translation",
        )
        config_path.write_text(text, encoding="utf-8")
        state = orient(self.church, self.target_date)
        self.assertEqual(state["stage_files"]["readings"]["status"], "stale")
        self.assertEqual(state["stage_files"]["research"]["status"], "stale")
        self.assertEqual(state["workflow_state"], "needs_readings")

    def test_research_preference_change_stales_only_research(self) -> None:
        self._record_research()
        config_path = self.church / "church.yaml"
        text = config_path.read_text(encoding="utf-8").replace(
            "language_depth: plain",
            "language_depth: technical",
        )
        config_path.write_text(text, encoding="utf-8")
        state = orient(self.church, self.target_date)
        self.assertEqual(state["stage_files"]["readings"]["status"], "verified")
        self.assertEqual(state["stage_files"]["research"]["status"], "stale")
        self.assertEqual(state["workflow_state"], "needs_research")

    def test_typed_pass_text_does_not_govern_state(self) -> None:
        sermon_dir = self.church / "sermons" / self.target_date
        sermon_dir.mkdir(parents=True)
        (sermon_dir / "readings.md").write_text(readings_content() + "\nPASS\n", encoding="utf-8")
        receipt_dir = sermon_dir / ".receipts"
        receipt_dir.mkdir()
        (receipt_dir / "fake.json").write_text(
            json.dumps({"stage": "readings", "verdict": "PASS"}),
            encoding="utf-8",
        )
        state = orient(self.church, self.target_date)
        self.assertEqual(state["workflow_state"], "needs_readings")
        self.assertEqual(state["stage_files"]["readings"]["status"], "modified")


if __name__ == "__main__":
    unittest.main()
