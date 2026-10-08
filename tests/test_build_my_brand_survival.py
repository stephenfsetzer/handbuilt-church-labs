from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.helpers import make_church

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "build-my-brand"))

from brand_workflow import DIRECTION_APPLICATIONS, INTERVIEW_KEYS, STAGES, check_marks, explore, orient, record, redirect  # noqa: E402
from brand_workflow import survival  # noqa: E402

SOLID = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor"><rect x="20" y="10" width="60" height="80"/></svg>'
RING = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor" fill-rule="evenodd"><path d="M50 4a46 46 0 1 0 0 92a46 46 0 1 0 0-92zm0 22a24 24 0 1 1 0 48a24 24 0 1 1 0-48z"/></svg>'
THIN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor"><rect x="49" y="10" width="2" height="80"/><rect x="10" y="49" width="80" height="2"/></svg>'
DEFAULT_FILL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="20" y="10" width="60" height="80"/></svg>'
RED = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="20" y="10" width="60" height="80" fill="#ff0000"/></svg>'
PHASES = [
    {"title": "Start", "stages": ["fork", "discover", "interview", "identity"], "you_see": "a", "you_decide": "b", "time": "c"},
    {"title": "Idea", "stages": ["direction", "develop", "refine-1", "refine-2"], "you_see": "a", "you_decide": "b", "time": "c"},
    {"title": "System", "stages": ["color", "type", "voice", "build", "prove", "connect", "handoff"], "you_see": "a", "you_decide": "b", "time": "c"},
]


def _metadata(stage: str) -> dict:
    meta: dict = {}
    if stage == "roadmap":
        meta["phases"] = PHASES
    if stage in {"fork", "identity", "direction"}:
        meta.update({"decision": "new" if stage == "fork" else f"{stage} choice", "rationale": "why"})
    if stage == "direction":
        meta.update({"options": ["A", "B"], "applications": list(DIRECTION_APPLICATIONS)})
    if stage == "discover":
        meta["sources"] = [{"label": "site", "kind": "website"}]
    if stage == "interview":
        meta["answers"] = {k: "a" for k in INTERVIEW_KEYS}
    return meta


class SurvivalTest(unittest.TestCase):
    def setUp(self):
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            self.skipTest("WeasyPrint is not available in this interpreter")
        self.temp = tempfile.TemporaryDirectory()
        self.church = make_church(Path(self.temp.name))
        self.marks = self.church / "brand" / "staging" / "marks"
        self.marks.mkdir(parents=True)
        self.sketches = self.church / "brand" / "staging" / "sketches"
        self.sketches.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _through_direction(self):
        for stage in STAGES:
            self.assertEqual(record(self.church, stage, "text", _metadata(stage))["status"], "recorded")
            if stage == "direction":
                break

    def _svg(self, name: str, text: str) -> str:
        path = self.marks / f"{name}.svg"
        path.write_text(text)
        return path.relative_to(self.church).as_posix()

    def test_reversed_render_paints_white_on_the_dark_color(self):
        path = self.marks / "mark.svg"
        path.write_text(SOLID)
        renders = survival.render_mark(self.church, path, self.marks / "renders", dark="#0b1d3a")
        with Image.open(self.church / renders["reversed"]) as image:
            colors = {color: count for count, color in image.convert("RGB").getcolors(maxcolors=100000)}
        total = sum(colors.values())
        self.assertGreater(colors.get((255, 255, 255), 0), total * 0.2)
        self.assertEqual(sum(n for (r, g, b), n in colors.items() if max(r, g, b) < 10), 0)
        self.assertGreater(colors.get((11, 29, 58), 0), total * 0.2)
        with Image.open(self.church / renders["sign"]) as image:
            sign_colors = {color: count for count, color in image.convert("RGB").getcolors(maxcolors=100000)}
        self.assertGreater(sign_colors.get((0, 0, 0), 0), total * 0.2)
        for view, size in (("footer", 64), ("favicon", 16), ("favicon_preview", 256)):
            with Image.open(self.church / renders[view]) as image:
                self.assertEqual(image.size, (size, size), view)

    def test_checks_pass_or_fail_and_name_the_reason(self):
        out = self.church / "brand" / "staging" / "checks"
        solid = survival.run_checks(self.church, Path(self.church / self._svg("solid", SOLID)), out / "solid", which=survival.PRIMARY_CHECKS)
        self.assertTrue(solid["passed"], solid)
        ring = survival.run_checks(self.church, Path(self.church / self._svg("ring", RING)), out / "ring", which=survival.SMALL_CHECKS)
        self.assertTrue(ring["passed"], ring)
        thin = survival.run_checks(self.church, Path(self.church / self._svg("thin", THIN)), out / "thin", which=survival.PRIMARY_CHECKS)
        failed = {c["check"]: c["detail"] for c in thin["checks"] if not c["passed"]}
        self.assertIn("embroidery", failed)
        self.assertIn("1 mm", failed["embroidery"])
        self.assertTrue({"one_color", "reversal"} <= {c["check"] for c in thin["checks"] if c["passed"]})
        default = survival.run_checks(self.church, Path(self.church / self._svg("default", DEFAULT_FILL)), out / "default", which=("reversal",))
        self.assertFalse(default["passed"])
        self.assertIn("currentColor", default["checks"][0]["detail"])
        red = survival.run_checks(self.church, Path(self.church / self._svg("red", RED)), out / "red", which=("one_color",))
        self.assertFalse(red["passed"])
        self.assertIn("#ff0000", red["checks"][0]["detail"])
        with self.assertRaises(survival.SurvivalFailure) as ctx:
            survival.validate_mark_svg(self._write_text_svg())
        self.assertEqual(ctx.exception.code, "invalid_svg")

    def _write_text_svg(self) -> Path:
        path = self.marks / "text.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text>A</text></svg>')
        return path

    def test_check_marks_operation_reports_and_receipts_before_staging(self):
        self._through_direction()
        primary = self._svg("mark", SOLID)
        small = self._svg("mark-small", RING)
        nothing = check_marks(self.church)
        self.assertEqual(nothing["errors"][0]["code"], "marks_required")
        result = check_marks(self.church, primary=primary, small=small, dark="#0b1d3a")
        self.assertEqual(result["status"], "checked", result)
        self.assertTrue(result["passed"])
        self.assertEqual(result["failures"], [])
        self.assertEqual([m["mark"] for m in result["marks"]], [primary, small])
        self.assertEqual([c["check"] for c in result["marks"][1]["checks"]], list(survival.SMALL_CHECKS))
        report = json.loads((self.church / result["report"]).read_text())
        self.assertEqual(report["dark"], "#0b1d3a")
        self.assertEqual(json.loads(Path(result["receipt"]).read_text())["kind"], "check-marks")
        fragile = check_marks(self.church, primary=self._svg("thin", THIN), small=small)
        self.assertEqual(fragile["status"], "checked")
        self.assertFalse(fragile["passed"])
        self.assertIn("embroidery", {f["check"] for f in fragile["failures"]})
        self.assertIn("waive", fragile["next_action"])

    def test_exploration_rounds_make_a_contact_sheet_and_the_creative_director_can_redirect(self):
        early = explore(self.church, "sketches-1", ["brand/staging/sketches/a.svg"])
        self.assertEqual(early["errors"][0]["code"], "stage_out_of_order")
        self._through_direction()
        files = []
        for index in range(3):
            path = self.sketches / f"a{index}.svg"
            path.write_text(SOLID.replace('x="20"', f'x="{10 + index * 5}"'))
            files.append(path.relative_to(self.church).as_posix())
        png = self.sketches / "form.png"
        Image.new("RGB", (120, 80), "navy").save(png)
        files.append(png.relative_to(self.church).as_posix())
        bad = self.sketches / "bad.txt"
        bad.write_text("no")
        self.assertEqual(explore(self.church, "sketches-1", [bad.relative_to(self.church).as_posix()])["errors"][0]["code"], "invalid_sketch")
        result = explore(self.church, "Sketches 1", files, maker="maker-a@opus", dark="#0b1d3a")
        self.assertEqual(result["status"], "explored", result)
        self.assertEqual(result["round"], "sketches-1")
        self.assertEqual(result["files"], 4)
        self.assertEqual([i["id"] for i in result["added"]], ["sketches-1-01", "sketches-1-02", "sketches-1-03", "sketches-1-04"])
        self.assertTrue((self.church / result["contact_sheet"]).is_file())
        self.assertIn("renders", result["added"][0])
        self.assertNotIn("renders", result["added"][3])
        self.assertTrue((self.church / "brand" / "staging" / "explorations" / "sketches-1" / "sketches-1-04.png").is_file())
        more = explore(self.church, "sketches-1", files[:1])
        self.assertEqual(more["files"], 5)
        state = orient(self.church)
        self.assertEqual(state["explorations"], {"sketches-1": {"files": 5, "redirected": False}})
        self.assertEqual(state["redirects"], 0)
        self.assertEqual(redirect(self.church, "sketches-1", "  ")["errors"][0]["field"], "reason")
        stopped = redirect(self.church, "sketches-1", "Every sketch is a literal pictogram; none carries the direction's lines.",
                           rebrief="Explore the door cropped huge by the frame, one continuous line, and the arch as the threshold.")
        self.assertEqual(stopped["status"], "redirected", stopped)
        self.assertEqual(stopped["files_seen"], 5)
        note = (self.church / stopped["file"]).read_text()
        self.assertIn("literal pictogram", note)
        self.assertIn("## New brief", note)
        self.assertEqual(json.loads(Path(stopped["receipt"]).read_text())["kind"], "redirect")
        self.assertEqual(explore(self.church, "sketches-1", files[:1])["errors"][0]["code"], "round_redirected")
        self.assertEqual(redirect(self.church, "sketches-1", "again")["errors"][0]["code"], "round_redirected")
        fresh = explore(self.church, "sketches-2", files[:2])
        self.assertEqual(fresh["status"], "explored")
        state = orient(self.church)
        self.assertEqual(state["redirects"], 1)
        self.assertTrue(state["explorations"]["sketches-1"]["redirected"])
        unseen = redirect(self.church, "image-forms", "Image tool output drifted into clip art.")
        self.assertEqual(unseen["status"], "redirected")
        self.assertEqual(unseen["files_seen"], 0)
        kinds = {json.loads(p.read_text())["kind"] for p in (self.church / ".handbuilt" / "build-my-brand" / "receipts").glob("*.json")}
        self.assertTrue({"explore", "redirect"} <= kinds)


if __name__ == "__main__":
    unittest.main()
