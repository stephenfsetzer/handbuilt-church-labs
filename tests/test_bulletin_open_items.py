"""Printed brackets become open items only when they look like real blanks."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from skills.bulletin.bulletin_production.interface import (
    _renderer_dir,
    _shipped_bracket_texts,
    _unfilled_brackets,
)
from tests.helpers import REPO_ROOT, bulletin_input, make_church

try:
    import weasyprint  # noqa: F401
    HAVE_RUNTIME = True
except ImportError:  # pragma: no cover - the managed runtime has these
    HAVE_RUNTIME = False


class PrintedBracketTests(unittest.TestCase):
    def test_shipped_liturgy_raises_no_open_item(self) -> None:
        shipped = _shipped_bracket_texts()
        sources = [
            re.sub(r"<!--.*?-->", " ", path.read_text(encoding="utf-8"), flags=re.S)
            for path in sorted((_renderer_dir() / "liturgy").glob("*.md"))
        ]
        sources.append((REPO_ROOT / "skills/bulletin/resources/bcp1979/sunday.json").read_text(encoding="utf-8"))
        for text in sources:
            # The renderer replaces these two directives before anything prints.
            printable = re.sub(r"\[[^\]]*inserted here\]", " ", text)
            self.assertEqual(_unfilled_brackets(printable, shipped), [])

    def test_shipped_optional_words_are_known(self) -> None:
        self.assertIn("[this day]", _shipped_bracket_texts())
        self.assertIn("[on this day]", _shipped_bracket_texts())

    def test_comments_and_renderer_directives_excuse_nothing(self) -> None:
        shipped = _shipped_bracket_texts()
        for text in ("[Remember ___________.]", "[Proper Preface inserted here]", "[Communion welcome inserted here]"):
            self.assertEqual(_unfilled_brackets(text, shipped), [text])

    def test_conventional_markings_and_verse_numbers_are_left_alone(self) -> None:
        printed = "Luke 4:14-21 [22-30] Christ is risen. [Alleluia] [Refrain] [Silence may be kept]"
        self.assertEqual(_unfilled_brackets(printed, set()), [])

    def test_blanks_are_found_once_each_in_page_order(self) -> None:
        printed = "[Date of the meeting] and [Name] then [Name] and [____] and [Optional: name of the guest] and []"
        self.assertEqual(
            _unfilled_brackets(printed, set()),
            ["[Date of the meeting]", "[Name]", "[____]", "[Optional: name of the guest]", "[]"],
        )


@unittest.skipUnless(HAVE_RUNTIME, "the managed bulletin runtime is required")
class ProducedBulletinTests(unittest.TestCase):
    def test_a_default_bulletin_with_shipped_liturgy_has_no_open_items(self) -> None:
        from skills.bulletin.bulletin_production import produce
        with tempfile.TemporaryDirectory() as temporary:
            result = produce(make_church(Path(temporary)), bulletin_input())
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        self.assertEqual(result["open_items"], [])

    def test_an_announcement_blank_names_its_field(self) -> None:
        from skills.bulletin.bulletin_production import produce
        bulletin = bulletin_input()
        bulletin["announcements"] = [{"title": "Notice", "text": "Join us on [day of the event] for supper."}]
        with tempfile.TemporaryDirectory() as temporary:
            result = produce(make_church(Path(temporary)), bulletin)
        self.assertEqual(result["status"], "ready_for_review", result.get("errors"))
        self.assertEqual(
            [(item["text"], item["field"]) for item in result["open_items"]],
            [("[day of the event]", "announcements[0].text")],
        )


if __name__ == "__main__":
    unittest.main()
