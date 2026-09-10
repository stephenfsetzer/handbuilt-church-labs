"""Prove the reference doc's record/verify examples are actually valid.

These tests parse the fenced example blocks out of
skills/sermon-research/references/source-verification.md by their
<!-- example:name --> marker and drive them through the real sermon_workflow
module with synthetic data. If a future edit to the module or the doc makes
an example invalid, one of these tests fails, instead of the gap only
surfacing when a fresh agent hits it cold.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT, make_church, research_brief


sys.path.insert(0, str(REPO_ROOT / "skills" / "sermon-research"))
from sermon_workflow import record  # noqa: E402


DOC_PATH = REPO_ROOT / "skills" / "sermon-research" / "references" / "source-verification.md"


def _extract_example(doc_text: str, name: str) -> str:
    marker = f"<!-- example:{name} -->"
    start = doc_text.index(marker) + len(marker)
    fence_start = doc_text.index("```", start)
    first_newline = doc_text.index("\n", fence_start)
    fence_end = doc_text.index("```", first_newline)
    return doc_text[first_newline + 1 : fence_end].rstrip("\n")


def _configure_church(
    church: Path,
    *,
    selection_mode: str,
    translation: str,
    primary_text: str,
    system: str | None = None,
    track: str | None = None,
    optional_verses: str | None = None,
) -> None:
    """Point a make_church fixture's lectionary/sermon config at the given values.

    Mirrors tests/helpers.make_nonlectionary_church's literal-replace style
    rather than adding a new shared helper.
    """
    config_path = church / "church.yaml"
    text = config_path.read_text(encoding="utf-8")
    if system is not None:
        text = text.replace("  system: RCL", f"  system: {system}")
    if track is not None:
        text = text.replace("  track: Track 2", f"  track: {track}")
    if optional_verses is not None:
        text = text.replace("  optional_verses: appointed", f"  optional_verses: {optional_verses}")
    text = text.replace("  translation: Synthetic Test Translation", f"  translation: {translation}")
    text = text.replace("  selection_mode: lectionary", f"  selection_mode: {selection_mode}")
    text = text.replace("  primary_text: gospel", f"  primary_text: {primary_text}")
    config_path.write_text(text, encoding="utf-8")


class SermonResearchExamplesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = DOC_PATH.read_text(encoding="utf-8")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_doc_has_the_expected_example_markers(self) -> None:
        for name in (
            "lectionary-readings-metadata",
            "lectionary-readings-content",
            "pastor-selected-readings-metadata",
            "pastor-selected-readings-content",
            "research-metadata",
        ):
            self.assertIn(f"<!-- example:{name} -->", self.doc, name)

    def test_lectionary_readings_example_is_valid_and_complete(self) -> None:
        metadata = json.loads(_extract_example(self.doc, "lectionary-readings-metadata"))
        content = _extract_example(self.doc, "lectionary-readings-content")
        selection = metadata["selection"]
        church = make_church(Path(self.temporary.name) / "lectionary-doc-example")
        _configure_church(
            church,
            selection_mode="lectionary",
            translation=selection["translation"],
            primary_text="gospel",
            system=selection["lectionary_system"],
            track=selection["track"],
            optional_verses=selection["optional_verses_policy"],
        )
        result = record(church, selection["service_date"], "readings", content, metadata)
        self.assertEqual(result["status"], "recorded", result)

    def test_pastor_selected_readings_example_is_valid_and_complete(self) -> None:
        metadata = json.loads(_extract_example(self.doc, "pastor-selected-readings-metadata"))
        content = _extract_example(self.doc, "pastor-selected-readings-content")
        selection = metadata["selection"]
        church = make_church(Path(self.temporary.name) / "pastor-selected-doc-example")
        _configure_church(
            church,
            selection_mode="pastor_selected",
            translation=selection["translation"],
            primary_text="selected",
        )
        result = record(church, selection["service_date"], "readings", content, metadata)
        self.assertEqual(result["status"], "recorded", result)

    def test_research_metadata_example_is_valid_against_a_recorded_reading(self) -> None:
        readings_metadata = json.loads(_extract_example(self.doc, "lectionary-readings-metadata"))
        readings_content_text = _extract_example(self.doc, "lectionary-readings-content")
        selection = readings_metadata["selection"]
        church = make_church(Path(self.temporary.name) / "research-doc-example")
        _configure_church(
            church,
            selection_mode="lectionary",
            translation=selection["translation"],
            primary_text="gospel",
            system=selection["lectionary_system"],
            track=selection["track"],
            optional_verses=selection["optional_verses_policy"],
        )
        readings_result = record(
            church, selection["service_date"], "readings", readings_content_text, readings_metadata
        )
        self.assertEqual(readings_result["status"], "recorded", readings_result)

        research_metadata_doc = json.loads(_extract_example(self.doc, "research-metadata"))
        citation = selection["readings"]["gospel"]
        self.assertEqual(research_metadata_doc["research_target"]["citation"], citation)
        body = research_brief(citation=citation, selection_mode="lectionary")
        # The fixture's header uses its own fixed occasion/translation/URLs.
        # Align them to the doc example's own selection and ledger, so the
        # header cross-check and the reference-linking check both pass
        # against this specific example rather than the shared fixture's
        # unrelated defaults.
        header_substitutions = [
            ("**Liturgical setting:** Synthetic Proper", f"**Liturgical setting:** {selection['occasion']}"),
            ("**Translation:** Synthetic Test Translation", f"**Translation:** {selection['translation']}"),
            (
                "**Reading verification:** https://lectionary-a.invalid/2026-09-20 and https://lectionary-b.invalid/2026-09-20",
                "**Reading verification:** {} and {}".format(
                    readings_metadata["sources"][0]["url"], readings_metadata["sources"][1]["url"]
                ),
            ),
        ]
        for old, new in header_substitutions:
            body = body.replace(old, new)
        # Swap the fixture's reference URLs for the doc example's own ledger
        # URLs, so every source in the doc's metadata is actually linked in
        # the brief, exactly as the module requires.
        fixture_urls = [f"https://research-{index}.invalid/source" for index in range(1, 5)]
        doc_urls = [source["url_or_citation"] for source in research_metadata_doc["sources"]]
        for fixture_url, doc_url in zip(fixture_urls, doc_urls):
            body = body.replace(fixture_url, doc_url)
        research_result = record(church, selection["service_date"], "research", body, research_metadata_doc)
        self.assertEqual(research_result["status"], "recorded", research_result)

    def test_lectionary_example_observed_selection_is_the_full_selection_not_a_placeholder(self) -> None:
        # This is the exact shape earlier isolated agents got wrong: copying
        # a shorthand placeholder for observed_selection instead of the
        # complete normalized selection object.
        metadata = json.loads(_extract_example(self.doc, "lectionary-readings-metadata"))
        for source in metadata["sources"]:
            self.assertEqual(source["observed_selection"], metadata["selection"])

    def test_missing_readings_labels_error_names_the_exact_missing_fields(self) -> None:
        metadata = json.loads(_extract_example(self.doc, "lectionary-readings-metadata"))
        content = _extract_example(self.doc, "lectionary-readings-content")
        stripped = re.sub(r"^\*\*Occasion:\*\*.*\n", "", content, flags=re.M)
        stripped = re.sub(r"^\*\*Track:\*\*.*\n", "", stripped, flags=re.M)
        church = make_church(Path(self.temporary.name) / "missing-labels-example")
        selection = metadata["selection"]
        _configure_church(
            church,
            selection_mode="lectionary",
            translation=selection["translation"],
            primary_text="gospel",
            system=selection["lectionary_system"],
            track=selection["track"],
            optional_verses=selection["optional_verses_policy"],
        )
        blocked = record(church, selection["service_date"], "readings", stripped, metadata)
        self.assertEqual(blocked["errors"][0]["code"], "invalid_readings")
        self.assertIn("Occasion", blocked["errors"][0]["message"])
        self.assertIn("Track", blocked["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
