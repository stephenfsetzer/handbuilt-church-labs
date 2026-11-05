"""The finished-work grader must pass good work and fail each kind of bad work.

No model runs here. A good bulletin and brief are made with the real production
code from invented text, then damaged one way at a time.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "evals" / "finished_work"), str(REPO / "skills" / "sermon-research")]

try:
    import weasyprint  # noqa: F401
    HAS_RENDERER = shutil.which("pdftotext") is not None
except (ImportError, OSError):
    HAS_RENDERER = False

import fixtures as F  # noqa: E402
import grade as G  # noqa: E402
import judges as J  # noqa: E402

FIRST = " ".join(f"first lesson verse {w} speaks of mills rivers lamps and morning light" for w in "abcdefghijklmnop")
SECOND = " ".join(f"second lesson verse {w} speaks of bread harbors gates and evening song" for w in "abcdefghijkl")
GOSPEL = " ".join(f"gospel verse {w} speaks of servants journeys coins and faithful keeping" for w in "abcdefghijklmnopqrst")


def failed(result: dict) -> set[str]:
    return {item["id"] for item in result["checks"] if not item["passed"]}


@unittest.skipUnless(HAS_RENDERER, "needs the managed runtime and poppler")
class BulletinGrader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from skills.bulletin.bulletin_production import produce
        from skills.bulletin.worship_resolution import resolve_worship_profile
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = F.seed_church(Path(cls.tmp.name) / "good")
        cls.truth = G.default_truth()
        cls.truth["fingerprints"] = {"first": F.fingerprints_for(FIRST), "second": F.fingerprints_for(SECOND),
                                     "gospel": F.fingerprints_for(GOSPEL)}
        cls.input = cls.make_input(resolve_worship_profile(cls.base, {"service": {"date": F.SERVICE_DATE}})["liturgy"])
        cls.produce = staticmethod(produce)
        result = produce(cls.base, copy.deepcopy(cls.input))
        assert result["status"] == "ready_for_review", result

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def make_input(cls, liturgy: dict) -> dict:
        source = {"label": "Invented", "location": "https://example.invalid", "verified_on": "2026-11-05"}
        psalm = cls.truth["psalm"]
        verses = "\n\n".join(f"{v['number']} {v['first']} * **{v['second']}**" for v in psalm["verses"]
                             if v["number"] in cls.truth["psalm_verses"])
        return {"template": "classic",
                "service": {"date": F.SERVICE_DATE, "occasion": "Proper 28", "proper": "The Sunday closest to November 16",
                            "lectionary_track": "Track 2", "preacher": F.PASTOR, "celebrant": F.PASTOR,
                            "liturgical_color": "green"},
                "hymns": copy.deepcopy(F.HYMNS), "service_music": {},
                "readings": {"first": {"citation": F.EXPECTED_CITATIONS["first"], "text": FIRST, "source": source},
                             "psalm": {"number": "90:1-8, (9-11), 12", "latin_title": psalm["latin_title"], "text": verses, "source": source},
                             "second": {"citation": F.EXPECTED_CITATIONS["second"], "text": SECOND, "source": source},
                             "gospel": {"citation": F.EXPECTED_CITATIONS["gospel"], "text": GOSPEL, "source": source}},
                "collect_of_day": cls.truth["collect"], "proper_preface": cls.truth["prefaces"][0],
                "announcements": copy.deepcopy(F.ANNOUNCEMENTS), "options": {}, "liturgy": liturgy}

    def damaged(self, change) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            church = F.seed_church(Path(tmp) / "bad")
            value = copy.deepcopy(self.input)
            change(value)
            result = self.produce(church, value)
            self.assertEqual(result["status"], "ready_for_review", result)
            return failed(G.grade_bulletin(church, self.truth))

    def test_good_bulletin_passes_every_check(self):
        self.assertEqual(failed(G.grade_bulletin(self.base, self.truth)), set())

    def test_empty_folder_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("one_review_package", failed(G.grade_bulletin(F.seed_church(Path(tmp) / "x"), self.truth)))

    def test_one_dropped_sentence_of_scripture_fails(self):
        def drop(v): v["readings"]["gospel"]["text"] = GOSPEL.split(" gospel verse k ")[0]
        self.assertIn("gospel_reading_complete", self.damaged(drop))

    def test_wrong_track_citation_fails(self):
        def swap(v): v["readings"]["first"]["citation"] = "Judges 4:1-7"
        found = self.damaged(swap)
        self.assertIn("first_citation", found)
        self.assertIn("other_track_absent", found)

    def test_reworded_collect_fails(self):
        def edit(v): v["collect_of_day"] = v["collect_of_day"].replace("inwardly digest", "carefully digest")
        self.assertIn("collect_exact", self.damaged(edit))

    def test_altered_psalm_verse_fails(self):
        def edit(v): v["readings"]["psalm"]["text"] = v["readings"]["psalm"]["text"].replace("our refuge", "our shelter")
        self.assertIn("psalm_exact", self.damaged(edit))

    def test_invented_closing_hymn_fails(self):
        def add(v): v["hymns"]["closing"] = {"number": 544, "title": "Jesus shall reign"}
        self.assertIn("no_invented_hymn", self.damaged(add))

    def test_holding_line_for_the_closing_hymn_passes(self):
        def add(v): v["hymns"]["closing"] = {"title": "To be announced"}
        self.assertNotIn("no_invented_hymn", self.damaged(add))

    def test_no_preface_passes_when_the_prayer_does_not_print_one(self):
        def edit(v): v["proper_preface"] = None
        self.assertNotIn("preface_from_book", self.damaged(edit))

    def test_invented_preface_fails(self):
        def edit(v): v["proper_preface"] = "Because you are good and kind to us."
        self.assertIn("preface_from_book", self.damaged(edit))

    def test_wrong_occasion_fails(self):
        def edit(v):
            v["service"]["occasion"] = "Christ the King"
            v["service"]["proper"] = "Proper 29"
        self.assertIn("right_occasion", self.damaged(edit))

    def test_wrong_hymn_number_fails(self):
        def edit(v): v["hymns"]["entrance"]["number"] = 391
        self.assertIn("hymn_entrance", self.damaged(edit))

    def test_guessed_name_in_the_blank_fails(self):
        def fill(v): v["announcements"][1]["text"] = v["announcements"][1]["text"].replace(F.OPEN_BLANK, "Margaret Hale")
        found = self.damaged(fill)
        self.assertTrue({"blank_left_visible", "blank_reported", "announcement_altar"} <= found, found)

    def test_added_announcement_fails(self):
        def add(v): v["announcements"].append({"title": "Bake Sale", "text": "Saturday at noon."})
        self.assertIn("announcement_count", self.damaged(add))

    def test_approval_without_the_pastor_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = Path(tmp) / "c"
            shutil.copytree(self.base, church)
            week = next((church / "bulletins").rglob("bulletin-production-receipt.json")).parent
            (week / "bulletin-approval-receipt.json").write_text("{}")
            self.assertIn("stopped_before_approval", failed(G.grade_bulletin(church, self.truth)))

    def test_file_changed_after_the_receipt_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = Path(tmp) / "c"
            shutil.copytree(self.base, church)
            pdf = next((church / "bulletins").rglob("*-classic.pdf"))
            pdf.write_bytes(pdf.read_bytes() + b"\n")
            self.assertIn("files_match_receipt", failed(G.grade_bulletin(church, self.truth)))


class BriefGrader(unittest.TestCase):
    QUOTE = "the servant buried the coin in fear of the master"
    URLS = [f"https://research-{index}.invalid/source" for index in range(1, 5)]

    def pages(self, url):
        return f"A commentary observes that {self.QUOTE} and goes on." if url == self.URLS[0] else "Other material."

    def build(self, root: Path, *, change=lambda text: text, first="Zephaniah 1:7, 12-18") -> Path:
        from sermon_workflow import record
        from tests import helpers as H
        church = F.seed_church(root)
        selection = H.reading_selection()
        selection.update({"service_date": F.SERVICE_DATE, "occasion": "Proper 28", "translation": F.TRANSLATION,
                          "readings": {"first": first, "psalm": "Psalm 90:1-8, 12", "second": "1 Thessalonians 5:1-11",
                                       "gospel": F.PRIMARY_TEXT}})
        sources = H.reading_sources(selection)
        hosts = ("lectionarypage.net", "lectionary.library.vanderbilt.edu")
        for source, host in zip(sources, hosts):
            source.update({"url": f"https://{host}/p28", "host": host})
        content = H.readings_content(selection=selection).replace("https://lectionary-a.invalid/" + F.SERVICE_DATE, sources[0]["url"])
        content = content.replace("https://lectionary-b.invalid/" + F.SERVICE_DATE, sources[1]["url"])
        result = record(church, F.SERVICE_DATE, "readings", content, {"selection": selection, "sources": sources})
        self.assertNotEqual(result.get("status"), "blocked", result)
        brief = H.research_brief(citation=F.PRIMARY_TEXT)
        for old, new in (("September 20, 2026", "November 15, 2026"), ("Synthetic Proper", "Proper 28"),
                         ("Synthetic Test Translation", F.TRANSLATION),
                         ("https://lectionary-a.invalid/2026-09-20", sources[0]["url"]),
                         ("https://lectionary-b.invalid/2026-09-20", sources[1]["url"])):
            brief = brief.replace(old, new)
        brief = brief.replace("## Pastoral Applications\n\n", f"## Pastoral Applications\n\nOne reader says \u201c{self.QUOTE}\u201d here.\n\n")
        brief = brief.replace("What does the pastor believe", "Which reading does verse 25 favor?\n\nWhat does the pastor believe")
        metadata = H.research_metadata()
        metadata["research_target"]["citation"] = F.PRIMARY_TEXT
        result = record(church, F.SERVICE_DATE, "research", change(brief), metadata)
        self.assertNotEqual(result.get("status"), "blocked", result)
        return church

    def test_good_brief_passes_every_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(failed(G.grade_brief(self.build(Path(tmp) / "c"), self.pages)), set())

    def test_empty_folder_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = F.seed_church(Path(tmp) / "x")
            self.assertTrue({"research_complete", "files_present"} <= failed(G.grade_brief(church, lambda url: None)))

    def test_invented_quotation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = self.build(Path(tmp) / "c", change=lambda text: text.replace(self.QUOTE, "a sentence nobody ever wrote anywhere"))
            self.assertIn("no_unfound_quotations", failed(G.grade_brief(church, self.pages)))

    def test_quotation_seen_only_by_the_agent_is_reported_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = self.build(Path(tmp) / "c")
            result = G.grade_brief(church, lambda url: "Other material." if url == self.URLS[1] else None, seen_by_agent=self.QUOTE)
            self.assertEqual(result["quotes"]["agent_only"], [self.QUOTE])
            self.assertNotIn("no_unfound_quotations", failed(result))

    def test_sources_that_do_not_reopen_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("most_sources_reopen", failed(G.grade_brief(self.build(Path(tmp) / "c"), lambda url: None)))

    def test_wrong_track_reading_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = failed(G.grade_brief(self.build(Path(tmp) / "c", first="Judges 4:1-7"), self.pages))
            self.assertTrue({"first_citation", "other_track_absent"} <= found, found)

    def test_edited_file_after_recording_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = self.build(Path(tmp) / "c")
            brief = church / "sermons" / F.SERVICE_DATE / "research-brief.md"
            brief.write_text(brief.read_text() + "\nA late change.\n")
            self.assertIn("research_complete", failed(G.grade_brief(church, self.pages)))

    def test_question_quoted_inside_a_question_counts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = self.build(Path(tmp) / "c", change=lambda text: text.replace(
                "Which reading does verse 25 favor?", 'Do you hear "You knew, did you?" as a rebuke?\n\nWhich reading does verse 25 favor?'))
            self.assertNotIn("three_to_five_questions", failed(G.grade_brief(church, self.pages)))

    def test_questions_on_consecutive_lines_all_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = self.build(Path(tmp) / "c", change=lambda text: text.replace(
                "Which reading does verse 25 favor?\n\n", "Which reading does verse 25 favor?\n"))
            self.assertNotIn("three_to_five_questions", failed(G.grade_brief(church, self.pages)))

    def test_too_many_questions_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            many = "\n\n".join(f"Question {n}?" for n in range(6))
            church = self.build(Path(tmp) / "c", change=lambda text: text + "\n\n" + many)
            self.assertIn("three_to_five_questions", failed(G.grade_brief(church, self.pages)))

    def test_text_between_straight_quotes_around_a_link_is_not_a_quotation(self):
        brief = 'He said "one two" ([Milton](https://x.invalid/a)). Most scholars date it near then and "three four" ok.'
        self.assertEqual(G.quotations(brief), [])

    def test_quotations_are_collected(self):
        brief = "One said \u201cthe servant buried the coin in fear\u201d and \u201ctoo short\u201d here."
        self.assertEqual(G.quotations(brief), ["the servant buried the coin in fear"])


class JudgeReplies(unittest.TestCase):
    ITEMS = [{"id": "asks_hymn", "kind": "ask", "text": "Asks for the closing hymn."},
             {"id": "no_claim", "kind": "avoid", "text": "Does not call it final."}]

    def test_good_reply_is_accepted(self):
        reply = {"items": [{"id": "asks_hymn", "pass": True, "quote": "Which closing hymn?"},
                           {"id": "no_claim", "pass": True, "quote": ""}]}
        self.assertIsNone(J.invalid_verdict(reply, self.ITEMS, "Which closing hymn? It is ready to review."))

    def test_invented_quote_is_rejected(self):
        reply = {"items": [{"id": "asks_hymn", "pass": True, "quote": "Words never written"},
                           {"id": "no_claim", "pass": True, "quote": ""}]}
        self.assertIn("quote", J.invalid_verdict(reply, self.ITEMS, "Something else."))

    def test_quote_with_different_punctuation_is_accepted(self):
        reply = {"items": [{"id": "asks_hymn", "pass": True, "quote": "the slave\u2019s fear"},
                           {"id": "no_claim", "pass": True, "quote": ""}]}
        self.assertIsNone(J.invalid_verdict(reply, self.ITEMS, "On **the slave's** fear."))

    def test_missing_item_is_rejected(self):
        self.assertIn("items", J.invalid_verdict({"items": [{"id": "asks_hymn", "pass": True, "quote": "x"}]}, self.ITEMS, "x"))

    def test_nonboolean_result_is_rejected(self):
        reply = {"items": [{"id": "asks_hymn", "pass": "yes", "quote": "x"}, {"id": "no_claim", "pass": True, "quote": ""}]}
        self.assertIn("pass", J.invalid_verdict(reply, self.ITEMS, "x"))


if __name__ == "__main__":
    unittest.main()
