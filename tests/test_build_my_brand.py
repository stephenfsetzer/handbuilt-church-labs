from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.helpers import make_church

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "build-my-brand"))
sys.path.insert(0, str(ROOT / "skills" / "onboarding" / "scripts"))

import brand_setup  # noqa: E402
from brand_workflow import (  # noqa: E402
    DECISION_STAGES, DEVELOP_APPLICATIONS, DIRECTION_APPLICATIONS, INTERVIEW_KEYS, STAGES,
    approve, orient, record, render_guide, restart, stage_brand,
)
from brand_workflow.guide import markdown_to_html  # noqa: E402

CLI = ROOT / "skills" / "build-my-brand" / "scripts" / "brand_workflow.py"
MARK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor"><rect x="20" y="10" width="60" height="80"/></svg>'
SMALL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor"><circle cx="50" cy="50" r="42"/></svg>'
THIN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor"><rect x="49" y="10" width="2" height="80"/><rect x="10" y="49" width="80" height="2"/></svg>'
PHASES = [
    {"title": "Getting to know you", "stages": ["fork", "discover", "interview", "identity"],
     "you_see": "How you look today and the brief", "you_decide": "Refresh or new; one identity", "time": "One sitting"},
    {"title": "The idea", "stages": ["direction", "develop", "refine-1", "refine-2"],
     "you_see": "Two or three directions, then one developed and tightened", "you_decide": "The direction, the version, the mark", "time": "Three short sessions"},
    {"title": "The system", "stages": ["color", "type", "voice", "build", "prove"],
     "you_see": "The palette, type, voice, and your bulletin in the new brand", "you_decide": "Each, then approval", "time": "Two sessions"},
    {"title": "Keeping it", "stages": ["connect", "handoff"],
     "you_see": "Where the brand travels and the volunteer card", "you_decide": "Nothing", "time": "Half an hour"},
]


def _metadata(stage: str) -> dict:
    meta: dict = {}
    if stage == "roadmap":
        meta["phases"] = json.loads(json.dumps(PHASES))
    if stage in DECISION_STAGES:
        meta.update({"decision": f"{stage} choice", "rationale": f"Because the {stage} lesson showed why."})
        if stage == "fork":
            meta["decision"] = "new"
        elif stage in {"direction", "develop", "color", "type", "voice"}:
            meta["options"] = ["Option A", "Option B"]
    if stage == "discover":
        meta["sources"] = [{"label": "Public website", "kind": "website"}]
    if stage == "interview":
        meta["answers"] = {k: f"answer for {k}" for k in INTERVIEW_KEYS}
    if stage == "direction":
        meta["applications"] = list(DIRECTION_APPLICATIONS)
    if stage in {"develop", "refine-1", "refine-2"}:
        meta["applications"] = list(DEVELOP_APPLICATIONS)
        meta["boards"] = ["brand/staging/explorations/board.png"]
    if stage == "develop":
        meta["recommendation"] = "Option A, because it carries the direction's lines into the mark."
    if stage == "refine-2":
        meta["mark"] = {"primary": "brand/staging/marks/mark.svg"}
    return meta


class BuildMyBrandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.church = make_church(Path(self.temp.name))
        staging = self.church / "brand" / "staging"
        (staging / "explorations").mkdir(parents=True)
        (staging / "marks").mkdir()
        Image.new("RGB", (80, 40), "white").save(staging / "explorations" / "board.png")
        (staging / "marks" / "mark.svg").write_text(MARK)
        (staging / "marks" / "mark-small.svg").write_text(SMALL)

    def tearDown(self):
        self.temp.cleanup()

    def _needs_renderer(self):
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            self.skipTest("WeasyPrint is not available in this interpreter")

    def _record_through(self, last: str) -> None:
        for stage in STAGES:
            result = record(self.church, stage, f"Lesson text for {stage}.", _metadata(stage))
            self.assertEqual(result["status"], "recorded", result)
            if stage == last:
                return

    def _stage_files(self) -> dict:
        staging = self.church / "brand" / "staging"
        (staging / "type").mkdir()
        (staging / "templates").mkdir()
        (staging / "marks" / "wordmark.svg").write_text(MARK)
        Image.new("RGB", (40, 20), "white").save(staging / "marks" / "banner.png")
        font = ROOT / "skills" / "bulletin" / "renderer" / "fonts" / "SourceSans3-Regular.ttf"
        (staging / "type" / "Display-Regular.ttf").write_bytes(font.read_bytes())
        (staging / "type" / "Text-Regular.ttf").write_bytes(font.read_bytes())
        (staging / "voice.md").write_text("# Voice\n\nPlain, warm, specific.\n")
        (staging / "templates" / "social-square.md").write_text("Square post template.\n")
        (staging / "templates" / "announcement.md").write_text("Announcement image template.\n")
        return {
            "brand_system": {
                "schema_version": 2,
                "name": {"wordmark": "Test Parish Church", "short": "Test Parish"},
                "direction": {"name": "Open Door", "story": "A door that is always propped open."},
                "marks": {"primary": "brand/staging/marks/mark.svg", "small": "brand/staging/marks/mark-small.svg", "wordmark": "brand/staging/marks/wordmark.svg"},
                "lockup_rules": "Ministry names sit below the wordmark in the text face.",
                "type": {
                    "display": {"family": "Test Display", "license": "OFL", "files": {"regular": "brand/staging/type/Display-Regular.ttf"}},
                    "text": {"family": "Test Text", "license": "OFL", "files": {"regular": "brand/staging/type/Text-Regular.ttf"}},
                },
                "palette": {"primary": {"hex": "#224466", "job": "Headlines and the mark"}, "paper": {"hex": "#fffdf8", "job": "Background"}},
                "imagery": {"made_from": "The door's rectangle and the light through it, cropped large.",
                            "announcement": "Program title in the display face over one palette ground; one door shape; no photo.",
                            "forbidden": ["stock photography of crowds", "a second logo", "gradients"]},
                "voice": "brand/staging/voice.md",
                "templates": {"social_square": "brand/staging/templates/social-square.md", "announcement": "brand/staging/templates/announcement.md"},
            },
            "colors": {"ink": "#111111", "accent": "#224466", "accent_deep": "#112233", "paper": "#fffdf8", "rubric_red": "#8b3a3a"},
            "logo": {"banner": "brand/staging/marks/banner.png"},
        }

    # ------------------------------------------------------------ the plan and the order

    def test_fresh_church_orients_to_the_plan_first(self):
        result = orient(self.church)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["next_stage"], "roadmap")
        self.assertEqual(result["stages"][0]["stage"], "roadmap")
        self.assertIn("plan", result["next_action"])
        self.assertFalse(result["roadmap"]["recorded"])
        self.assertFalse(result["guide"])

    def test_the_plan_must_cover_the_whole_engagement(self):
        missing = record(self.church, "roadmap", "The plan.", {"phases": PHASES[:2]})
        self.assertEqual(missing["errors"][0]["code"], "phases_required")
        self.assertIn("color", missing["errors"][0]["message"])
        thin = json.loads(json.dumps(PHASES))
        thin[0].pop("time")
        self.assertEqual(record(self.church, "roadmap", "The plan.", {"phases": thin})["errors"][0]["field"], "phases[0].time")
        twice = json.loads(json.dumps(PHASES))
        twice[1]["stages"].append("fork")
        self.assertEqual(record(self.church, "roadmap", "The plan.", {"phases": twice})["errors"][0]["code"], "phases_required")
        ok = record(self.church, "roadmap", "Here is the whole engagement on one page.", _metadata("roadmap"))
        self.assertEqual(ok["status"], "recorded", ok)
        guide = (self.church / "brand" / "guide.md").read_text()
        self.assertIn("| Phase | What you will see | What you decide | About how long |", guide)
        self.assertIn("| The idea |", guide)
        self.assertIn("**Where you are:** step 1 of 16, The plan.", guide)
        self.assertIn("**Next you will see:** Refresh or start new.", guide)
        state = orient(self.church)
        self.assertTrue(state["roadmap"]["recorded"])
        self.assertEqual(state["roadmap"]["you_are_here"], {"stage": "fork", "title": "Refresh or start new", "phase": "Getting to know you"})

    def test_stages_must_run_in_order_and_carry_a_why(self):
        blocked = record(self.church, "fork", "text", _metadata("fork"))
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["errors"][0]["code"], "stage_out_of_order")
        self._record_through("roadmap")
        bad_fork = record(self.church, "fork", "text", {"decision": "maybe", "rationale": "x"})
        self.assertEqual(bad_fork["errors"][0]["code"], "invalid_fork")
        ok = record(self.church, "fork", "Refresh keeps the mark; new replaces it.", _metadata("fork"))
        self.assertEqual(ok["status"], "recorded")
        self.assertEqual(record(self.church, "discover", "audit", {"sources": [{"label": "site", "kind": "website"}]})["status"], "recorded")
        self.assertEqual(record(self.church, "interview", "brief", {"answers": {k: "a" for k in INTERVIEW_KEYS}})["status"], "recorded")
        no_rationale = record(self.church, "identity", "lesson", {"decision": "one mark"})
        self.assertEqual(no_rationale["errors"][0]["field"], "rationale")
        self.assertEqual(record(self.church, "identity", "lesson", {"decision": "one mark", "rationale": "drift"})["status"], "recorded")
        few_options = record(self.church, "direction", "lesson", {"decision": "A", "rationale": "why", "options": ["A"], "applications": list(DIRECTION_APPLICATIONS)})
        self.assertEqual(few_options["errors"][0]["code"], "options_required")
        legacy = record(self.church, "mark", "lesson", {"decision": "x", "rationale": "y"})
        self.assertEqual(legacy["errors"][0]["code"], "stage_replaced")

    def test_every_section_opens_with_where_the_pastor_is(self):
        self._record_through("direction")
        guide = (self.church / "brand" / "guide.md").read_text()
        self.assertIn("# Public Test Parish Brand Guide", guide)
        self.assertIn("**Where you are:** step 6 of 16, Your direction, in the phase \"The idea\".", guide)
        self.assertIn("**You decide today:** Which of two or three directions is the church you are trying to be.", guide)
        self.assertIn("**Next you will see:** Your direction, developed.", guide)
        self.assertIn("**Shown on:** the bulletin cover; the church's own test announcement; the website's first screen", guide)
        self.assertIn("**Decision:** direction choice", guide)
        self.assertIn("**Why:** Because the direction lesson showed why.", guide)
        self.assertIn("Lesson text for interview.", (self.church / "brand" / "brief.md").read_text())
        self.assertIn("answer for audience", guide)

    def test_replacing_an_earlier_stage_marks_later_stages_stale(self):
        self._record_through("refine-1")
        dup = record(self.church, "direction", "again", _metadata("direction"))
        self.assertEqual(dup["errors"][0]["code"], "already_recorded")
        redo = record(self.church, "direction", "Revised direction.", _metadata("direction"), replace=True)
        self.assertEqual(redo["status"], "recorded")
        state = orient(self.church)
        self.assertEqual([s["stage"] for s in state["stages"] if s["stale"]], ["develop", "refine-1"])
        guide = (self.church / "brand" / "guide.md").read_text()
        self.assertEqual(guide.count("<!-- stage:direction -->"), 1)
        self.assertIn("Revised direction.", guide)

    # ------------------------------------------------------------ fidelity only rises

    def test_fidelity_only_rises_from_direction_through_refinement(self):
        self._record_through("identity")
        short = _metadata("direction")
        short["applications"] = ["bulletin_cover", "test_announcement"]
        dropped = record(self.church, "direction", "lesson", short)
        self.assertEqual(dropped["errors"][0]["code"], "fidelity_dropped")
        self.assertIn("website", dropped["errors"][0]["message"])
        wide = _metadata("direction")
        wide["applications"] = list(DIRECTION_APPLICATIONS) + ["poster"]
        self.assertEqual(record(self.church, "direction", "lesson", wide)["status"], "recorded")
        floor = orient(self.church)["fidelity_floor"]
        self.assertEqual(floor["stage"], "develop")
        self.assertEqual(floor["applications"], list(DIRECTION_APPLICATIONS) + ["poster", "sign", "social_avatar"])
        self.assertIn("a poster", orient(self.church)["next_action"])
        less = _metadata("develop")
        less["applications"] = list(DEVELOP_APPLICATIONS)
        fewer = record(self.church, "develop", "developed", less)
        self.assertEqual(fewer["errors"][0]["code"], "fidelity_dropped")
        self.assertEqual(fewer["errors"][0]["detail"]["missing"], ["poster"])
        no_rec = _metadata("develop")
        no_rec["applications"] = floor["applications"]
        no_rec.pop("recommendation")
        self.assertEqual(record(self.church, "develop", "developed", no_rec)["errors"][0]["field"], "recommendation")
        no_boards = dict(no_rec, recommendation="A", boards=[])
        self.assertEqual(record(self.church, "develop", "developed", no_boards)["errors"][0]["code"], "boards_required")
        good = dict(no_rec, recommendation="Version A, because the arch carries.", applications=floor["applications"] + ["partner_pairing"],
                    references=[{"name": "Whitney Museum, Experimental Jetset", "learn": "One form, endless layouts."}])
        done = record(self.church, "develop", "developed", good)
        self.assertEqual(done["status"], "recorded", done)
        guide = (self.church / "brand" / "guide.md").read_text()
        self.assertIn("**Recommended:** Version A, because the arch carries.", guide)
        self.assertIn("the mark beside a stand-in partner mark", guide)
        bad_refs = dict(good, references=[{"name": "x"}])
        self.assertEqual(record(self.church, "develop", "developed", bad_refs, replace=True)["errors"][0]["field"], "references[0].learn")
        refine = _metadata("refine-1")
        refine["applications"] = list(DEVELOP_APPLICATIONS)
        back = record(self.church, "refine-1", "tightened", refine)
        self.assertEqual(back["errors"][0]["code"], "fidelity_dropped")
        self.assertEqual(sorted(back["errors"][0]["detail"]["missing"]), ["partner_pairing", "poster"])
        refine["applications"] = good["applications"]
        self.assertEqual(record(self.church, "refine-1", "tightened", refine)["status"], "recorded")
        final = _metadata("refine-2")
        final["applications"] = good["applications"]
        final.pop("mark")
        self.assertEqual(record(self.church, "refine-2", "final", final)["errors"][0]["code"], "mark_required")
        png = self.church / "brand" / "staging" / "marks" / "mark.png"
        Image.new("RGB", (10, 10), "black").save(png)
        final["mark"] = {"primary": "brand/staging/marks/mark.png"}
        self.assertEqual(record(self.church, "refine-2", "final", final)["errors"][0]["code"], "invalid_mark")
        final["mark"] = {"primary": "brand/staging/marks/mark.svg", "small": "brand/staging/marks/mark-small.svg"}
        self.assertEqual(record(self.church, "refine-2", "final", final)["status"], "recorded")
        state = orient(self.church)
        self.assertEqual(state["mark"]["primary"], "brand/staging/marks/mark.svg")
        self.assertEqual(state["next_stage"], "color")

    # ------------------------------------------------------------ a run from the first scheme

    def _legacy_state(self, extra: dict | None = None) -> None:
        stages = {
            "fork": {"decision": "refresh", "rationale": "The current mark stays.", "recorded_at": "2026-01-10T19:14:17+00:00", "stale": False},
            "discover": {"sources": [{"label": "site", "kind": "website"}], "recorded_at": "2026-01-10T19:15:50+00:00", "stale": False},
            "interview": {"answers": {k: "a" for k in INTERVIEW_KEYS}, "recorded_at": "2026-01-10T21:13:30+00:00", "stale": False},
            "identity": {"decision": "One logo.", "rationale": "why", "options": ["A", "B"], "recorded_at": "2026-01-10T22:07:32+00:00", "stale": False},
            "direction": {"decision": "B. Open Door leads.", "rationale": "the open arch", "options": ["A", "B", "C"], "recorded_at": "2026-01-10T22:55:31+00:00", "stale": False},
        }
        stages.update(extra or {})
        state_dir = self.church / ".handbuilt" / "build-my-brand"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text(json.dumps({"schema_version": 1, "stages": stages, "fork": "refresh", "approved": None, "implementation_version": "0.1.0"}))
        guide = ["# Public Test Parish Brand Guide", ""]
        for stage in stages:
            guide += [f"<!-- stage:{stage} -->", f"## {stage}", "", "old text", f"<!-- /stage:{stage} -->", ""]
        (self.church / "brand" / "guide.md").write_text("\n".join(guide))

    def test_a_run_from_the_first_scheme_resumes_at_direction_development(self):
        self._legacy_state()
        state = orient(self.church)
        self.assertEqual(state["status"], "ok", state)
        self.assertEqual(state["next_stage"], "develop")
        self.assertEqual(state["owed_stages"], ["roadmap"])
        self.assertEqual(state["migrated_from"], 1)
        self.assertIn("plan", state["warnings"][0])
        self.assertTrue(state["next_action"].startswith("This run began before the plan stage existed"))
        self.assertIn("Open Door", state["next_action"])
        direction = next(s for s in state["stages"] if s["stage"] == "direction")
        self.assertEqual(direction["applications"], list(DIRECTION_APPLICATIONS))
        self.assertEqual(state["fidelity_floor"]["applications"], list(DEVELOP_APPLICATIONS))
        too_soon = record(self.church, "develop", "developed", _metadata("develop"))
        self.assertEqual(too_soon["errors"][0]["code"], "roadmap_required")
        plan = record(self.church, "roadmap", "The plan, shown now that we are at direction development.", _metadata("roadmap"))
        self.assertEqual(plan["status"], "recorded", plan)
        guide = (self.church / "brand" / "guide.md").read_text()
        self.assertLess(guide.index("<!-- stage:roadmap -->"), guide.index("<!-- stage:fork -->"))
        self.assertIn("You are at step 7 of 16, Your direction, developed.", guide)
        self.assertEqual(orient(self.church)["owed_stages"], [])
        less = _metadata("develop")
        less["applications"] = ["bulletin_cover", "sign", "social_avatar"]
        fewer = record(self.church, "develop", "developed", less)
        self.assertEqual(fewer["errors"][0]["code"], "fidelity_dropped")
        done = record(self.church, "develop", "Open Door, developed three ways.", _metadata("develop"))
        self.assertEqual(done["status"], "recorded", done)
        self.assertEqual(done["next_stage"], "refine-1")
        saved = json.loads((self.church / ".handbuilt" / "build-my-brand" / "state.json").read_text())
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(saved["stages"]["direction"]["applications_source"].split(":")[0], "Migration baseline")

    def test_first_scheme_mark_and_color_decisions_are_kept_as_evidence_and_made_stale(self):
        self._legacy_state({
            "mark": {"decision": "r3-01", "rationale": "x", "studio_direction": "hold-fast", "finalist": "r3-01", "recorded_at": "2026-10-06T00:00:00+00:00", "stale": False},
            "color": {"decision": "blues", "rationale": "x", "options": ["a", "b"], "recorded_at": "2026-10-06T00:00:00+00:00", "stale": False},
        })
        state = orient(self.church)
        self.assertEqual(state["next_stage"], "develop")
        color = next(s for s in state["stages"] if s["stage"] == "color")
        self.assertTrue(color["recorded"])
        self.assertTrue(color["stale"])
        self.assertNotIn("mark", [s["stage"] for s in state["stages"]])
        self.assertEqual(record(self.church, "roadmap", "plan", _metadata("roadmap"))["status"], "recorded")
        saved = json.loads((self.church / ".handbuilt" / "build-my-brand" / "state.json").read_text())
        self.assertEqual(saved["legacy_stages"]["mark"]["finalist"], "r3-01")
        self.assertIn("developed system", saved["stages"]["color"]["stale_reason"])

    # ------------------------------------------------------------ the system, the proof, approval

    def test_staging_requires_the_image_language_and_passing_marks_then_approval_archives_the_old_brand(self):
        self._needs_renderer()
        self._record_through("voice")
        patch = self._stage_files()
        old_schema = json.loads(json.dumps(patch))
        old_schema["brand_system"]["schema_version"] = 1
        self.assertEqual(stage_brand(self.church, old_schema)["errors"][0]["field"], "schema_version")
        no_imagery = json.loads(json.dumps(patch))
        no_imagery["brand_system"].pop("imagery")
        blocked = stage_brand(self.church, no_imagery)
        self.assertEqual(blocked["errors"][0]["code"], "imagery_required")
        no_forbidden = json.loads(json.dumps(patch))
        no_forbidden["brand_system"]["imagery"]["forbidden"] = []
        self.assertEqual(stage_brand(self.church, no_forbidden)["errors"][0]["field"], "imagery.forbidden")
        no_small = json.loads(json.dumps(patch))
        no_small["brand_system"]["marks"].pop("small")
        self.assertEqual(stage_brand(self.church, no_small)["errors"][0]["field"], "marks")
        escaped = json.loads(json.dumps(patch))
        escaped["brand_system"]["marks"]["primary"] = "brand/marks/mark.svg"
        self.assertEqual(stage_brand(self.church, escaped)["errors"][0]["code"], "outside_staging")
        thin = self.church / "brand" / "staging" / "marks" / "thin.svg"
        thin.write_text(THIN)
        fragile = json.loads(json.dumps(patch))
        fragile["brand_system"]["marks"]["primary"] = "brand/staging/marks/thin.svg"
        failed = stage_brand(self.church, fragile)
        self.assertEqual(failed["errors"][0]["code"], "survival_failed", failed)
        self.assertIn("embroidery", {f["check"] for f in failed["errors"][0]["detail"]["failures"]})
        self.assertTrue((self.church / failed["errors"][0]["detail"]["report"]).is_file())
        bad_waiver = dict(fragile, waivers=[{"check": "reversal", "reason": "no"}])
        self.assertEqual(stage_brand(self.church, bad_waiver)["errors"][0]["code"], "invalid_waivers")
        staged = stage_brand(self.church, patch)
        self.assertEqual(staged["status"], "staged", staged)
        self.assertTrue((self.church / staged["survival"]).is_file())
        early = approve(self.church)
        self.assertEqual(early["errors"][0]["code"], "stage_out_of_order")
        build = record(self.church, "build", "Built the system.", {"staged_files": ["brand/staging/marks/mark.svg"]})
        self.assertEqual(build["status"], "recorded", build)
        (self.church / "before.pdf").write_bytes(b"%PDF-1.4 before")
        (self.church / "after.pdf").write_bytes(b"%PDF-1.4 after")
        no_announcement = record(self.church, "prove", "Old beside new.", {"before": "before.pdf", "after": "after.pdf"})
        self.assertEqual(no_announcement["errors"][0]["field"], "announcement")
        Image.new("RGB", (10, 10), "blue").save(self.church / "announcement.png")
        proof = record(self.church, "prove", "Old beside new.", {"before": "before.pdf", "after": "after.pdf", "announcement": "announcement.png"})
        self.assertEqual(proof["status"], "recorded", proof)
        too_soon = record(self.church, "connect", "travels", {})
        self.assertEqual(too_soon["errors"][0]["code"], "approval_required")
        old_brand = (self.church / "brand.json").read_bytes()
        approved = approve(self.church, approved_by="The Rev. Test Pastor")
        self.assertEqual(approved["status"], "approved", approved)
        self.assertTrue(approved["live_brand_ready"])
        archive = Path(approved["archive"])
        self.assertEqual((archive / "brand.json").read_bytes(), old_brand)
        self.assertTrue((archive / "staged-brand-system.json").is_file())
        brand = json.loads((self.church / "brand.json").read_text())
        system = brand["brand_system"]
        self.assertEqual(system["marks"]["primary"], "brand/marks/mark.svg")
        self.assertEqual(system["marks"]["small"], "brand/marks/mark-small.svg")
        self.assertEqual(system["imagery"]["forbidden"][1], "a second logo")
        self.assertEqual(system["survival"]["report"], "brand/checks/report.json")
        self.assertTrue((self.church / "brand" / "checks" / "report.json").is_file())
        self.assertEqual(system["type"]["display"]["files"]["regular"], "brand/type/Display-Regular.ttf")
        self.assertEqual(system["approved_by"], "The Rev. Test Pastor")
        self.assertEqual(brand["logo"]["banner"], "brand/marks/banner.png")
        self.assertEqual(brand["colors"]["accent"], "#224466")
        self.assertEqual(brand["colors_status"], "confirmed")
        self.assertFalse((self.church / "brand" / "staging").exists())
        self.assertTrue(brand_setup.status(self.church)["ready"])
        self.assertEqual(record(self.church, "connect", "The same file drives everything.", {})["status"], "recorded")
        (self.church / "brand" / "volunteer-card.md").write_text("Ask for a flyer.\n")
        handoff = record(self.church, "handoff", "Keep it.", {"volunteer_card": "brand/volunteer-card.md"})
        self.assertEqual(handoff["status"], "recorded", handoff)
        self.assertIsNone(orient(self.church)["next_stage"])
        receipts = list((self.church / ".handbuilt" / "build-my-brand" / "receipts").glob("*.json"))
        kinds = {json.loads(p.read_text())["kind"] for p in receipts}
        self.assertIn("approval", kinds)
        self.assertIn("stage-brand", kinds)
        self.assertEqual(len([k for k in kinds if k.startswith("stage-") and k != "stage-brand"]), len(STAGES))

    def test_a_waiver_lets_the_creative_director_accept_a_named_failure_with_a_reason(self):
        self._needs_renderer()
        self._record_through("voice")
        patch = self._stage_files()
        thin = self.church / "brand" / "staging" / "marks" / "thin.svg"
        thin.write_text(THIN)
        patch["brand_system"]["marks"]["primary"] = "brand/staging/marks/thin.svg"
        reason = "Hairline mark by design; small sizes and embroidery use the small variant."
        patch["waivers"] = [{"check": check, "reason": reason} for check in ("sign", "footer", "embroidery")]
        result = stage_brand(self.church, patch)
        self.assertEqual(result["status"], "staged", result)
        report = json.loads((self.church / result["survival"]).read_text())
        waived = {c["check"] for m in report["marks"] for c in m["checks"] if c.get("waived")}
        self.assertIn("embroidery", waived)
        self.assertFalse(waived & {"one_color", "reversal"})
        self.assertEqual(json.loads((self.church / "brand" / "staging" / "brand-system.json").read_text())["waivers"][0]["reason"], reason)

    def test_restart_archives_the_run_and_begins_again_at_the_plan(self):
        self.assertEqual(restart(self.church)["errors"][0]["code"], "nothing_to_restart")
        self._record_through("interview")
        (self.church / "brand" / "discovery").mkdir()
        (self.church / "brand" / "discovery" / "site.png").write_bytes(b"png")
        result = restart(self.church, reason="Testing the workflow from the start")
        self.assertEqual(result["status"], "restarted", result)
        archive = Path(result["archive"])
        for kept in ("guide.md", "brief.md", "discovery/site.png", "staging/marks/mark.svg", "workflow-record/state.json", "run.json"):
            self.assertTrue((archive / kept).is_file(), kept)
        self.assertEqual(json.loads((archive / "run.json").read_text())["stages_recorded"], ["roadmap", "fork", "discover", "interview"])
        self.assertFalse((self.church / "brand" / "guide.md").exists())
        state = orient(self.church)
        self.assertEqual(state["next_stage"], "roadmap")
        self.assertFalse(state["brief"])
        self.assertEqual(record(self.church, "roadmap", "Again.", _metadata("roadmap"))["status"], "recorded")

    # ------------------------------------------------------------ the guide and the command line

    def test_markdown_converter_covers_the_guide_shapes(self):
        html = markdown_to_html("# T\n\n<!-- c -->\n## Head\n\n**Where you are:** step 1.\n\nPara **b** *i* `c` [l](x).\n\n- one\n- two\n\n1. a\n2. b\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n![alt](brand/x.png)\n\n**Decision:** X\n\n**Shown on:** the sign\n\n> quote\n")
        for needle in ("<h2>Head</h2>", 'class="wayfinding"', "<strong>b</strong>", "<em>i</em>", "<code>c</code>", '<a href="x">l</a>', "<ul><li>one</li>", "<ol><li>a</li>", "<table>", "<figure>", 'class="decision-line"><strong>Decision', 'class="decision-line"><strong>Shown on', "<blockquote>"):
            self.assertIn(needle, html)
        self.assertNotIn("<!--", html)

    def test_guide_names_the_church_from_church_yaml_when_brand_fields_are_blank(self):
        from brand_workflow.guide import build_html
        brand = json.loads((self.church / "brand.json").read_text())
        brand["church"] = {"public_name": "", "name": "", "short_name": ""}
        (self.church / "brand.json").write_text(json.dumps(brand))
        _source, document = build_html(self.church, "# X\n\n## Head\n\nBody.\n")
        self.assertIn("Public Test Parish", document)
        self.assertNotIn("Your church", document)

    def test_guide_renders_to_pdf_before_and_after_staging(self):
        self._needs_renderer()
        self._record_through("voice")
        neutral = render_guide(self.church)
        self.assertEqual(neutral["status"], "rendered", neutral)
        self.assertEqual(neutral["brand_source"], "neutral")
        self.assertEqual(stage_brand(self.church, self._stage_files())["status"], "staged")
        staged = render_guide(self.church, "brand/guide-draft.pdf")
        self.assertEqual(staged["status"], "rendered", staged)
        self.assertEqual(staged["brand_source"], "staged")
        self.assertTrue((self.church / "brand" / "guide-draft.pdf").read_bytes().startswith(b"%PDF"))

    def test_help_is_not_a_failed_run_and_bad_arguments_answer_in_json(self):
        for argv in (["--help"], ["record", "--help"], ["check-marks", "-h"]):
            done = subprocess.run([sys.executable, str(CLI), *argv], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            payload = json.loads(done.stdout)
            self.assertEqual(payload["status"], "help")
            self.assertIn("usage", payload["usage"])
        bad = subprocess.run([sys.executable, str(CLI), "record", "--church-folder", str(self.church), "--stage", "nope", "--content-file", "x"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)["errors"][0]["code"], "invalid_arguments")
        self.assertEqual(bad.stderr, "")
        orient_run = subprocess.run([sys.executable, str(CLI), "orient", "--church-folder", str(self.church)], capture_output=True, text=True)
        self.assertEqual(json.loads(orient_run.stdout)["next_stage"], "roadmap")

    def test_the_launcher_registers_the_new_operations(self):
        source = (ROOT / "tools" / "church_workflow.py").read_text()
        for operation in ("explore", "redirect", "check-marks", "stage-brand"):
            self.assertIn(f'"{operation}"', source)
        self.assertNotIn('"studio"', source)


if __name__ == "__main__":
    unittest.main()
