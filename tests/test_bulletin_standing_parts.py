"""Parts a church used to add by hand after the skill ran, now set in the bulletin's own input (Handbuilt PRD-026)."""
from __future__ import annotations

import unittest
from pathlib import Path

from skills.bulletin.renderer.render_bulletin import after_gospel_block, hymn_block, liturgy_section, sermon_block


class StandingPartsTest(unittest.TestCase):
    def test_everyone_sings_a_response_after_the_gospel(self) -> None:
        html = after_gospel_block({"after_gospel": {"speaker": "Together", "text": "Rejoice! Rejoice! Emmanuel\nshall come to thee, O Israel."}})
        self.assertIn('class="section after-gospel"', html)
        self.assertIn("Rejoice! Rejoice! Emmanuel", html)
        self.assertEqual(html.count(">Together<"), 1)
        self.assertEqual(after_gospel_block({}), "")
        self.assertEqual(after_gospel_block({"after_gospel": {"text": "  "}}), "")

    def test_a_note_prints_under_the_preacher(self) -> None:
        html = sermon_block({"preacher": "Jordan Reyes", "preacher_note": "Seminarian at Riverbend Seminary"})
        self.assertIn("Jordan Reyes", html)
        self.assertIn('class="service-person-note center">Seminarian at Riverbend Seminary', html)
        self.assertNotIn("service-person-note", sermon_block({"preacher": "Jordan Reyes"}))

    def test_the_church_s_choice_of_who_dismisses(self) -> None:
        deacon = liturgy_section("dismissal", {"dismissal_speaker": "Deacon"})
        self.assertIn(">Deacon<", deacon)
        self.assertNotIn(">Celebrant<", deacon)
        self.assertIn(">People<", deacon)
        self.assertIn(">Celebrant<", liturgy_section("dismissal", {}))

    def test_the_composer_label_can_be_plain_or_hidden(self) -> None:
        hymn = {"title": "Sweet, Sweet Spirit", "composer": "Doris Akers"}
        self.assertIn("Composer: Doris Akers", hymn_block("Closing Hymn", hymn, Path("/tmp")))
        plain = hymn_block("Closing Hymn", {**hymn, "composer_style": "plain"}, Path("/tmp"))
        self.assertIn(">Doris Akers<", plain)
        self.assertNotIn("Composer:", plain)
        self.assertNotIn("Doris Akers", hymn_block("Closing Hymn", {**hymn, "composer_style": "hidden"}, Path("/tmp")))
        # Engraved music prints its own credits, so no composer line by default.
        self.assertNotIn("Composer:", hymn_block("Closing Hymn", {**hymn, "images": ["missing.png"]}, Path("/tmp")))


class ReadingFormatTest(unittest.TestCase):
    def test_a_lesson_set_in_short_lines_prints_as_full_width_prose(self) -> None:
        from skills.bulletin.bulletin_production.interface import _resolve_reading_format
        isaiah = "Comfort, O comfort my people,\nsays your God.\nSpeak tenderly to Jerusalem,\n\nA voice cries out:\nIn the wilderness prepare the way"
        bulletin = {"readings": {"first": {"format": "poetry", "text": isaiah},
                                 "psalm": {"format": "responsive_half_verse", "text": "1 You have been gracious"}}}
        _resolve_reading_format(bulletin, {})
        first = bulletin["readings"]["first"]
        self.assertEqual(first["format"], "prose")
        self.assertEqual(first["text"], "Comfort, O comfort my people, says your God. Speak tenderly to Jerusalem,\n\n"
                                        "A voice cries out: In the wilderness prepare the way")
        self.assertEqual(bulletin["readings"]["psalm"]["format"], "responsive_half_verse")

    def test_a_church_may_keep_poetry_lines_on_purpose(self) -> None:
        from skills.bulletin.bulletin_production.interface import _resolve_reading_format
        bulletin = {"readings": {"first": {"format": "poetry", "text": "a\nb"}}}
        _resolve_reading_format(bulletin, {"reading_format": "poetry_where_printed"})
        self.assertEqual(bulletin["readings"]["first"], {"format": "poetry", "text": "a\nb"})


if __name__ == "__main__":
    unittest.main()
