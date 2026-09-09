from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CORE = ROOT / "skills" / "onboarding" / "SKILL.md"
WEBSITE = ROOT / "skills" / "onboarding" / "references" / "website-discovery.md"
WORSHIP = ROOT / "skills" / "onboarding" / "references" / "worship-onboarding.md"


def prose(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class OnboardingContractTest(unittest.TestCase):
    def test_core_skill_is_a_short_router(self) -> None:
        text = CORE.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 240)
        self.assertIn("references/website-discovery.md", text)
        self.assertIn("references/worship-onboarding.md", text)
        self.assertIn("Required stage sequence", text)
        self.assertIn("What I found", text)
        self.assertIn("private church folder", text)

    def test_core_skill_makes_sources_do_the_interview_work(self) -> None:
        text = prose(CORE)
        for phrase in (
            "Proactive working-template contract",
            "bulletin deliberately supplied for onboarding is the church's working template until the pastor changes it",
            "Do not ask for a second confirmation of the bulletin template",
            "Do not wait for the pastor to ask \"what's next?\"",
            "Maintain them quietly",
            "Do not automatically continue",
        ):
            self.assertIn(phrase, text)

        sequence = "worship source chosen -> worship setup -> first useful result -> optional setup when requested"
        self.assertIn(sequence, text)

    def test_website_reference_owns_discovery_and_qr_detail(self) -> None:
        text = WEBSITE.read_text(encoding="utf-8")
        for phrase in (
            "## Bounded discovery",
            "Possible conflicts",
            "Brand candidates",
            "QR destinations",
            "confirmed URL",
            "private church folder",
            "only a candidate",
            "standard copy",
        ):
            self.assertIn(phrase, text)

    def test_worship_reference_supports_bulletin_and_fallback_paths(self) -> None:
        text = WORSHIP.read_text(encoding="utf-8")
        for phrase in (
            "Bulletin path",
            "Fallback worship interview",
            "What I will carry forward",
            "What changes each week",
            "Eucharistic Prayer",
            "canonical general blessing",
            "communion welcome is optional",
            "Ask whether the church has recurring services",
            "approved-text location",
            "End by naming the next two requests",
        ):
            self.assertIn(phrase, text)

    def test_bulletin_becomes_the_working_template_without_redundant_questions(self) -> None:
        text = prose(WORSHIP)
        for phrase in (
            "Supplying the bulletin for onboarding already selected it",
            "Do not ask whether each observed section or role slot should recur",
            "carry forward the section and its role slots without asking",
            "Confirmation of the current sermon passage is not confirmation",
            "Inspect the bulletin for a translation",
            "derive the lectionary, track, preaching translation",
            "Treat people named only in a dated Serving Today section as weekly assignments",
            "Then stop. Do not immediately ask an optional onboarding question",
        ):
            self.assertIn(phrase, text)

    def test_optional_setup_is_deferred_until_requested_or_needed(self) -> None:
        website = prose(WEBSITE)
        worship = prose(WORSHIP)
        self.assertIn("QR destinations after the first useful result", website)
        self.assertIn("without turning them into new questions", website)
        self.assertIn("Optional bulletin setup after the first useful result", worship)
        self.assertIn("Do not continue into this section automatically", worship)

    def test_onboarding_preserves_purpose_first_safety_contract(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8") for path in (CORE, WEBSITE, WORSHIP)
        )
        for phrase in (
            "why the decision matters",
            "Ask no more than three questions",
            "saved",
            "pending",
            "still unresolved",
            "Never request passwords",
            "do not ask the pastor",
            "magic confirmation phrase",
            "licensed",
        ):
            self.assertIn(phrase, text)

    def test_onboarding_does_not_add_a_printed_lyrics_rights_interview(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8") for path in (CORE, WEBSITE, WORSHIP)
        )
        for field in (
            "printed_lyrics",
            "allow_full_lyrics",
            "lyrics_source",
            "lyrics_permission",
            "options.printed_lyrics_confirmed",
        ):
            self.assertNotIn(field, text)


if __name__ == "__main__":
    unittest.main()
