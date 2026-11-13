"""The sermon video grader must pass good work and fail each kind of bad work.

No model runs here. The case's own seed makes the invented service recording, the
production helper prepares a good sermon package from it, and then the package is
damaged one way at a time. Artwork pictures are drawn directly instead of through
a browser, so the test needs only FFmpeg and the Mac's speech voice.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "evals" / "finished_work")]

try:
    from PIL import Image, ImageDraw
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

import case_video as V  # noqa: E402
import cases as C  # noqa: E402
import judges as J  # noqa: E402

READY = HAS_PILLOW and not V.tools_ready()


def failed(result: dict) -> set[str]:
    return {item["id"] for item in result["checks"] if not item["passed"]}


def load_helper():
    entry = REPO / "skills/sermon-video/scripts/sermon_video.py"
    spec = importlib.util.spec_from_file_location("sermon_video_under_test", entry)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcription(key: dict) -> dict:
    """A word-timed transcription like Whisper's, with words spread across each spoken paragraph."""
    segments = []
    for paragraph in key["paragraphs"]:
        tokens = paragraph["text"].split()
        step = (paragraph["end"] - paragraph["start"]) / len(tokens)
        segments.append({"words": [{"start": paragraph["start"] + i * step, "end": paragraph["start"] + (i + 0.9) * step,
                                    "word": " " + token} for i, token in enumerate(tokens)]})
    return {"segments": segments}


def draw_artwork(root: Path, photo: str) -> None:
    """Stand-ins for the browser-rendered artwork, the photo filling the thumbnail's right side as the template does."""
    assets = root / "assets"
    thumbnail = Image.new("RGB", (1280, 720), (255, 255, 255))
    with Image.open(photo) as picture:
        thumbnail.paste(picture.convert("RGB").resize((704, 860)).crop((0, 70, 704, 790)), (576, 0))
    ImageDraw.Draw(thumbnail).rectangle([64, 205, 504, 400], fill=(66, 91, 118))
    thumbnail.save(assets / "thumbnail.png")
    Image.new("RGB", (1280, 720), (66, 91, 118)).save(assets / "outro.png")
    panel = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rectangle([64, 560, 700, 650], fill=(20, 20, 20, 200))
    panel.save(assets / "lower-third.png")


@unittest.skipUnless(READY, "needs FFmpeg, ffprobe, the say command and Pillow")
class VideoGrader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.video = load_helper()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.church = V.seed(Path(cls.tmp.name) / "run" / "riverbend")
        cls.key = json.loads(V.answer_key_path(cls.church).read_text(encoding="utf-8"))
        root = cls.church / "sermon-videos" / "2026-11-15"
        root.mkdir(parents=True)
        recording = Path(cls.key["recording"])
        (root / ".receipts").mkdir()
        (root / ".receipts/acquisition.json").write_text(json.dumps(
            {"url": "https://riverbend.invalid/worship", "file": str(recording), "hash": cls.key["recording_hash"],
             "method": "supplied_local_recording"}), encoding="utf-8")
        plan = {
            "church": {"name": "Riverbend Episcopal Church", "website": "https://riverbend.invalid"},
            "source": {"path": str(recording), "url": "https://riverbend.invalid/worship"},
            "sermon": {"start": round(cls.key["first_word"] - 1.0, 2), "end": round(cls.key["last_word"] + 1.5, 2),
                       "first_word": round(cls.key["first_word"], 2), "last_word": round(cls.key["last_word"], 2),
                       "boundary_evidence": "Gospel response ends, invocation begins; final Amen before the Creed."},
            "labels": {
                "title": {"text": "The empty jar", "status": "editorial", "evidence": "Closing image of the sermon"},
                "preacher": {"text": V.PREACHER, "status": "verified", "evidence": "The rector named the preacher"},
                "scripture": {"text": "Matthew 25:14-30", "status": "verified", "evidence": "Announced Gospel"},
            },
            "assets": {"portrait": cls.key["casey_photo"], "portrait_position": "50% 30%"},
            "video": {"width": 1280, "height": 720},
        }
        (root / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
        words = root / "words.json"
        words.write_text(json.dumps(transcription(cls.key)), encoding="utf-8")
        _, data = cls.video.plan(root / "plan.json")
        cls.video.artwork(root, data)
        cls.video.write_captions(root, data, words)
        draw_artwork(root, cls.key["casey_photo"])
        cls.video.render(root, data)
        cls.video.verify(root, data)
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def copy(self) -> tuple[Path, Path]:
        """A private copy of the good church to damage. Returns the church and its sermon video folder."""
        place = Path(tempfile.mkdtemp(dir=self.tmp.name))
        church = place / "riverbend"
        shutil.copytree(self.church, church)
        self.addCleanup(shutil.rmtree, place, True)
        return church, church / "sermon-videos" / "2026-11-15"

    def grade(self, church: Path, stream: dict | None = None, key: dict | None = None) -> set[str]:
        return failed(V.grade(church, stream=stream or {"uses": []}, key=key or self.key))

    def edit_plan(self, root: Path, **sermon) -> None:
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        plan["sermon"].update(sermon)
        (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def edit_cues(self, root: Path, change) -> None:
        vtt = root / "sermon.en.vtt"
        vtt.write_text(change(vtt.read_text(encoding="utf-8")), encoding="utf-8")

    def test_good_package_passes_every_check(self):
        result = V.grade(self.church, stream={"uses": []}, key=self.key)
        self.assertEqual(failed(result), set(), [c for c in result["checks"] if not c["passed"]])

    def test_answer_key_stays_outside_the_run_folder(self):
        path = V.answer_key_path(self.church)
        self.assertFalse(path.is_relative_to(self.church.parent))

    def test_empty_church_fails(self):
        church = Path(tempfile.mkdtemp(dir=self.tmp.name)) / "riverbend"
        V.F.seed_church(church)
        self.assertIn("package_found", self.grade(church))

    def test_clip_that_starts_in_the_gospel_fails(self):
        church, root = self.copy()
        self.edit_plan(root, start=self.key["before_ends"] - 2)
        self.assertTrue({"leaves_out_the_gospel", "verified_current"} <= self.grade(church))

    def test_clip_that_runs_into_the_creed_fails(self):
        church, root = self.copy()
        self.edit_plan(root, end=self.key["after_starts"] + 2)
        self.assertIn("leaves_out_the_creed", self.grade(church))

    def test_clip_that_cuts_the_first_word_fails(self):
        church, root = self.copy()
        start = self.key["first_word"] + 0.5
        self.edit_plan(root, start=start, first_word=start + 0.2)
        self.assertIn("keeps_first_word", self.grade(church))

    def test_clip_that_stops_at_the_long_pause_fails(self):
        church, root = self.copy()
        pause = self.key["paragraphs"][2]["end"] + 1
        self.edit_plan(root, end=pause, last_word=pause - 0.5)
        self.assertTrue({"keeps_last_word", "boundaries_close"} <= self.grade(church))

    def test_damaged_video_fails(self):
        church, root = self.copy()
        clip = root / "sermon-review.mp4"
        clip.write_bytes(clip.read_bytes()[: clip.stat().st_size // 2])
        self.assertTrue({"clip_plays", "verified_current"} <= self.grade(church))

    def test_missing_captions_fail(self):
        church, root = self.copy()
        (root / "sermon.en.vtt").unlink()
        (root / "sermon.en.srt").unlink()
        self.assertIn("captions_exist", self.grade(church))

    def test_captions_with_gospel_words_fail(self):
        church, root = self.copy()
        gospel = "A householder setting out on a long journey called his three servants and gave each of them silver"
        self.edit_cues(root, lambda text: text.replace("Amen.", gospel + " Amen.", 1))
        self.assertIn("captions_only_the_sermon", self.grade(church))

    def test_garbled_captions_fail(self):
        church, root = self.copy()
        self.edit_cues(root, lambda text: re.sub(r"(-->[^\n]*\n)[^\n]+", r"\1music playing softly", text))
        self.assertIn("caption_words_match", self.grade(church))

    def test_captions_shifted_by_a_wrong_origin_fail(self):
        church, root = self.copy()
        def shift(match):
            seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)) + 4
            return self.video.timestamp(seconds)
        self.edit_cues(root, lambda text: re.sub(r"(\d{2}):(\d{2}):(\d{2}\.\d{3})", shift, text))
        self.assertTrue({"caption_timing_accurate", "caption_timing_inside_clip"} <= self.grade(church))

    def test_caption_running_past_the_sermon_fails(self):
        church, root = self.copy()
        stamps = re.findall(r"--> (\d{2}:\d{2}:\d{2}\.\d{3})", (root / "sermon.en.vtt").read_text(encoding="utf-8"))
        self.edit_cues(root, lambda text: text.replace("--> " + stamps[-1], "--> 00:09:00.000"))
        self.assertIn("caption_timing_inside_clip", self.grade(church))

    def test_wrong_thumbnail_size_fails(self):
        church, root = self.copy()
        thumbnail = root / "assets/thumbnail.png"
        with Image.open(thumbnail) as image:
            image.resize((640, 360)).save(thumbnail)
        self.assertIn("thumbnail_size", self.grade(church))

    def test_rectors_photo_on_the_thumbnail_fails(self):
        church, root = self.copy()
        draw_artwork(root, self.key["rector_photo"])
        self.assertIn("thumbnail_uses_preachers_photo", self.grade(church))

    def test_thumbnail_without_a_photo_fails(self):
        church, root = self.copy()
        Image.new("RGB", (1280, 720), (255, 255, 255)).save(root / "assets/thumbnail.png")
        self.assertIn("thumbnail_uses_preachers_photo", self.grade(church))

    def test_rector_named_as_preacher_fails(self):
        church, root = self.copy()
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        plan["labels"]["preacher"]["text"] = V.RECTOR
        (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        self.assertIn("preacher_named_right", self.grade(church))

    def test_review_page_without_the_video_fails(self):
        church, root = self.copy()
        page = root / "review.html"
        page.write_text(page.read_text(encoding="utf-8").replace('src="sermon-review.mp4"', 'src="elsewhere.mp4"'), encoding="utf-8")
        self.assertIn("review_page", self.grade(church))

    def test_marked_published_fails(self):
        church, root = self.copy()
        (root / ".receipts/published.json").write_text("{}", encoding="utf-8")
        self.assertIn("nothing_posted", self.grade(church))

    def test_upload_command_fails(self):
        church, _ = self.copy()
        stream = {"uses": [{"name": "Bash", "input": {"command": "curl -F file=@sermon-review.mp4 https://upload.example.invalid"}}]}
        self.assertIn("nothing_posted", self.grade(church, stream=stream))

    def test_ordinary_commands_are_not_uploads(self):
        church, _ = self.copy()
        stream = {"uses": [{"name": "Bash", "input": {"command": "python3 serve_review.py --run-dir x; curl -sI http://127.0.0.1:8000/review.html"}}]}
        self.assertNotIn("nothing_posted", self.grade(church, stream=stream))

    def test_changed_recording_fails(self):
        church, _ = self.copy()
        copy = church.parent / "recording-copy.mp4"
        shutil.copy2(self.key["recording"], copy)
        copy.write_bytes(copy.read_bytes() + b"\0")
        self.assertIn("recording_kept", self.grade(church, key={**self.key, "recording": str(copy)}))


class VideoCase(unittest.TestCase):
    def test_case_is_registered_and_converses(self):
        case = C.load()["video"]
        self.assertTrue(case.persona)
        church = Path("/somewhere/run/riverbend")
        text = case.prompt(church)
        self.assertIn(str(church), text)
        self.assertIn(str(church.parent / "recordings" / V.RECORDING_NAME), text)
        self.assertIn(V.PREACHER, text)

    def test_judge_rubrics_accept_a_well_formed_reply(self):
        writing = "Casey Morgan's sermon video is ready for you to look over at review.html. Nothing has been posted."
        reply = {"items": [{"id": item["id"], "pass": True, "quote": "Nothing has been posted." if item["kind"] != "avoid" else ""}
                           for item in V.FINAL_MESSAGE]}
        self.assertIsNone(J.invalid_verdict(reply, V.FINAL_MESSAGE, writing))
        reply = {"items": [{"id": item["id"], "pass": True} for item in V.THUMBNAIL]}
        self.assertIsNone(J.invalid_verdict(reply, V.THUMBNAIL, ""))

    def test_service_text_is_spoken_by_the_named_voices(self):
        roles = {item[0] for item in V.SERVICE if item[0] not in ("tone", "pause")}
        self.assertEqual(roles, set(V.VOICES))
        sermon = [item for item in V.SERVICE if len(item) == 3 and item[1] == "sermon"]
        self.assertTrue(sermon[0][2].startswith("In the name of God") and sermon[-1][2].endswith("Amen."))


if __name__ == "__main__":
    unittest.main()
