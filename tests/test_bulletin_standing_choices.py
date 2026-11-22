"""Standing choices, carry-forward and adopting an approval made outside the skill."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from skills.bulletin.bulletin_production import standing

REPO = Path(__file__).resolve().parents[1]


def write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
    return path


def advent_one_config() -> dict:
    return {
        "template": "modern",
        "service": {"date": "2026-11-29", "occasion": "The First Sunday of Advent", "preacher": "Jordan Reyes",
                    "celebrant": "The Rev. Pat Okafor", "liturgical_color": "violet", "time": "11:00 am"},
        "readings": {"first": {"citation": "Isaiah 64:1-9"}},
        "collect_of_day": {"text": "Almighty God, give us grace"},
        "hymns": {"entrance": {"number": 68, "title": "Rejoice! rejoice, believers"}},
        "liturgy": {"dismissal_speaker": "Deacon"},
        "after_gospel": {"speaker": "Together", "text": "Rejoice! Rejoice! Emmanuel"},
        "announcements": [
            {"title": "Advent and AI", "text": "Sundays, December 6, 13 and 20.", "until": "2026-12-20"},
            {"title": "Thanksgiving pie sale", "text": "After the service.", "until": "2026-11-29"},
            {"title": "Cozy Christmas Cabaret", "text": "December 14."},
        ],
        "options": {"merge_back_page": True},
        "selected_parts": {"collect": "x"}, "service_context": {"legacy": True}, "choice_origins": {},
    }


def approve_week(root: Path, config: dict, run_id: str = "run-a1") -> Path:
    folder = root / "bulletins/2026/11/2026-11-29-the-first-sunday-of-advent"
    write(folder / "bulletin-config.json", config)
    write(folder / "bulletin-production-receipt.json", {
        "run_id": run_id, "service_date": config["service"]["date"],
        "artifacts": [{"role": "sequential_pdf", "path": f"{folder.relative_to(root)}/bulletin-2026-11-29-modern.pdf"}]})
    return folder


class SeasonTest(unittest.TestCase):
    def test_each_season_ends_on_its_last_day(self):
        self.assertEqual(standing.easter(2027), date(2027, 3, 28))
        self.assertEqual(standing.advent_sunday(2026), date(2026, 11, 29))
        self.assertEqual(standing.advent_sunday(2027), date(2027, 11, 28))
        for sunday, end in (("2026-12-06", "2026-12-24"), ("2026-12-27", "2027-01-05"), ("2027-01-10", "2027-02-09"),
                            ("2027-02-14", "2027-03-27"), ("2027-04-04", "2027-05-16"), ("2027-06-06", "2027-11-27")):
            self.assertEqual(standing.season_end(date.fromisoformat(sunday)).isoformat(), end, sunday)


class StandingChoicesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_a_kept_answer_applies_until_it_ends_and_a_sunday_answer_is_never_kept(self):
        sunday = date(2026, 12, 6)
        self.assertEqual(standing.keep(self.root, key="preacher", question="Who preaches?", answer="John", keep="sunday",
                                       sunday=sunday), {"status": "ok", "kept": False})
        standing.keep(self.root, key="dismissal", question="Who says the dismissal?", answer="The Deacon", keep="always", sunday=sunday)
        standing.keep(self.root, key="after-gospel", question="Sing the refrain after the Gospel?", answer="Yes", keep="season", sunday=sunday)
        self.assertEqual([c["key"] for c in standing.applicable(self.root, date(2026, 12, 20))], ["after-gospel", "dismissal"])
        self.assertEqual([c["key"] for c in standing.applicable(self.root, date(2027, 1, 3))], ["dismissal"])

    def test_keeping_again_replaces_the_earlier_answer(self):
        sunday = date(2026, 12, 6)
        standing.keep(self.root, key="dismissal", question="Who says the dismissal?", answer="The Deacon", keep="always", sunday=sunday)
        standing.keep(self.root, key="dismissal", question="Who says the dismissal?", answer="The Priest", keep="always", sunday=sunday)
        self.assertEqual([c["answer"] for c in standing.applicable(self.root, sunday)], ["The Priest"])

    def test_bad_keys_and_keeps_are_refused(self):
        for bad in ({"key": "Bad Key", "keep": "always"}, {"key": "ok", "keep": "forever"}):
            with self.assertRaises(standing.StandingError):
                standing.keep(self.root, question="q", answer="a", sunday=date(2026, 12, 6), **bad)


class CarryForwardTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.folder = approve_week(self.root, advent_one_config())
        standing.adopt(self.root, self.folder, approved_by="The Rev. Pat Okafor")

    def test_next_week_starts_from_last_week_with_the_date_s_parts_cleared(self):
        result = standing.carry_forward(self.root, date(2026, 12, 6))
        draft = json.loads((self.root / result["draft_input"]).read_text(encoding="utf-8"))
        self.assertEqual(draft["service"], {"date": "2026-12-06", "celebrant": "The Rev. Pat Okafor", "time": "11:00 am"})
        for gone in standing.DATE_DECIDES:
            self.assertNotIn(gone, draft)
        self.assertEqual(draft["liturgy"], {"dismissal_speaker": "Deacon"})
        self.assertEqual(draft["after_gospel"]["text"], "Rejoice! Rejoice! Emmanuel")
        self.assertEqual(draft["options"], {"merge_back_page": True})
        self.assertEqual(draft["carried_from"]["date"], "2026-11-29")

    def test_a_notice_carries_while_its_date_holds_and_an_undated_one_is_asked(self):
        result = standing.carry_forward(self.root, date(2026, 12, 6))
        draft = json.loads((self.root / result["draft_input"]).read_text(encoding="utf-8"))
        self.assertEqual([n["title"] for n in draft["announcements"]], ["Advent and AI"])
        self.assertEqual(result["dropped_notices"], ["Thanksgiving pie sale"])
        notices = next(ask for ask in result["asks"] if ask["id"] == "notices")
        self.assertIn("Cozy Christmas Cabaret", notices["options"])

    def test_who_preaches_is_asked_unless_a_kept_answer_names_them(self):
        asks = standing.carry_forward(self.root, date(2026, 12, 6), write=False)["asks"]
        preacher = next(ask for ask in asks if ask["id"] == "preacher")
        self.assertTrue(preacher["weekly"])
        self.assertEqual(preacher["options"], ["Jordan Reyes"])
        standing.keep(self.root, key="preacher", question="Who preaches?", answer="The Rev. Pat Okafor",
                      keep="season", sunday=date(2026, 12, 6))
        result = standing.carry_forward(self.root, date(2026, 12, 6), write=False)
        self.assertEqual(result["draft"]["service"]["preacher"], "The Rev. Pat Okafor")
        self.assertFalse(any(ask["id"] == "preacher" for ask in result["asks"]))

    def test_nothing_approved_means_nothing_carried(self):
        self.assertIsNone(standing.carry_forward(Path(tempfile.mkdtemp()), date(2026, 12, 6))["carried_from"])

    def test_a_later_bulletin_never_carries_into_an_earlier_sunday(self):
        self.assertIsNone(standing.carry_forward(self.root, date(2026, 11, 29))["carried_from"])


class CheckCarriedTest(unittest.TestCase):
    def test_dropping_a_carried_part_is_refused_unless_named(self):
        root = Path(tempfile.mkdtemp())
        standing.adopt(root, approve_week(root, advent_one_config()), approved_by="x")
        draft = json.loads((root / standing.carry_forward(root, date(2026, 12, 6))["draft_input"]).read_text(encoding="utf-8"))
        standing.check_carried(root, draft)   # the draft itself passes
        without = {key: value for key, value in draft.items() if key != "after_gospel"}
        with self.assertRaises(standing.StandingError) as refused:
            standing.check_carried(root, without)
        self.assertEqual(refused.exception.code, "carried_part_dropped")
        self.assertIn("after_gospel", str(refused.exception))
        standing.check_carried(root, {**without, "dropped_from_last_week": ["after_gospel"]})
        no_deacon = {**draft, "liturgy": {}}
        with self.assertRaises(standing.StandingError) as liturgy:
            standing.check_carried(root, no_deacon)
        self.assertIn("liturgy.dismissal_speaker", str(liturgy.exception))
        no_acclamation = {**draft, "hymns": {}}
        with self.assertRaises(standing.StandingError) as hymns:
            standing.check_carried(root, no_acclamation)
        self.assertIn("hymns.entrance", str(hymns.exception))

    def test_no_draft_means_no_check(self):
        standing.check_carried(Path(tempfile.mkdtemp()), {"service": {"date": "2026-12-06"}})


class AdoptTest(unittest.TestCase):
    def test_adopting_records_history_once_and_never_over_a_skill_approval(self):
        root = Path(tempfile.mkdtemp())
        folder = approve_week(root, advent_one_config())
        result = standing.adopt(root, folder, approved_by="The Rev. Pat Okafor", note="Approved in chat")
        self.assertEqual(result["status"], "ok")
        entry = json.loads((root / "bulletins/bulletin-log.json").read_text(encoding="utf-8"))[result["adopted"]]
        self.assertEqual(entry["evidence_label"], "adopted_approval")
        self.assertEqual(entry["package"], folder.relative_to(root).as_posix())
        with self.assertRaises(standing.StandingError) as again:
            standing.adopt(root, folder, approved_by="x")
        self.assertEqual(again.exception.code, "approved_history_conflict")
        write(folder / "bulletin-approval-receipt.json", {})
        with self.assertRaises(standing.StandingError) as approved:
            standing.adopt(root, folder, approved_by="x")
        self.assertEqual(approved.exception.code, "already_approved")


class CommandLineTest(unittest.TestCase):
    def test_keep_and_standing_run_from_the_command_line(self):
        root = Path(tempfile.mkdtemp())
        script = REPO / "skills/bulletin/scripts/bulletin_production.py"
        kept = subprocess.run([sys.executable, str(script), "keep", "--church-folder", str(root), "--date", "2026-12-06",
                               "--key", "dismissal", "--question", "Who says the dismissal?", "--answer", "The Deacon",
                               "--keep", "always"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(kept.returncode, 0, kept.stderr)
        listed = subprocess.run([sys.executable, str(script), "standing", "--church-folder", str(root), "--date", "2026-12-06"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(listed.stdout)["choices"][0]["answer"], "The Deacon")


if __name__ == "__main__":
    unittest.main()
