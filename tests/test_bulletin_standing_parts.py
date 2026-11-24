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

    def test_the_response_after_the_gospel_can_come_from_the_church_s_file(self) -> None:
        import tempfile
        from skills.bulletin.bulletin_production.interface import _after_gospel_from_file
        root = Path(tempfile.mkdtemp())
        (root / "worship").mkdir()
        (root / "worship" / "refrain.md").write_text("<!-- a note -->\n\n*All sing the refrain.*\n\nRejoice! Rejoice!\nshall come\n",
                                                     encoding="utf-8")
        bulletin = {"after_gospel": {"file": "worship/refrain.md"}}
        _after_gospel_from_file(bulletin, root)
        self.assertEqual(bulletin["after_gospel"], {"speaker": "Together", "text": "Rejoice! Rejoice!\nshall come",
                                                    "rubric": "All sing the refrain."})

    def test_a_note_prints_under_the_preacher(self) -> None:
        html = sermon_block({"preacher": "Jordan Reyes", "preacher_note": "Seminarian at Riverbend Seminary"})
        self.assertIn("Jordan Reyes", html)
        self.assertIn('class="service-person center service-person-note">Seminarian at Riverbend Seminary', html)
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

    def test_quoted_lines_that_finish_a_sentence_join_its_paragraph(self) -> None:
        from skills.bulletin.bulletin_production.interface import _resolve_reading_format
        mark = ("Jesus said, \u201cIn those days, after that suffering,\n\nthe sun will be darkened,\n"
                "and the moon will not give its light.\n\nThen they will see")
        bulletin = {"readings": {"gospel": {"format": "poetry", "text": mark}}}
        _resolve_reading_format(bulletin, {})
        self.assertEqual(bulletin["readings"]["gospel"]["text"],
                         "Jesus said, \u201cIn those days, after that suffering, the sun will be darkened, "
                         "and the moon will not give its light.\n\nThen they will see")

    def test_a_church_may_keep_poetry_lines_on_purpose(self) -> None:
        from skills.bulletin.bulletin_production.interface import _resolve_reading_format
        bulletin = {"readings": {"first": {"format": "poetry", "text": "a\nb"}}}
        _resolve_reading_format(bulletin, {"reading_format": "poetry_where_printed"})
        self.assertEqual(bulletin["readings"]["first"], {"format": "poetry", "text": "a\nb"})


class TuneTest(unittest.TestCase):
    def test_a_stanza_cut_from_the_hymn_page_names_the_page_s_tune(self) -> None:
        import json
        import tempfile
        from skills.bulletin.bulletin_production.interface import _tunes_from_hymn_library
        root = Path(tempfile.mkdtemp())
        db = root / "music" / "church-music-db"
        db.mkdir(parents=True)
        (db / "H56-page-1.source.json").write_text(json.dumps({"hymn": "H56", "tune": "Veni, veni, Emmanuel"}), encoding="utf-8")
        (db / "H56-stanza-1.source.json").write_text(json.dumps({"hymn": "H56", "made_from": "H56-page-1.png"}), encoding="utf-8")
        (db / "H68-page-1.source.json").write_text(json.dumps({"hymn": "H68", "tune": "Llangloffan"}), encoding="utf-8")
        bulletin = {"hymns": {"gospel_acclamation": {"images": ["music/church-music-db/H56-stanza-1.png"]},
                              "entrance": {"images": ["music/church-music-db/H68-page-1.png"]},
                              "closing": {"images": ["music/church-music-db/H68-page-1.png"], "tune": "Kept"},
                              "communion": {"images": ["music/other.png"]}}}
        _tunes_from_hymn_library(bulletin, root)
        self.assertEqual(bulletin["hymns"]["gospel_acclamation"]["tune"], "Veni, veni, Emmanuel")
        self.assertEqual(bulletin["hymns"]["entrance"]["tune"], "Llangloffan")
        self.assertEqual(bulletin["hymns"]["closing"]["tune"], "Kept")
        self.assertNotIn("tune", bulletin["hymns"]["communion"])
        from_the_sheet = {"hymns": {"entrance": {"number": 68, "images": ["music/reused/h82-68-image1.png"]},
                                    "closing": {"title": "Day by Day", "images": []}}}
        _tunes_from_hymn_library(from_the_sheet, root)
        self.assertEqual(from_the_sheet["hymns"]["entrance"]["tune"], "Llangloffan")
        self.assertNotIn("tune", from_the_sheet["hymns"]["closing"])


class StagingTest(unittest.TestCase):
    def test_brand_fonts_stay_relative_and_travel_with_the_staged_brand(self) -> None:
        import json, tempfile
        from skills.bulletin.bulletin_production.interface import _stage_effective_brand
        root, stage = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        (root / "brand/type").mkdir(parents=True)
        (root / "brand/type/League.woff2").write_bytes(b"wOF2font")
        (root / "brand/logo.png").write_bytes(b"png")
        brand = {"logo": "brand/logo.png",
                 "brand_system": {"type": {"display": {"files": {"regular": "brand/type/League.woff2"}}}}}
        staged = json.loads(_stage_effective_brand(brand, {}, root, stage).read_text(encoding="utf-8"))
        self.assertEqual(staged["brand_system"]["type"]["display"]["files"]["regular"], "brand/type/League.woff2")
        self.assertEqual((stage / "brand/type/League.woff2").read_bytes(), b"wOF2font")
        self.assertTrue(Path(staged["logo"]).is_absolute())

    def test_two_hymns_named_page_1_both_keep_their_own_music(self) -> None:
        import tempfile
        from skills.bulletin.bulletin_production.interface import _copy_music_assets
        root, stage = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        for hymn in ("H75", "H67"):
            (root / "music/hymn-library" / hymn).mkdir(parents=True)
            (root / "music/hymn-library" / hymn / "page-1.png").write_bytes(hymn.encode())
        bulletin = {"hymns": {"entrance": {"images": ["music/hymn-library/H75/page-1.png"]},
                              "offertory": {"images": ["music/hymn-library/H67/page-1.png"]}}}
        _copy_music_assets(bulletin, root, stage, [])
        entrance, offertory = bulletin["hymns"]["entrance"]["images"][0], bulletin["hymns"]["offertory"]["images"][0]
        self.assertNotEqual(entrance, offertory)
        self.assertEqual((stage / entrance).read_bytes(), b"H75")
        self.assertEqual((stage / offertory).read_bytes(), b"H67")


if __name__ == "__main__":
    unittest.main()
