"""Synthetic tests for the source-backed worship-choice guard.

Uses hand-built manifest dicts and page-text files rather than real PDFs;
skills/onboarding/source_choices.py only ever reads already-extracted page
text (produced elsewhere by bulletin_import.py), so a real PDF adds nothing
to these tests. No church data, real bulletin content, or private source
material appears here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_church


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "onboarding"))
sys.path.insert(0, str(ROOT / "skills" / "onboarding" / "scripts"))

from source_choices import (  # noqa: E402
    aggregate_imports,
    find_contradictions,
    observe_manifest,
)


def _write_pages(root: Path, pages: dict[int, str]) -> list[dict]:
    text_dir = root / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    manifest_pages = []
    for page_number, text in pages.items():
        name = f"page-{page_number:04d}.txt"
        (text_dir / name).write_text(text, encoding="utf-8")
        manifest_pages.append({"page": page_number, "text_path": f"text/{name}"})
    return manifest_pages


def _manifest(root: Path, import_id: str, pages: dict[int, str], sha256: str | None = None) -> dict:
    return {
        "import_id": import_id,
        "source": {"sha256": sha256 or (import_id * 4)[:64], "page_count": len(pages)},
        "pages": _write_pages(root, pages),
    }


CHRIST_CHURCH_PAGES = {
    1: "Hymn in Procession 1\nWelcome and announcements\n",
    3: (
        "The Great Thanksgiving\nCelebrant and People\n"
        "It is right to give God thanks and praise.\n"
        "Book of Common Prayer, page 361\n"
    ),
    8: (
        "Post-Communion Prayer\nLet us pray.\n\nThe Blessing\n\n"
        "Hymn in Procession    376    Christ Whose Glory\n\n"
        "The Dismissal\nCelebrant: Go in peace.\n"
    ),
}


# Reproduces the real pdftotext column-reflow pattern a private probe
# surfaced: the printed BCP page citation lands well after the "Great
# Thanksgiving" heading, past the whole Sursum Corda dialogue, because the
# source PDF's columns get interleaved on extraction. Fake parish content.
COLUMN_REFLOW_PRAYER_A_PAGE = (
    "Anthem\nA setting for choir\nPlease stand and sing\n"
    "The Presentation Hymn 380, v. 3 Praise God, from Whom All Blessings Flow\n"
    "The Great Thanksgiving\n"
    "Celebrant\nThe Lord be with you.\n"
    "People\nAnd also with you.\n"
    "Celebrant\nLift up your hearts.\n"
    "People\nWe lift them to the Lord.\n"
    "Celebrant\nLet us give thanks to the Lord our God.\n"
    "People\nIt is right to give God thanks and praise.\n"
    "\n"
    "Hymnal 1982\n"
    "(red) Book of Common Prayer 361\n"
)


class ObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_explicit_label_and_page_anchor_agree_high_confidence(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", {
            3: "The Great Thanksgiving\nEucharistic Prayer A\nBook of Common Prayer, page 361\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertEqual(observations["eucharistic_prayer"]["value"], "A")
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "high")
        self.assertIn("Eucharistic Prayer A", observations["eucharistic_prayer"]["evidence"])

    def test_christ_church_style_mismatch_is_detected(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES)
        observations = observe_manifest(self.root, manifest)
        self.assertEqual(observations["eucharistic_prayer"], {
            "value": "A", "confidence": "high", "page": 3,
            "evidence": "Great Thanksgiving with a BCP 361 page anchor",
        })
        self.assertEqual(observations["closing_hymn_position"]["value"], "before_dismissal")
        self.assertEqual(observations["closing_hymn_position"]["page"], 8)

        aggregated = aggregate_imports(
            {"aaaaaaaaaaaaaaaa": observations},
            {"aaaaaaaaaaaaaaaa": manifest["source"]["sha256"]},
        )
        contradictions = find_contradictions(
            aggregated,
            {"eucharistic_prayer": "B", "closing_hymn_position": "after_dismissal"},
            {},
        )
        fields = {item["field"] for item in contradictions}
        self.assertEqual(fields, {"eucharistic_prayer", "closing_hymn_position"})
        ep = next(item for item in contradictions if item["field"] == "eucharistic_prayer")
        self.assertEqual(ep["source_value"], "A")
        self.assertEqual(ep["standing_value"], "B")
        self.assertEqual(ep["page"], 3)

    def test_matching_standing_values_produce_no_contradiction(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES)
        observations = observe_manifest(self.root, manifest)
        aggregated = aggregate_imports(
            {"aaaaaaaaaaaaaaaa": observations},
            {"aaaaaaaaaaaaaaaa": manifest["source"]["sha256"]},
        )
        contradictions = find_contradictions(
            aggregated,
            {"eucharistic_prayer": "A", "closing_hymn_position": "before_dismissal"},
            {},
        )
        self.assertEqual(contradictions, [])

    def test_no_import_means_no_observations_to_compare(self) -> None:
        aggregated = aggregate_imports({}, {})
        for field, observation in aggregated.items():
            self.assertEqual(observation["confidence"], "unknown", field)
        contradictions = find_contradictions(aggregated, {"eucharistic_prayer": "B"}, {})
        self.assertEqual(contradictions, [])

    def test_conflicting_anchors_within_one_import_are_ambiguous_not_a_guess(self) -> None:
        manifest = _manifest(self.root, "bbbbbbbbbbbbbbbb", {
            3: (
                "The Great Thanksgiving\nEucharistic Prayer A\n"
                "It is right to give God thanks and praise.\nBook of Common Prayer, page 367\n"
            ),
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["eucharistic_prayer"]["value"])
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "ambiguous")

    def test_disagreeing_imports_are_ambiguous_not_whichever_sorts_first(self) -> None:
        first = _manifest(self.root, "aaaaaaaaaaaaaaaa", {
            3: "The Great Thanksgiving\nIt is right to give God thanks and praise.\nBook of Common Prayer, page 361\n",
        }, sha256="1" * 64)
        second = _manifest(self.root, "bbbbbbbbbbbbbbbb", {
            4: "The Great Thanksgiving\nIt is right to give God thanks and praise.\nBook of Common Prayer, page 367\n",
        }, sha256="2" * 64)
        observations_by_import = {
            "aaaaaaaaaaaaaaaa": observe_manifest(self.root, first),
            "bbbbbbbbbbbbbbbb": observe_manifest(self.root, second),
        }
        aggregated = aggregate_imports(observations_by_import, {"aaaaaaaaaaaaaaaa": "1" * 64, "bbbbbbbbbbbbbbbb": "2" * 64})
        self.assertEqual(aggregated["eucharistic_prayer"]["confidence"], "ambiguous")
        self.assertIsNone(aggregated["eucharistic_prayer"]["value"])

    def test_communion_and_opening_hymn_slots_are_not_mistaken_for_closing(self) -> None:
        manifest = _manifest(self.root, "cccccccccccccccc", {
            1: "Hymn in Procession 1\nOpening acclamation\n",
            5: "Communion Hymn 300\nDuring communion\n",
            6: "Offertory Hymn 210\n",
            8: "The Dismissal\nGo in peace.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["closing_hymn_position"]["value"])
        self.assertEqual(observations["closing_hymn_position"]["confidence"], "unknown")

    def test_bare_page_number_without_great_thanksgiving_context_is_not_a_signal(self) -> None:
        manifest = _manifest(self.root, "dddddddddddddddd", {
            2: "See page 361 of the bulletin for the announcements.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["eucharistic_prayer"]["value"])
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "unknown")

    def test_no_dismissal_heading_leaves_closing_hymn_unknown(self) -> None:
        manifest = _manifest(self.root, "eeeeeeeeeeeeeeee", {
            8: "Hymn in Procession 376\nGo in peace, mentioned in passing dismissal talk.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["closing_hymn_position"]["value"])

    def test_tampered_or_escaping_text_path_is_ignored_not_followed(self) -> None:
        outside = self.root.parent / "outside-secret.txt"
        outside.write_text("Eucharistic Prayer A\n", encoding="utf-8")
        church = self.root / "church"
        church.mkdir()
        manifest = {
            "import_id": "ffffffffffffffff",
            "source": {"sha256": "f" * 64, "page_count": 1},
            "pages": [
                {"page": 1, "text_path": "../outside-secret.txt"},
                {"page": 2, "text_path": "/etc/passwd"},
                {"page": 3, "text_path": 12345},
            ],
        }
        observations = observe_manifest(church, manifest)
        self.assertIsNone(observations["eucharistic_prayer"]["value"])
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "unknown")

    def test_column_reflow_separates_anchor_from_heading_across_sursum_corda(self) -> None:
        # A real retained import placed the page anchor 15 lines after the
        # heading, past the whole Sursum Corda; a nearby-line window alone
        # cannot see it, so corroborating Sursum Corda response text is
        # required instead of line proximity.
        manifest = _manifest(self.root, "6666666666666666", {5: COLUMN_REFLOW_PRAYER_A_PAGE})
        observations = observe_manifest(self.root, manifest)
        self.assertEqual(observations["eucharistic_prayer"]["value"], "A")
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "high")

    def test_conflicting_prayer_book_anchors_do_not_choose_the_first(self) -> None:
        manifest = _manifest(self.root, "8888888888888888", {
            5: "The Great Thanksgiving\nIt is right to give him thanks and praise.\n"
               "Book of Common Prayer 361\nBook of Common Prayer 367\n",
        })
        observation = observe_manifest(self.root, manifest)["eucharistic_prayer"]
        self.assertEqual(observation["confidence"], "ambiguous")
        self.assertIsNone(observation["value"])

    def test_prayer_c_body_fingerprint_wrapped_across_a_reflowed_line(self) -> None:
        # A real retained import had no selectable "Eucharistic Prayer"
        # label or BCP page number at all for this page (the printed
        # heading was evidently not selectable text); pdftotext also wraps
        # the fingerprint phrase itself mid-word-group.
        manifest = _manifest(self.root, "7777777777777777", {
            8: "Celebrant At your command all things came to be: the vast expanse of interstellar\n"
               "space, galaxies, suns, the planets in their courses.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertEqual(observations["eucharistic_prayer"]["value"], "C")
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "high")

    def test_page_anchor_without_sursum_corda_corroboration_stays_unknown(self) -> None:
        # Great Thanksgiving heading and a bare 361 both present, but no
        # Sursum Corda response text corroborates that the number actually
        # belongs to this prayer -- still not enough to guess.
        manifest = _manifest(self.root, "8888888888888888", {
            5: "The Great Thanksgiving\nBook of Common Prayer, page 361\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["eucharistic_prayer"]["value"])
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "unknown")

    def test_two_labels_on_one_page_conflict_not_first_match(self) -> None:
        manifest = _manifest(self.root, "1111111111111111", {
            3: "The Great Thanksgiving\nEucharistic Prayer A\n...\nEucharistic Prayer B\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["eucharistic_prayer"]["value"])
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "ambiguous")

    def test_narrative_future_reference_does_not_outrank_the_actual_service(self) -> None:
        manifest = _manifest(self.root, "2222222222222222", {
            3: "The Great Thanksgiving\nEucharistic Prayer A\nNext week Eucharistic Prayer B will be used.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertEqual(observations["eucharistic_prayer"]["value"], "A")
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "high")

    def test_unrelated_page_number_far_from_great_thanksgiving_heading_is_not_an_anchor(self) -> None:
        manifest = _manifest(self.root, "3333333333333333", {
            3: (
                "The Great Thanksgiving\nCelebrant and People\n"
                + ("\n" * 6)
                + "Bulletin printed on page 361 of our records.\n"
            ),
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["eucharistic_prayer"]["value"])
        self.assertEqual(observations["eucharistic_prayer"]["confidence"], "unknown")

    def test_compact_one_page_service_does_not_mistake_opening_for_closing(self) -> None:
        # No blessing/post-communion anchor precedes the single "Hymn in
        # Procession" heading, so it reads as the opening hymn, not closing.
        manifest = _manifest(self.root, "4444444444444444", {
            1: "Hymn in Procession 1\nWelcome\n...\nThe Dismissal\nGo in peace.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertIsNone(observations["closing_hymn_position"]["value"])
        self.assertEqual(observations["closing_hymn_position"]["confidence"], "unknown")

    def test_explicit_closing_label_does_not_need_a_late_service_anchor(self) -> None:
        manifest = _manifest(self.root, "5555555555555555", {
            1: "Closing Hymn 400\nThe Dismissal\nGo in peace.\n",
        })
        observations = observe_manifest(self.root, manifest)
        self.assertEqual(observations["closing_hymn_position"]["value"], "before_dismissal")
        self.assertEqual(observations["closing_hymn_position"]["confidence"], "high")

    def test_ambiguous_sample_keeps_aggregate_ambiguous_even_with_an_agreeing_high_confidence_import(self) -> None:
        clean = _manifest(self.root, "aaaaaaaaaaaaaaaa", {
            3: "The Great Thanksgiving\nEucharistic Prayer A\nBook of Common Prayer, page 361\n",
        }, sha256="1" * 64)
        # Internally self-conflicting: two distinct labels on one page.
        contrary = _manifest(self.root, "bbbbbbbbbbbbbbbb", {
            4: "The Great Thanksgiving\nEucharistic Prayer A\n...\nEucharistic Prayer D\n",
        }, sha256="2" * 64)
        observations_by_import = {
            "aaaaaaaaaaaaaaaa": observe_manifest(self.root, clean),
            "bbbbbbbbbbbbbbbb": observe_manifest(self.root, contrary),
        }
        aggregated = aggregate_imports(
            observations_by_import, {"aaaaaaaaaaaaaaaa": "1" * 64, "bbbbbbbbbbbbbbbb": "2" * 64}
        )
        self.assertEqual(aggregated["eucharistic_prayer"]["confidence"], "ambiguous")
        self.assertIsNone(aggregated["eucharistic_prayer"]["value"])

    def test_override_missing_reason_is_never_trusted_even_if_hand_edited_into_profile(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, sha256="a" * 64)
        aggregated = aggregate_imports(
            {"aaaaaaaaaaaaaaaa": observe_manifest(self.root, manifest)},
            {"aaaaaaaaaaaaaaaa": "a" * 64},
        )
        overrides = {"eucharistic_prayer": {"source_sha256": "a" * 64, "value": "B", "reason": ""}}
        contradictions = find_contradictions(aggregated, {"eucharistic_prayer": "B"}, overrides)
        self.assertEqual(len(contradictions), 1)

        overrides_non_string = {"eucharistic_prayer": {"source_sha256": "a" * 64, "value": "B", "reason": {}}}
        contradictions = find_contradictions(aggregated, {"eucharistic_prayer": "B"}, overrides_non_string)
        self.assertEqual(len(contradictions), 1)

    def test_valid_override_suppresses_a_current_contradiction(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, sha256="a" * 64)
        aggregated = aggregate_imports(
            {"aaaaaaaaaaaaaaaa": observe_manifest(self.root, manifest)},
            {"aaaaaaaaaaaaaaaa": "a" * 64},
        )
        overrides = {
            "eucharistic_prayer": {"source_sha256": "a" * 64, "value": "B", "reason": "The rector prefers Prayer B."},
        }
        contradictions = find_contradictions(
            aggregated, {"eucharistic_prayer": "B", "closing_hymn_position": "before_dismissal"}, overrides
        )
        self.assertEqual(contradictions, [])

    def test_stale_override_after_a_changed_choice_still_blocks(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, sha256="a" * 64)
        aggregated = aggregate_imports(
            {"aaaaaaaaaaaaaaaa": observe_manifest(self.root, manifest)},
            {"aaaaaaaaaaaaaaaa": "a" * 64},
        )
        overrides = {
            "eucharistic_prayer": {"source_sha256": "a" * 64, "value": "B", "reason": "Previously chosen."},
        }
        # The pastor changed the standing choice again, to C, after the override was recorded for B.
        contradictions = find_contradictions(aggregated, {"eucharistic_prayer": "C"}, overrides)
        self.assertEqual(len(contradictions), 1)
        self.assertEqual(contradictions[0]["field"], "eucharistic_prayer")

    def test_stale_override_after_a_reimport_still_blocks(self) -> None:
        manifest = _manifest(self.root, "aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, sha256="new-hash" * 8)
        aggregated = aggregate_imports(
            {"aaaaaaaaaaaaaaaa": observe_manifest(self.root, manifest)},
            {"aaaaaaaaaaaaaaaa": ("new-hash" * 8)[:64]},
        )
        overrides = {
            "eucharistic_prayer": {"source_sha256": "old-hash" * 8, "value": "B", "reason": "Previously chosen."},
        }
        contradictions = find_contradictions(aggregated, {"eucharistic_prayer": "B"}, overrides)
        self.assertEqual(len(contradictions), 1)


class ChurchSetupIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.church = make_church(Path(self.temporary.name))
        sys.path.insert(0, str(ROOT / "skills" / "onboarding" / "scripts"))
        global church_setup
        import church_setup  # noqa: PLC0415

    def _write_import(self, import_id: str, pages: dict[int, str], sha256: str) -> None:
        base = self.church / "onboarding" / "imports" / import_id
        text_dir = base / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        manifest_pages = []
        for page_number, text in pages.items():
            name = f"page-{page_number:04d}.txt"
            (text_dir / name).write_text(text, encoding="utf-8")
            manifest_pages.append({
                "page": page_number,
                "text_path": f"onboarding/imports/{import_id}/text/{name}",
            })
        manifest = {
            "import_id": import_id,
            "source": {"sha256": sha256, "page_count": len(pages)},
            "pages": manifest_pages,
        }
        (base / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _confirm_worship_profile(self) -> None:
        church_setup.update_standing(self.church, {
            "worship_profile": {
                "tradition_pack": "episcopal-bcp-rite-ii",
                "status": "confirmed",
                "defaults": {
                    "eucharistic_prayer": "B", "lords_prayer": "traditional", "prayers_of_the_people": "III",
                    "closing_hymn_position": "after_dismissal",
                    "include_creed": True, "include_confession": True,
                    "print_full_eucharistic_prayer": False,
                },
            },
        })
        church_setup.update_standing(self.church, {
            "worship_profile": {"defaults": {"psalm_format": "responsive_half_verse"}},
        })
        import brand_setup  # noqa: PLC0415
        brand_setup.update(self.church, {"logo_status": "none", "colors_status": "neutral"})

    def test_no_import_does_not_block_bulletin_ready(self) -> None:
        self._confirm_worship_profile()
        result = church_setup.status(self.church)
        self.assertNotIn(
            "eucharistic_prayer",
            " ".join(str(item) for item in result["unresolved"]),
        )

    def test_source_contradiction_blocks_bulletin_ready_with_a_plain_language_reason(self) -> None:
        self._write_import("aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, "a" * 64)
        self._confirm_worship_profile()
        result = church_setup.status(self.church)
        self.assertFalse(result["bulletin_ready"])
        reasons = [item["reason"] for item in result["unresolved"] if "worship_profile.defaults.eucharistic_prayer" == item.get("field")]
        self.assertEqual(len(reasons), 1)
        self.assertIn("page 3", reasons[0])
        self.assertIn("A", reasons[0])
        self.assertIn("B", reasons[0])

    def test_source_contradiction_does_not_affect_research_readiness(self) -> None:
        self._write_import("aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, "a" * 64)
        church_setup.update_standing(self.church, {
            "church": {"name": "Christ Church Test"},
            "sermon": {"selection_mode": "lectionary", "primary_text": "gospel"},
            "lectionary": {"system": "RCL", "track": "Track 2", "translation": "NRSV", "optional_verses": "appointed"},
        })
        result = church_setup.status(self.church)
        self.assertTrue(result["research_ready"])

    def test_recorded_override_lifts_the_block_until_the_choice_changes_again(self) -> None:
        self._write_import("aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, "a" * 64)
        self._confirm_worship_profile()
        blocked = church_setup.status(self.church)
        self.assertFalse(blocked["bulletin_ready"])

        church_setup.update_standing(self.church, {
            "worship_profile": {
                "source_overrides": {
                    "eucharistic_prayer": {
                        "source_sha256": "a" * 64,
                        "value": "B",
                        "reason": "The rector confirmed Prayer B is the intended standing choice.",
                    },
                    "closing_hymn_position": {
                        "source_sha256": "a" * 64,
                        "value": "after_dismissal",
                        "reason": "The retained sample was a one-off; the standing order is after_dismissal.",
                    },
                },
            },
        })
        acknowledged = church_setup.status(self.church)
        self.assertTrue(acknowledged["bulletin_ready"])

        # Changing the standing choice again stales the override automatically.
        church_setup.update_standing(self.church, {
            "worship_profile": {"defaults": {"eucharistic_prayer": "C"}},
        })
        stale = church_setup.status(self.church)
        self.assertFalse(stale["bulletin_ready"])

    def test_malformed_import_directory_does_not_crash_status(self) -> None:
        base = self.church / "onboarding" / "imports" / "aaaaaaaaaaaaaaaa"
        base.mkdir(parents=True)
        (base / "manifest.json").write_text("{not valid json", encoding="utf-8")
        self._confirm_worship_profile()
        result = church_setup.status(self.church)
        self.assertIn("bulletin_ready", result)

    def test_invalid_source_override_shape_is_rejected(self) -> None:
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {
                "worship_profile": {"source_overrides": {"not_a_checked_field": {"source_sha256": "a" * 64, "value": "B", "reason": "x"}}},
            })
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {
                "worship_profile": {"source_overrides": {"eucharistic_prayer": {"value": "B"}}},
            })
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {
                "worship_profile": {"source_overrides": {"eucharistic_prayer": {
                    "source_sha256": "not-a-hash", "value": "B", "reason": "x",
                }}},
            })
        with self.assertRaises(church_setup.SetupError):
            church_setup.update_standing(self.church, {
                "worship_profile": {"source_overrides": {"eucharistic_prayer": {
                    "source_sha256": "a" * 64, "value": "Z", "reason": "x",
                }}},
            })

    def test_guard_does_not_run_outside_episcopal_rite_ii(self) -> None:
        # No tradition pack confirmed (default scaffold state) means the
        # resolver never reports service_plan episcopal-rite-ii, so the
        # Episcopal-only guard must not run at all.
        self._write_import("aaaaaaaaaaaaaaaa", CHRIST_CHURCH_PAGES, "a" * 64)
        result = church_setup.status(self.church)
        self.assertEqual(result["source_choices"]["status"], "not_applicable")
        self.assertEqual(result["source_choices"]["contradictions"], [])


if __name__ == "__main__":
    unittest.main()
