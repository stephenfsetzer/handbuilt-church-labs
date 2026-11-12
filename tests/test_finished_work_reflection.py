"""The sermon reflection grader must pass good work and fail each kind of bad work.

No model runs here. The invented church gets its research through the real research
workflow, then the real reflection workflow opens the page, records done and the edit,
and renders the speaker's copy. Each test damages one thing.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "evals" / "finished_work"), str(REPO / "skills" / "sermon-research")]

try:
    import weasyprint  # noqa: F401
    HAS_RENDERER = shutil.which("pdftotext") is not None and shutil.which("pdffonts") is not None
except (ImportError, OSError):
    HAS_RENDERER = False

import case_reflection as R  # noqa: E402
import cases as C  # noqa: E402
import fixtures as F  # noqa: E402

PURPOSE = "I want them to feel trusted, not tested. And I want them to do one brave thing this week with whatever they've been sitting on."
ANSWERS = [
    ("What grabbed you in this text?", "The third guy. He didn't steal it, he didn't lose a thing. That's the problem. "
                                       "He's the only one who played it safe and he gets the hardest words in the story."),
    ("Is there a story this reminds you of?", "Yes. My uncle Walt's hardware store, the summer I was sixteen. I'll tell it when I talk it through."),
    ("When people walk out on Sunday, what do you hope they feel, and what do you hope they do?", PURPOSE),
]
CONVERSATION = [{"who": "pastor", "text": R.PROMPT.format(church="/x/riverbend")}]
for question, answer in ANSWERS:
    CONVERSATION += [{"who": "assistant", "text": question}, {"who": "pastor", "text": answer}]
CONVERSATION += [
    {"who": "assistant", "text": "Your page is open. Talk as long as you like and I will write it down."},
    {"who": "pastor", "text": R.REFLECTIONS + "\n\n" + R.DONE_LINE},
    {"who": "assistant", "text": "Your sermon is saved. I corrected one Bible quotation."},
    {"who": "pastor", "text": "It sounds like me. Can you make me a speaker's copy? Big type, 18 point."},
    {"who": "assistant", "text": "Your speaker's copy is ready."},
]
SEED = "# Reflections for November 15\n\n" + "\n\n".join(f"{q}\n{a}" for q, a in ANSWERS) + "\n\nKeep writing.\n\n## Spoken, Thursday afternoon\n\n" + R.REFLECTIONS + "\n"

# A light edit: the opener dropped, the misremembered Bible wording fixed, everything else the pastor's.
EDIT = "# Keys, Not Report Cards\n\n**Text:** Matthew 25:14-30\n\n" + R.REFLECTIONS.replace(
    "Okay. Here goes, I'm just going to talk.\n\n", "").replace(
    "enter into my rest", "and he invites them into his joy")
REWRITE = """# Stewardship and Trust

The parable of the talents invites us to consider the nature of faithful stewardship. Each servant receives a portion of
the master's wealth according to ability, and two of them invest it wisely. The third, paralysed by anxiety, conceals it.

Theologians across the centuries have understood this narrative as a meditation on the gifts with which God endows every
believer. We are called not merely to preserve those gifts but to cultivate them, in confidence that divine generosity
exceeds every calculation of risk.

Consequently, the challenge before us this week is to examine where caution has quietly replaced courage, and to respond
with renewed commitment to the work of the kingdom, offering our abilities in service of others.
"""
INVENTED_PAGE = " ".join(["The deeper theme concerns covenantal stewardship as a lens for discipleship, inviting readers "
                          "toward generosity, accountability, vocation, and hope in every season of communal life."] * 1)


def failed(result: dict) -> set[str]:
    return {item["id"] for item in result["checks"] if not item["passed"]}


@unittest.skipUnless(HAS_RENDERER, "needs the managed runtime and poppler")
class ReflectionGrader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = R.seed(Path(cls.tmp.name) / "seeded")
        cls.flow = R._reflection()
        cls.good = cls.build(Path(cls.tmp.name) / "good")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def build(cls, root: Path, *, seed=SEED, purpose=PURPOSE, sermon=EDIT, size=18, copy=True, earlier="") -> Path:
        """Run the real reflection workflow on a copy of the seeded church."""
        church = root / "riverbend"
        shutil.copytree(cls.base, church)
        work = root / "work"
        work.mkdir()
        (work / "seed.md").write_text(seed, encoding="utf-8")
        cls.flow.open_page(church, F.SERVICE_DATE, "in_app", None, str(work / "seed.md"))
        cls.flow.done(church, F.SERVICE_DATE, None, purpose)
        for number, text in enumerate([earlier, sermon] if earlier else [sermon]):
            (work / f"sermon-{number}.md").write_text(text, encoding="utf-8")
            assert cls.flow.record(church, F.SERVICE_DATE, str(work / f"sermon-{number}.md"), False)["status"] == "ok"
            if copy and (earlier and number == 0 or not earlier):
                cls.flow.speaker_copy(church, F.SERVICE_DATE, size)
        return church

    def grade(self, church: Path, conversation=CONVERSATION) -> set[str]:
        return failed(R.grade_reflection(church, conversation))

    def damaged(self, **change) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return self.grade(self.build(Path(tmp), **change))

    def changed_after(self, edit) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            church = Path(tmp) / "riverbend"
            shutil.copytree(self.good, church)
            edit(church / R.SERMON_DIR)
            return self.grade(church)

    def test_good_work_passes_every_check(self):
        result = R.grade_reflection(self.good, CONVERSATION)
        self.assertEqual(failed(result), set(), [c for c in result["checks"] if not c["passed"]])

    def test_empty_folder_fails(self):
        self.assertIn("sermon_saved", self.grade(self.base))

    def test_pastor_who_never_spoke_fails(self):
        self.assertIn("pastor_gave_reflections", self.grade(self.good, CONVERSATION[:7]))

    def test_rewritten_sermon_fails(self):
        found = self.damaged(sermon=REWRITE)
        self.assertTrue({"mostly_pastor_words", "keeps_pastor_phrases", "pastor_story_kept"} <= found, found)

    def test_dropping_the_pastors_lines_fails(self):
        sermon = EDIT.replace("Fear is a terrible accountant. ", "").replace("God hands out keys, not report cards.", "")
        self.assertIn("keeps_pastor_phrases", self.damaged(sermon=sermon))

    def test_cutting_the_pastors_story_fails(self):
        story = R.REFLECTIONS.split("\n\n")[4]
        self.assertIn("Walt", story)
        self.assertIn("pastor_story_kept", self.damaged(sermon=EDIT.replace(story, "")))

    def test_invented_personal_story_fails(self):
        sermon = EDIT.replace("I know that fear.", "When I was a boy my grandmother kept a jar of buttons that nobody was allowed to touch. I know that fear.")
        self.assertIn("no_untraceable_personal_story", self.damaged(sermon=sermon))

    def test_the_churchs_saved_name_is_not_an_invention(self):
        sermon = EDIT.replace("**Text:** Matthew 25:14-30", "*Proper 28, Riverbend Episcopal Church*")
        self.assertNotIn("no_new_names", self.damaged(sermon=sermon))

    def test_invented_person_fails(self):
        sermon = EDIT.replace("I know that fear.", "Ask Margaret Hale what that felt like. I know that fear.")
        self.assertIn("no_new_names", self.damaged(sermon=sermon))

    def test_misremembered_scripture_left_in_fails(self):
        self.assertIn("misquote_fixed", self.damaged(sermon=EDIT.replace("and he invites them into his joy", "enter into my rest")))

    def test_tidied_page_fails(self):
        tidy = SEED.replace(R.REFLECTIONS, "The pastor reflected on fear, the third servant, and a summer job at a hardware store.")
        self.assertIn("page_holds_pastor_words", self.damaged(seed=tidy))

    def test_page_with_added_material_fails(self):
        self.assertIn("page_not_invented", self.damaged(seed=SEED + "\n\n" + "\n\n".join([INVENTED_PAGE] * 12) + "\n"))

    def test_purpose_in_the_agents_words_fails(self):
        found = self.damaged(purpose="To help the congregation grasp a theology of stewardship and courageous discipleship.")
        self.assertIn("purpose_in_pastor_words", found)

    def test_page_changed_after_done_fails(self):
        def edit(folder):
            page = folder / "reflections.md"
            page.write_text(page.read_text(encoding="utf-8").replace("Fishing! On a Tuesday! ", ""), encoding="utf-8")
        self.assertIn("edit_recorded_after_done", self.changed_after(edit))

    def test_sermon_changed_after_the_recorded_edit_fails(self):
        def edit(folder):
            sermon = folder / "sermon.md"
            sermon.write_text(sermon.read_text(encoding="utf-8") + "\nA line nobody recorded.\n", encoding="utf-8")
        self.assertIn("edit_recorded_after_done", self.changed_after(edit))

    def test_changed_research_fails(self):
        def edit(folder):
            brief = folder / "research-brief.md"
            brief.write_text(brief.read_text(encoding="utf-8") + "\nA late note.\n", encoding="utf-8")
        self.assertIn("research_unchanged", self.changed_after(edit))

    def test_missing_speaker_copy_fails(self):
        self.assertIn("speaker_copy_present", self.damaged(copy=False))

    def test_small_type_fails(self):
        self.assertIn("speaker_copy_large_type", self.damaged(size=12))

    def test_type_smaller_than_asked_fails(self):
        self.assertIn("speaker_copy_large_type", self.damaged(size=16))

    def test_speaker_copy_from_an_earlier_draft_fails(self):
        earlier = EDIT.split("So what are you sitting on?")[0]
        self.assertIn("speaker_copy_matches_sermon", self.damaged(earlier=earlier))

    def test_no_speaker_copy_needed_when_not_asked(self):
        quiet = [dict(t, text=t["text"].replace("Can you make me a speaker's copy? Big type, 18 point.", "")) for t in CONVERSATION]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.grade(self.build(Path(tmp), copy=False), quiet), set())


class ReflectionCaseParts(unittest.TestCase):
    def test_case_is_registered(self):
        self.assertIn("reflection", C.load())

    def test_persona_carries_every_graded_phrase_and_story_marker(self):
        for phrase in R.PHRASES:
            self.assertTrue(R.phrase_kept(phrase, R.REFLECTIONS), phrase)
        for marker in R.STORY_MARKERS:
            self.assertIn(marker, R.REFLECTIONS)
        self.assertIn(R.MISQUOTE, R.REFLECTIONS)
        self.assertIn(R.REFLECTIONS, R.PERSONA)

    def test_names_at_the_start_of_a_sentence_are_not_flagged(self):
        self.assertEqual(R.new_names("Margaret came by. Then we talked.", ""), [])
        self.assertEqual(R.new_names("Then Margaret came by.", ""), ["Margaret"])
        self.assertEqual(R.new_names("Then Walt came by.", "my uncle Walt"), [])

    def test_requested_size_is_read_from_the_pastor(self):
        self.assertEqual(R.requested_points("Big type, 18 point."), 18.0)
        self.assertEqual(R.requested_points("Big type please."), R.LARGE_TYPE)

    def test_nothing_written_here_uses_long_dashes(self):
        for text in (R.PERSONA, R.BRIEF, R.PROMPT, Path(R.__file__).read_text(encoding="utf-8")):
            self.assertNotRegex(text, "[–—]")


if __name__ == "__main__":
    unittest.main()
