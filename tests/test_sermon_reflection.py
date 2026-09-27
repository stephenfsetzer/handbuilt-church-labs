"""Sermon reflection: the pastor writes, the agent edits.

The contracts under test: the pastor's page is never rewritten, the edit waits
for the pastor's "done," the pastor's own changes to the sermon are protected,
and the kept-from-pastor measure reports how much of the pastor survives.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import church_workflow as bridge
from tests.helpers import make_church

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "skills/sermon-reflection/scripts/sermon_reflection.py"
_spec = importlib.util.spec_from_file_location("sermon_reflection", ENTRY)
reflection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reflection)

DATE = "2026-10-04"
PAGE = """# Reflections for October 4

What grabbed you?
I keep coming back to the line about the vineyard owner who kept sending people.
He never gave up on the tenants even when they were at their worst!

What do you hope people feel and do?
I want them to leave knowing they are not too far gone. I want them to call someone they have been avoiding.

Keep writing.
When I was a kid my grandmother kept a garden that nobody else wanted to tend.
She said a garden forgives you if you come back to it.
"""
EDIT = """# The Owner Who Kept Sending

I keep coming back to the line about the vineyard owner who kept sending people.
He never gave up on the tenants even when they were at their worst!

When I was a kid my grandmother kept a garden that nobody else wanted to tend.
She said a garden forgives you if you come back to it.

So here is what I want you to know this morning. You are not too far gone.
And this week, call someone you have been avoiding.
"""


def run(church: Path, operation: str, *args: str) -> tuple[dict, int]:
    process = subprocess.run(
        [sys.executable, str(ENTRY), operation, "--church-folder", str(church), "--date", DATE, *args],
        capture_output=True, text=True, cwd=church)
    return json.loads(process.stdout), process.returncode


class SermonReflectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = make_church(Path(self.temp.name))
        self.sermon_dir = self.church / "sermons" / DATE
        self.work = Path(self.temp.name) / "work"
        self.work.mkdir()

    def file(self, name: str, text: str) -> str:
        path = self.work / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def open_and_finish(self) -> None:
        run(self.church, "open", "--seed-file", self.file("seed.md", PAGE))
        run(self.church, "done", "--purpose", "Leave hopeful and call someone.")

    def test_a_new_sermon_starts_by_drawing_out_the_pastor(self):
        result, code = run(self.church, "orient")
        self.assertEqual(code, 0)
        self.assertEqual(result["workflow_state"], "draw_out")
        self.assertEqual(result["next_actions"], ["draw_out", "open_page"])
        self.assertIn("research_not_complete", [w["code"] for w in result["warnings"]])
        self.assertFalse(self.sermon_dir.exists(), "orient must not write anything")

    def test_opening_the_page_seeds_it_once_and_then_waits(self):
        result, code = run(self.church, "open", "--seed-file", self.file("seed.md", PAGE))
        self.assertEqual((code, result["created"]), (0, True))
        page = self.sermon_dir / "reflections.md"
        self.assertEqual(page.read_text(), PAGE)
        page.write_text(PAGE + "More of my own writing.\n")
        result, _ = run(self.church, "open", "--seed-file", self.file("other.md", "Replacement\n"))
        self.assertFalse(result["created"])
        self.assertTrue(page.read_text().endswith("More of my own writing.\n"))
        state, _ = run(self.church, "orient")
        self.assertEqual((state["workflow_state"], state["next_actions"]), ("pastor_writing", []))

    def test_the_edit_waits_for_the_pastor_to_say_done(self):
        run(self.church, "open", "--seed-file", self.file("seed.md", PAGE))
        result, code = run(self.church, "record", "--content-file", self.file("edit.md", EDIT))
        self.assertEqual((code, result["code"]), (1, "pastor_not_done"))
        self.assertFalse((self.sermon_dir / "sermon.md").exists())

    def test_done_then_edit_keeps_the_page_and_reports_what_was_kept(self):
        self.open_and_finish()
        state, _ = run(self.church, "orient")
        self.assertEqual(state["workflow_state"], "ready_to_edit")
        self.assertEqual(state["purpose"], "Leave hopeful and call someone.")
        result, code = run(self.church, "record", "--content-file", self.file("edit.md", EDIT))
        self.assertEqual(code, 0)
        self.assertEqual((self.sermon_dir / "sermon.md").read_text(), EDIT)
        self.assertEqual((self.sermon_dir / "reflections.md").read_text(), PAGE)
        kept = result["kept_from_pastor"]
        self.assertGreater(kept["share"], 0.6)
        self.assertEqual(kept["words"], len(EDIT.replace("#", "").split()))
        self.assertNotIn("warnings", result)
        state, _ = run(self.church, "orient")
        self.assertEqual((state["workflow_state"], state["next_actions"]), ("edited", ["speaker_copy"]))

    def test_changing_the_page_after_done_blocks_the_edit_until_done_again(self):
        self.open_and_finish()
        page = self.sermon_dir / "reflections.md"
        page.write_text(PAGE + "One more thought.\n")
        state, _ = run(self.church, "orient")
        self.assertEqual(state["workflow_state"], "pastor_writing")
        self.assertIn("page_changed_after_done", [w["code"] for w in state["warnings"]])
        result, code = run(self.church, "record", "--content-file", self.file("edit.md", EDIT))
        self.assertEqual((code, result["code"]), (1, "page_changed_after_done"))
        run(self.church, "done")
        state, _ = run(self.church, "orient")
        self.assertEqual(state["workflow_state"], "ready_to_edit")
        self.assertEqual(state["purpose"], "Leave hopeful and call someone.")

    def test_the_pastors_changes_to_the_sermon_are_protected(self):
        self.open_and_finish()
        run(self.church, "record", "--content-file", self.file("edit.md", EDIT))
        sermon = self.sermon_dir / "sermon.md"
        sermon.write_text(EDIT + "A line the pastor added.\n")
        state, _ = run(self.church, "orient")
        self.assertIn("pastor_edited_sermon", [w["code"] for w in state["warnings"]])
        result, code = run(self.church, "record", "--content-file", self.file("edit2.md", EDIT))
        self.assertEqual((code, result["code"]), (1, "sermon_changed_by_pastor"))
        self.assertTrue(sermon.read_text().endswith("A line the pastor added.\n"))
        result, code = run(self.church, "record", "--content-file", self.file("edit2.md", EDIT), "--replace")
        self.assertEqual(code, 0)
        kept = Path(result["previous_version"]).read_text()
        self.assertTrue(kept.endswith("A line the pastor added.\n"))

    def test_writing_done_elsewhere_is_added_to_the_end_of_the_page(self):
        result, code = run(self.church, "open", "--where", "elsewhere")
        self.assertEqual((code, result["code"]), (1, "place_missing"))
        run(self.church, "open", "--where", "elsewhere", "--place", "my notes app")
        self.assertFalse((self.sermon_dir / "reflections.md").exists())
        state, _ = run(self.church, "orient")
        self.assertEqual((state["workflow_state"], state["place"]), ("pastor_writing", "my notes app"))
        result, code = run(self.church, "done", "--from-file", self.file("notes.md", PAGE))
        self.assertEqual(code, 0)
        page = self.sermon_dir / "reflections.md"
        self.assertEqual(page.read_text(), PAGE)
        run(self.church, "done", "--from-file", self.file("more.md", "Second session.\n"))
        self.assertEqual(page.read_text(), PAGE.rstrip("\n") + "\n\n---\n\nSecond session.\n")

    def test_done_needs_something_on_the_page(self):
        result, code = run(self.church, "open", "--seed-file", self.file("blank.md", " \n"))
        self.assertEqual((code, result["code"]), (1, "empty_content"))
        run(self.church, "open", "--where", "elsewhere", "--place", "paper")
        result, code = run(self.church, "done")
        self.assertEqual((code, result["code"]), (1, "page_empty"))

    def test_a_heavy_rewrite_is_flagged(self):
        self.open_and_finish()
        rewrite = "Grace is the persistent pursuit of a patient God toward us.\n" \
                  "The parable invites us to consider our own resistance carefully.\n"
        result, code = run(self.church, "record", "--content-file", self.file("rewrite.md", rewrite))
        self.assertEqual(code, 0)
        self.assertLess(result["kept_from_pastor"]["share"], 0.3)
        self.assertEqual(result["warnings"][0]["code"], "mostly_rewritten")

    def test_kept_from_pastor_counts_word_runs_and_ignores_frontmatter(self):
        page = "---\ntitle: kept words here\n---\nThis is the pastor's own sentence here. Yes.\n"
        sermon = "---\nstatus: final\n---\nThis is the pastor's own sentence here! Amen, kept words here.\n"
        self.assertEqual(reflection.kept_from_pastor(page, sermon), {"words": 11, "kept": 7, "share": 0.64})
        reordered = "Here is the pastor's own sentence. This is it."
        self.assertEqual(reflection.kept_from_pastor(page, reordered)["kept"], 5)

    def test_speaker_copy_html_is_large_type_and_escaped(self):
        html = reflection.speaker_copy_html(
            "---\nstatus: final\n---\n# On <the> Night\n\n**Text:** Philippians 2:1-13\n\n"
            "Every Sunday we tell a *hard* story.\n\n> Christ has died.\n", DATE)
        self.assertIn("<h1>On &lt;the&gt; Night</h1>", html)
        self.assertIn("October 4, 2026", html)
        self.assertIn("font-size: 16pt", html)
        self.assertIn("<em>hard</em>", html)
        self.assertIn("<blockquote>Christ has died.</blockquote>", html)
        self.assertNotIn("status: final", html)

    def test_speaker_copy_renders_a_pdf_when_the_pdf_tools_exist(self):
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            self.skipTest("PDF tools are not installed in this Python")
        result, code = run(self.church, "speaker-copy")
        self.assertEqual((code, result["code"]), (1, "sermon_missing"))
        self.open_and_finish()
        run(self.church, "record", "--content-file", self.file("edit.md", EDIT))
        result, code = run(self.church, "speaker-copy")
        self.assertEqual(code, 0)
        self.assertGreaterEqual(result["pages"], 1)
        self.assertTrue((self.sermon_dir / "sermon-speaker-copy.pdf").read_bytes().startswith(b"%PDF"))

    def test_state_lives_where_research_receipts_do_not_read_it(self):
        self.open_and_finish()
        state_file = self.sermon_dir / ".receipts" / "reflection" / "state.json"
        self.assertTrue(state_file.is_file())
        self.assertEqual(list((self.sermon_dir / ".receipts").glob("*.json")), [])

    def test_launcher_runs_sermon_reflection_for_a_connected_church(self):
        self.assertIn("sermon-reflection", bridge.WORKFLOWS)
        self.assertNotIn("sermon-reflection", bridge.PDF_WORKFLOWS)
        doctor = {"status": "ready", "runtime": {"python": sys.executable}}
        with mock.patch.object(bridge, "_doctor", return_value=doctor):
            result, code = bridge.execute(self.church, "sermon-reflection", "orient", ["--date", DATE])
            self.assertEqual((result["workflow_state"], code), ("draw_out", 0))
            with self.assertRaises(ValueError):
                bridge.execute(self.church, "sermon-reflection", "orient", ["--church-folder=/tmp/another"])
            with self.assertRaises(ValueError):
                bridge.execute(self.church, "sermon-reflection", "delete", [])

    def test_packaging_registers_the_skill_for_both_hosts(self):
        for host in (".agents", ".claude"):
            pointer = (ROOT / host / "skills/sermon-reflection/SKILL.md").read_text()
            self.assertIn("skills/sermon-reflection/SKILL.md", pointer)
            self.assertLessEqual(len(pointer.splitlines()), 10)
        skill = (ROOT / "skills/sermon-reflection/SKILL.md").read_text()
        for promise in ("one question at a time", "voice", "reflections.md", "done", "speaker-copy"):
            self.assertIn(promise, skill)


if __name__ == "__main__":
    unittest.main()
