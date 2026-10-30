from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tests.helpers import make_church

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "build-my-website" / "scripts"))
sys.path.insert(0, str(ROOT))

import website_workflow  # noqa: E402
from website_workflow import change_request, check_score, critique, orient, record, score_problems  # noqa: E402
from tools import church_workflow as bridge  # noqa: E402

CLI = ROOT / "skills" / "build-my-website" / "scripts" / "website_workflow.py"
MEASURES = {"rounds": 1, "hours": {"agent": 1.5, "pastor": 0.5}}
WEB = {
    "idea": "A quiet frame so the seasons can be loud.",
    "house_style": "brand/art-direction.md",
    "slots": {"home_hero": {"changes": "Each season", "may_hold": ["the campaign"]},
              "announcement_band": {"changes": "Weekly", "may_hold": ["this week's notice"]}},
    "checks": ["contrast_aa", "one_h1"],
}
HOME = [
    {"section": "welcome", "job": "Say who we are", "lead": "photo", "photo": "photos/nave.jpg", "ground": "photo", "scale": "full", "layout": "full bleed"},
    {"section": "times", "job": "When to come", "lead": "number", "ground": "primary", "scale": "huge", "layout": "centered"},
    {"section": "notice", "job": "This week", "lead": "type", "ground": "paper", "scale": "medium", "layout": "split"},
]
VISIT = [
    {"section": "door", "job": "What to expect", "lead": "type", "ground": "paper", "scale": "large", "layout": "left"},
    {"section": "map", "job": "How to get here", "lead": "art", "ground": "deep", "scale": "medium", "layout": "split"},
    {"section": "ask", "job": "Ask a question", "lead": "form", "ground": "paper", "scale": "small", "layout": "centered"},
]


class BuildMyWebsiteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.church = make_church(Path(self.temp.name))
        self._brand(schema_version=3, approved=True)
        (self.church / "brand").mkdir(exist_ok=True)
        (self.church / "brand" / "photo-ledger.json").write_text(json.dumps({"photos": [
            {"file": "photos/nave.jpg", "rating": "A", "consent": "yes", "people": False, "used_in": []},
            {"file": "photos/choir.jpg", "rating": "C", "consent": "ask", "people": True, "used_in": []},
            {"file": "photos/porch.jpg", "rating": "B", "consent": "ask", "people": True, "used_in": []},
        ], "gaps": ["The congregation at worship"]}))
        self.web = self.church / "website"
        (self.web / "harvest").mkdir(parents=True, exist_ok=True)
        (self.web / "screens").mkdir()
        for name in ("home", "visit", "pattern"):
            for width in (1440, 375):
                Image.new("RGB", (20, 20), "white").save(self.web / "screens" / f"{name}-{width}.png")

    def tearDown(self):
        self.temp.cleanup()

    def _brand(self, *, schema_version: int, approved: bool) -> None:
        path = self.church / "brand.json"
        brand = json.loads(path.read_text()) if path.is_file() else {}
        brand["brand_system"] = {"schema_version": schema_version, "web": WEB, "approved_on": "2026-10-01" if approved else None}
        if schema_version < 3:
            brand["brand_system"].pop("web")
        path.write_text(json.dumps(brand))

    def _meta(self, stage: str) -> dict:
        meta = dict(MEASURES)
        if stage in website_workflow.PASTOR_GATES:
            meta["approved_by"] = "The Rev. Test Pastor"
        if stage == "sitemap":
            (self.web / "sitemap.md").write_text("# Site map\n")
            meta["pages"] = [{"slug": "home", "title": "Home", "job": "Welcome", "audience": "Newcomers", "must_let_visitor": ["find the service time"]},
                             {"slug": "visit", "title": "Visit", "job": "Get someone in the door", "audience": "Newcomers", "must_let_visitor": ["plan a first visit"]}]
        if stage == "harvest":
            for page in ("home", "visit"):
                (self.web / "harvest" / f"{page}.md").write_text("Q and A\n")
            meta["sheets"] = {"home": {"status": "answered", "file": "website/harvest/home.md"},
                              "visit": {"status": "skipped", "file": "website/harvest/visit.md", "reason": "The pastor pointed to last year's newcomer letter"}}
            meta["mined"] = [{"quote": "Come as you are.", "source": "Newsletter, spring"}]
        if stage == "content":
            (self.web / "content.md").write_text("# Content\n")
            (self.web / "site-data.yaml").write_text("services:\n  - day: Sunday\n    time: '10:00'\naddress: 10 Test Lane\n")
            (self.web / "preview.html").write_text("<p>gray boxes</p>")
            meta["pages"] = {"home": [{"id": s["section"], "message": s["job"]} for s in HOME],
                             "visit": [{"id": s["section"], "message": s["job"]} for s in VISIT]}
            meta["preview"] = "website/preview.html"
        if stage == "scores":
            (self.web / "design-plan.md").write_text("# Scores\n")
            meta["scores"] = {"home": json.loads(json.dumps(HOME)), "visit": json.loads(json.dumps(VISIT))}
        if stage == "design":
            meta["pages"] = {p: {"screens": {str(w): f"website/screens/{p}-{w}.png" for w in (1440, 375)}, "patterns": ["full-bleed-welcome"]}
                             for p in ("home", "visit")}
            meta["patterns"] = [{"name": "full-bleed-welcome", "holds": "One A photo and a line of type",
                                 "screens": {str(w): f"website/screens/pattern-{w}.png" for w in (1440, 375)}}]
        return meta

    def _record_through(self, last: str) -> None:
        for stage in website_workflow.STAGES:
            if stage in {"scores", "design"}:
                for page in ("home", "visit"):
                    critique(self.church, stage, page, "pass", "Shifts hard twice; nothing near the edge.")
            result = record(self.church, stage, self._meta(stage))
            self.assertEqual(result["status"], "recorded", result)
            if stage == last:
                return

    def test_the_website_starts_only_from_an_approved_kit_with_its_web_layer(self):
        self._brand(schema_version=3, approved=False)
        self.assertEqual(orient(self.church)["errors"][0]["code"], "brand_kit_required")
        self._brand(schema_version=2, approved=True)
        blocked = orient(self.church)
        self.assertEqual(blocked["errors"][0]["code"], "web_layer_required")
        self.assertIn("How it looks everywhere", blocked["next_action"])
        self.assertEqual(record(self.church, "sitemap", self._meta("sitemap"))["errors"][0]["code"], "web_layer_required")
        self._brand(schema_version=3, approved=True)
        ready = orient(self.church)
        self.assertEqual(ready["next_stage"], "sitemap")
        self.assertEqual(ready["photos"], {"usable": 2, "gaps": ["The congregation at worship"]})

    def test_stages_run_in_order_and_record_rounds_and_hours(self):
        self.assertEqual(record(self.church, "content", self._meta("content"))["errors"][0]["code"], "stage_out_of_order")
        no_hours = self._meta("sitemap")
        no_hours.pop("hours")
        self.assertEqual(record(self.church, "sitemap", no_hours)["errors"][0]["code"], "hours_required")
        unapproved = self._meta("sitemap")
        unapproved.pop("approved_by")
        self.assertEqual(record(self.church, "sitemap", unapproved)["errors"][0]["field"], "approved_by")
        over = self._meta("sitemap")
        over["rounds"] = 4
        result = record(self.church, "sitemap", over)
        self.assertEqual(result["status"], "recorded", result)
        self.assertIn("budget of 2", result["warnings"][0])
        state = orient(self.church)
        self.assertEqual(state["stages"][0]["rounds"], 4)
        self.assertEqual(state["hours"], {"agent": 1.5, "pastor": 0.5})

    def test_every_approved_page_gets_a_question_sheet(self):
        self._record_through("sitemap")
        meta = self._meta("harvest")
        meta["sheets"].pop("visit")
        self.assertEqual(record(self.church, "harvest", meta)["errors"][0]["code"], "sheets_required")
        meta = self._meta("harvest")
        meta["mined"] = [{"quote": "Come as you are."}]
        self.assertEqual(record(self.church, "harvest", meta)["errors"][0]["code"], "sources_required")
        self.assertEqual(record(self.church, "harvest", self._meta("harvest"))["status"], "recorded")

    def test_content_covers_the_site_map_and_keeps_facts_in_one_place(self):
        self._record_through("harvest")
        meta = self._meta("content")
        meta["pages"].pop("visit")
        self.assertEqual(record(self.church, "content", meta)["errors"][0]["code"], "pages_required")
        (self.web / "site-data.yaml").write_text("")
        meta = self._meta("content")
        (self.web / "site-data.yaml").write_text("- just a list\n")
        self.assertEqual(record(self.church, "content", meta)["errors"][0]["code"], "invalid_site_data")

    def test_a_score_changes_gear_every_section_and_shifts_hard_twice(self):
        flat = [dict(HOME[1], section=f"s{i}") for i in range(3)]
        self.assertTrue(any("repeats" in p for p in score_problems(flat)))
        one_shift = [HOME[1], dict(HOME[1], section="b", layout="split"), dict(HOME[1], section="c", layout="left", ground="paper")]
        self.assertTrue(any("big shift" in p for p in score_problems(one_shift)))
        self.assertEqual(score_problems(HOME), [])
        self.assertEqual(check_score(self.church, {"home": HOME, "visit": VISIT})["status"], "pass")
        weak = json.loads(json.dumps(HOME))
        weak[0]["photo"] = "photos/choir.jpg"
        self.assertTrue(any("rated C" in p for p in check_score(self.church, {"home": weak})["photos"]))
        reused = json.loads(json.dumps(VISIT))
        reused[1]["photo"] = "photos/nave.jpg"
        self.assertTrue(any("two pages" in p for p in check_score(self.church, {"home": HOME, "visit": reused})["photos"]))
        no_consent = json.loads(json.dumps(VISIT))
        no_consent[1]["photo"] = "photos/porch.jpg"
        self.assertTrue(any("consent" in p for p in check_score(self.church, {"visit": no_consent})["photos"]))

    def test_scores_follow_the_approved_sections_and_need_the_critic(self):
        self._record_through("content")
        moved = self._meta("scores")
        moved["scores"]["home"] = [HOME[1], HOME[0], HOME[2]]
        self.assertEqual(record(self.church, "scores", moved)["errors"][0]["code"], "sections_changed")
        added = self._meta("scores")
        added["scores"]["visit"].append(dict(VISIT[0], section="extra"))
        self.assertEqual(record(self.church, "scores", added)["errors"][0]["code"], "sections_changed")
        self.assertEqual(record(self.church, "scores", self._meta("scores"))["errors"][0]["code"], "critic_required")
        critique(self.church, "scores", "home", "pass", "Good.")
        critique(self.church, "scores", "visit", "redirect", "Every section is the same split.", instead="Lead the map with art on the deep ground")
        blocked = record(self.church, "scores", self._meta("scores"))
        self.assertEqual(blocked["errors"][0]["detail"]["missing"], ["visit"])
        critique(self.church, "scores", "visit", "pass", "Fixed.")
        self.assertEqual(record(self.church, "scores", self._meta("scores"))["status"], "recorded")
        ledger = json.loads((self.church / "brand" / "photo-ledger.json").read_text())
        self.assertEqual(ledger["photos"][0]["used_in"], ["home"])
        self.assertEqual(orient(self.church)["redirects"], 1)

    def test_design_is_home_and_one_inside_page_built_from_named_patterns(self):
        self._record_through("scores")
        for page in ("home", "visit"):
            critique(self.church, "design", page, "pass", "Good.")
        unnamed = self._meta("design")
        unnamed["pages"]["visit"]["patterns"] = ["mystery"]
        self.assertEqual(record(self.church, "design", unnamed)["errors"][0]["code"], "pattern_unknown")
        no_phone = self._meta("design")
        no_phone["pages"]["home"]["screens"].pop("375")
        self.assertEqual(record(self.church, "design", no_phone)["errors"][0]["field"], "pages.home.screens.375")
        self.assertEqual(record(self.church, "design", self._meta("design"))["status"], "recorded")

    def test_an_approved_stage_is_frozen_until_a_change_request(self):
        self._record_through("scores")
        frozen = record(self.church, "content", self._meta("content"), replace=True)
        self.assertEqual(frozen["errors"][0]["code"], "change_request_required")
        opened = change_request(self.church, "content", "The pastor wants a newcomer section", "Add a Coming alone section to Visit")
        self.assertEqual(opened["change_request"]["stale"], ["scores"])
        self.assertEqual(orient(self.church)["next_stage"], "content")
        self.assertEqual(record(self.church, "design", self._meta("design"))["errors"][0]["code"], "stage_stale")
        meta = self._meta("content")
        meta["pages"]["visit"].append({"id": "alone", "message": "You won't sit alone"})
        self.assertEqual(record(self.church, "content", meta, replace=True)["status"], "recorded")
        self.assertEqual(orient(self.church)["next_stage"], "scores")
        rescore = self._meta("scores")
        rescore["scores"]["visit"].append(dict(VISIT[0], section="alone", ground="primary", scale="huge"))
        self.assertEqual(record(self.church, "scores", rescore)["errors"][0]["code"], "critic_required")
        for page in ("home", "visit"):
            critique(self.church, "scores", page, "pass", "Rechecked.")
        self.assertEqual(record(self.church, "scores", rescore)["status"], "recorded")

    def test_handoff_names_one_approver_and_proves_one_real_update(self):
        self._record_through("design")
        # A two-page site has nothing left after the design round, but the
        # pastor still sees the whole site once.
        rest = dict(self._meta("pages"), pages={}, patterns=[])
        self.assertEqual(record(self.church, "pages", rest)["errors"][0]["code"], "whole_site_required")
        self.assertEqual(record(self.church, "pages", dict(rest, whole_site_shown=True))["status"], "recorded")
        (self.web / "motion.md").write_text("# Motion\n")
        too_many = dict(self._meta("motion"), moments=[{"name": str(i), "reduced_motion": "still"} for i in range(4)])
        self.assertEqual(record(self.church, "motion", too_many)["errors"][0]["code"], "moments_required")
        self.assertEqual(record(self.church, "motion", dict(self._meta("motion"), moments=[{"name": "door opens", "reduced_motion": "shown open"}]))["status"], "recorded")
        failing = dict(self._meta("build"), site="website/site", checks={"contrast_aa": {"1440": "pass", "375": "fail"}, "one_h1": {"1440": "pass", "375": "pass"}})
        self.assertEqual(record(self.church, "build", failing)["errors"][0]["detail"]["failing"], ["contrast_aa"])
        passing = dict(failing, checks={c: {"1440": "pass", "375": "pass"} for c in WEB["checks"]})
        self.assertEqual(record(self.church, "build", passing)["status"], "recorded")
        (self.web / "maintain.md").write_text("# Keeping it up\n")
        (self.web / "volunteer-card.md").write_text("Ask the agent.\n")
        handoff = dict(self._meta("handoff"), volunteer_card="website/volunteer-card.md", approver="A. Warden",
                       slot_calendar={"home_hero": "Each season", "announcement_band": "Each Monday"},
                       first_update={"request": "Add the Advent schedule", "approved_by": "Someone else"})
        self.assertEqual(record(self.church, "handoff", handoff)["errors"][0]["code"], "first_update_required")
        handoff["first_update"]["approved_by"] = "A. Warden"
        handoff["slot_calendar"].pop("announcement_band")
        self.assertEqual(record(self.church, "handoff", handoff)["errors"][0]["code"], "slot_calendar_required")
        handoff["slot_calendar"]["announcement_band"] = "Each Monday"
        self.assertEqual(record(self.church, "handoff", handoff)["status"], "recorded")
        self.assertIsNone(orient(self.church)["next_stage"])

    def test_the_command_line_answers_in_json(self):
        result = subprocess.run([sys.executable, str(CLI), "orient", "--church-folder", str(self.church)], capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)["next_stage"], "sitemap")
        bad = subprocess.run([sys.executable, str(CLI), "record", "--church-folder", str(self.church), "--stage", "nope", "--metadata-file", "x"], capture_output=True, text=True)
        self.assertEqual(json.loads(bad.stdout)["errors"][0]["code"], "invalid_arguments")

    def test_the_launcher_runs_build_my_website_for_a_connected_church(self):
        self.assertIn("build-my-website", bridge.WORKFLOWS)
        self.assertNotIn("build-my-website", bridge.PDF_WORKFLOWS)
        doctor = {"status": "ready", "runtime": {"python": sys.executable}}
        with mock.patch.object(bridge, "_doctor", return_value=doctor):
            result, code = bridge.execute(self.church, "build-my-website", "orient", [])
            self.assertEqual((result["next_stage"], code), ("sitemap", 0))
            with self.assertRaises(ValueError):
                bridge.execute(self.church, "build-my-website", "publish", [])

    def test_the_skill_states_its_promises(self):
        skill = (ROOT / "skills" / "build-my-website" / "SKILL.md").read_text()
        for promise in ("site map", "gray-box", "change request", "critic", "approver", "site-data.yaml", "check-score"):
            self.assertIn(promise, skill)


if __name__ == "__main__":
    unittest.main()
