"""The weekly texts tool copies readings from their sources so no one retypes them."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skills.bulletin import weekly_texts as W

ROOT = Path(__file__).resolve().parents[1]

# An invented lectionary page in the published page's layout. The lessons are made-up
# sentences, not scripture, so the test carries no one's translation.
PAGE = """<html><body>
<article><h2 class="lessonHeading">The Collect</h2>
<p class="collectText"><span class="initCap">G</span>rant us a quiet morning.</p></article>
<article><h2 class="lessonHeading" id="ot1">Old Testament</h2>
<h3 class="lessonCitation">Ruth 9:1-4</h3><div>
<p class="lessonText"><span class="initCap">T</span>he river rose in the spring. The
<span class="lordSmallCaps">Lord</span>sent rain on the hills.</p>
<p class="lessonText">Then the people [who had waited all winter] planted barley.</p></div></article>
<article><h2 class="lessonHeading" id="ot2">Old Testament</h2>
<h3 class="lessonCitation">Amos 12:1\N{EN DASH}3</h3><div>
<p class="poetryText"><span class="initCap">S</span>ing to the valley,<br>
    sing to the ridge; </p>
<p class="poetryText">let the orchard answer,<br>
    and the mill wheel turn. </p></div></article>
<article><h2 class="lessonHeading" id="gsp1">The Gospel</h2>
<h3 class="lessonCitation">Mark 19:5-9</h3><div>
<p class="lessonText">A sower went out at dawn.</p>
<p class="poetryText">\N{LEFT DOUBLE QUOTATION MARK}The field is wide,<br>and the day is long.\N{RIGHT DOUBLE QUOTATION MARK}</p>
<p class="lessonText">And they went home glad.</p></div></article>
</body></html>"""


class ParsingTests(unittest.TestCase):
    def test_each_lesson_is_found_with_its_citation(self):
        citations = [lesson["citation"] for lesson in W.parse_lessons(PAGE)]
        self.assertEqual(citations, ["Ruth 9:1-4", "Amos 12:1\N{EN DASH}3", "Mark 19:5-9"])

    def test_the_collect_is_not_mistaken_for_a_lesson(self):
        self.assertNotIn("", [lesson["citation"] for lesson in W.parse_lessons(PAGE)])

    def test_a_citation_matches_whatever_its_spacing_or_dash(self):
        self.assertEqual(W._key("Amos 12: 1-3"), W._key("Amos 12:1\N{EN DASH}3"))
        self.assertEqual(W._key("Psalm 90:1-8, (9-11), 12"), W._key("psalm 90:1-8,9-11,12"))


class FillTests(unittest.TestCase):
    def fill(self, bulletin, **options):
        return W.fill(bulletin, page_html=PAGE, page_url="https://lectionarypage.net/x.html",
                      today="2026-01-04", **options)

    def test_prose_keeps_its_paragraphs_and_its_opening_letter(self):
        bulletin = {"readings": {"first": {"citation": "Ruth 9:1-4"}}}
        self.fill(bulletin, optional="include")
        text = bulletin["readings"]["first"]["text"]
        self.assertTrue(text.startswith("The river rose in the spring."))
        self.assertEqual(text.count("\n\n"), 1)
        self.assertNotIn("format", bulletin["readings"]["first"])

    def test_a_space_the_page_dropped_after_the_divine_name_is_restored(self):
        bulletin = {"readings": {"first": {"citation": "Ruth 9:1-4"}}}
        self.fill(bulletin, optional="include")
        self.assertIn("The Lord sent rain", bulletin["readings"]["first"]["text"])

    def test_optional_verses_stop_the_tool_until_someone_chooses(self):
        bulletin = {"readings": {"first": {"citation": "Ruth 9:1-4"}}}
        with self.assertRaises(W.WeeklyTextsError) as caught:
            self.fill(bulletin)
        self.assertIn("optional verses", str(caught.exception))
        self.assertNotIn("text", bulletin["readings"]["first"])

    def test_optional_verses_are_kept_or_dropped_as_chosen(self):
        kept = {"readings": {"first": {"citation": "Ruth 9:1-4"}}}
        self.fill(kept, optional="include")
        self.assertIn("people who had waited all winter planted", kept["readings"]["first"]["text"])
        dropped = {"readings": {"first": {"citation": "Ruth 9:1-4"}}}
        self.fill(dropped, optional="omit")
        self.assertIn("Then the people planted barley.", dropped["readings"]["first"]["text"])

    def test_poetry_keeps_its_lines_and_stays_one_poem(self):
        bulletin = {"readings": {"first": {"citation": "Amos 12:1-3"}}}
        self.fill(bulletin)
        reading = bulletin["readings"]["first"]
        self.assertEqual(reading["format"], "poetry")
        self.assertEqual(reading["text"].split("\n"),
                         ["Sing to the valley,", "sing to the ridge;", "let the orchard answer,",
                          "and the mill wheel turn."])

    def test_a_lesson_that_quotes_a_poem_keeps_both(self):
        bulletin = {"readings": {"gospel": {"citation": "Mark 19:5-9"}}}
        self.fill(bulletin)
        blocks = bulletin["readings"]["gospel"]["text"].split("\n\n")
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[1].count("\n"), 1)

    def test_each_filled_reading_records_where_it_came_from(self):
        bulletin = {"readings": {"gospel": {"citation": "Mark 19:5-9"}}}
        self.fill(bulletin)
        self.assertEqual(bulletin["readings"]["gospel"]["source"],
                         {"label": "The Lectionary Page", "location": "https://lectionarypage.net/x.html",
                          "verified_on": "2026-01-04"})

    def test_a_citation_the_page_lacks_names_what_the_page_has(self):
        bulletin = {"readings": {"second": {"citation": "Jude 40:1-2"}}}
        with self.assertRaises(W.WeeklyTextsError) as caught:
            self.fill(bulletin)
        self.assertIn("Mark 19:5-9", str(caught.exception))

    def test_words_already_in_the_file_are_left_alone(self):
        bulletin = {"readings": {"gospel": {"citation": "Mark 19:5-9", "text": "The pastor's own wording."}}}
        summary = self.fill(bulletin)
        self.assertEqual(bulletin["readings"]["gospel"]["text"], "The pastor's own wording.")
        self.assertEqual(summary["status"], "nothing_to_fill")

    def test_the_summary_never_carries_a_passage(self):
        bulletin = {"readings": {"gospel": {"citation": "Mark 19:5-9"}}}
        summary = json.dumps(self.fill(bulletin))
        self.assertNotIn("sower", summary)
        self.assertIn('"words": 20', summary)

    def test_the_psalm_comes_from_the_library_in_the_church_format(self):
        bulletin = {"liturgy": {"psalm_format": "responsive_whole_verse", "psalm_response_start": "first"},
                    "readings": {"psalm": {"number": "23:1-3, (4-6)"}}}
        W.fill(bulletin)
        psalm = bulletin["readings"]["psalm"]
        self.assertEqual(psalm["number"], "23:1-3, (4-6)")
        self.assertEqual([verse["number"] for verse in psalm["verses"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual((psalm["format"], psalm["response_start"]), ("responsive_whole_verse", "first"))
        self.assertEqual(psalm["source"]["library_id"], "bcp1979/psalms/23")

    def test_a_psalm_that_is_not_a_number_is_refused_plainly(self):
        with self.assertRaises(W.WeeklyTextsError):
            W.fill({"readings": {"psalm": {"number": "the shepherd one"}}})

    def test_the_collect_and_preface_come_from_the_library_with_their_sources(self):
        bulletin = {"collect_of_day": {"library": "proper-28"}, "proper_preface": {"library": "lords-day"}}
        W.fill(bulletin)
        self.assertIsInstance(bulletin["collect_of_day"], str)
        self.assertIsInstance(bulletin["proper_preface"], str)
        self.assertEqual(bulletin["collect_source"]["library_id"], "bcp1979/collects/proper-28")
        self.assertEqual(bulletin["proper_preface_source"]["library_id"], "bcp1979/prefaces/lords-day")

    def test_lessons_without_a_page_ask_for_one(self):
        with self.assertRaises(W.WeeklyTextsError) as caught:
            W.fill({"readings": {"gospel": {"citation": "Mark 19:5-9"}}})
        self.assertIn("--lectionary-page", str(caught.exception))


class FileTests(unittest.TestCase):
    def test_the_file_is_filled_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text(json.dumps({"readings": {"gospel": {"citation": "Mark 19:5-9"}}}), encoding="utf-8")
            with mock.patch.object(W, "fetch_page", return_value=PAGE):
                summary = W.fill_file(path, page_url="https://lectionarypage.net/x.html")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(saved["readings"]["gospel"]["text"].startswith("A sower went out"))
            self.assertEqual(summary["status"], "filled")
            self.assertEqual([item.name for item in Path(folder).iterdir()], ["input.json"])

    def test_a_failure_leaves_the_file_as_it_was(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            before = json.dumps({"readings": {"gospel": {"citation": "Mark 19:5-9"},
                                              "second": {"citation": "Jude 40:1-2"}}})
            path.write_text(before, encoding="utf-8")
            with mock.patch.object(W, "fetch_page", return_value=PAGE):
                with self.assertRaises(W.WeeklyTextsError):
                    W.fill_file(path, page_url="https://lectionarypage.net/x.html")
            self.assertEqual(path.read_text(encoding="utf-8"), before)


class DownloadTests(unittest.TestCase):
    def test_only_the_lectionary_site_is_downloaded(self):
        for address in ("http://lectionarypage.net/a.html", "https://example.org/a.html",
                        "https://lectionarypage.net.example.org/a.html", "file:///etc/hosts"):
            with self.assertRaises(W.WeeklyTextsError):
                W.fetch_page(address)

    def test_the_download_names_this_program_and_not_a_browser(self):
        self.assertIn("Handbuilt", W.CLIENT)
        self.assertNotIn("Mozilla", W.CLIENT)


class InstructionTests(unittest.TestCase):
    def test_the_bulletin_instructions_forbid_retyping_and_name_the_tool(self):
        skill = (ROOT / "skills/bulletin/SKILL.md").read_text(encoding="utf-8")
        weekly = (ROOT / "skills/bulletin/references/weekly-input.md").read_text(encoding="utf-8")
        self.assertIn("Never type a reading", skill)
        self.assertIn("scripts/weekly_texts.py fill", weekly)
        self.assertIn("## Let the tool copy the texts", weekly)


if __name__ == "__main__":
    unittest.main()
