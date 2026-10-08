"""Sermon video: the pure decisions the helper makes before any media tool runs.

The contracts under test: discovery names the provider behind a recording link
without fetching anything, the editing plan refuses labels without evidence and
boundaries that cut off the sermon, captions move into video time after the
opening card, and the measured artwork layout is held to its clear zones. All
data here is invented; no network, FFmpeg, or browser is used.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "skills/sermon-video/scripts/sermon_video.py"
_spec = importlib.util.spec_from_file_location("sermon_video", ENTRY)
video = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(video)

PAGE_URL = "https://example.invalid/worship/"
CHANNEL = "abcdefghij0123456789"
PAGE = f"""
<html><body>
<iframe src="https://www.youtube-nocookie.com/embed/EXAMPLEVID01"></iframe>
<iframe src="https://player.vimeo.com/video/100000001"></iframe>
<a href="https://boxcast.tv/view/example-service">Past services</a>
<a href="/media/service.mp4">Download the service</a>
<a href="/media/bulletin.pdf">Bulletin</a>
<a href="https://www.youtube-nocookie.com/embed/EXAMPLEVID01">Same video again</a>
<div id="boxcast-widget-{CHANNEL}"></div>
<script>boxcast.loadChannel('{CHANNEL}');</script>
</body></html>
"""


def synthetic_plan(**overrides):
    plan = {
        "church": {"name": "Example Church", "website": "https://example.invalid"},
        "source": {"path": "source/service.mp4", "url": "https://example.invalid/service"},
        "sermon": {"start": 1200, "end": 1800, "first_word": 1202, "last_word": 1797,
                   "boundary_evidence": "Invocation and final Amen inspected."},
        "labels": {
            "title": {"text": "An invitation to hope", "status": "editorial", "evidence": "Repeated theme"},
            "scripture": {"text": "Luke 17:5-10", "status": "verified", "evidence": "Recorded Gospel"},
            "sunday": {"text": "A Sunday sermon", "status": "unknown", "evidence": "Not established"},
        },
    }
    for key, value in overrides.items():
        plan[key] = value
    return plan


class DiscoveryTests(unittest.TestCase):
    def test_providers_are_named_from_links_and_embeds(self):
        found = video.discover_candidates(PAGE, PAGE_URL)
        providers = sorted(item["provider"] for item in found if "url" in item)
        self.assertEqual(providers, ["boxcast", "direct", "vimeo", "youtube"])
        direct = next(item for item in found if item["provider"] == "direct")
        self.assertEqual(direct["url"], "https://example.invalid/media/service.mp4")

    def test_boxcast_channel_is_found_once_from_widget_and_script(self):
        found = video.discover_candidates(PAGE, PAGE_URL)
        channels = [item for item in found if "channel" in item]
        self.assertEqual(channels, [{"provider": "boxcast", "channel": CHANNEL, "page_url": PAGE_URL}])

    def test_unrelated_links_are_not_candidates(self):
        found = video.discover_candidates('<a href="/media/bulletin.pdf">Bulletin</a>', PAGE_URL)
        self.assertEqual(found, [])

    def test_source_urls_must_be_web_addresses_without_credentials(self):
        video.validate_url("https://example.invalid/service")
        for bad in ("file:///etc/passwd", "ftp://example.invalid/a.mp4", "https://user:pw@example.invalid/"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                video.validate_url(bad)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "sermon-videos" / "example"
        (self.run_dir / "source").mkdir(parents=True)
        (self.run_dir / "source/service.mp4").write_bytes(b"")

    def load(self, plan):
        path = self.run_dir / "plan.json"
        path.write_text(json.dumps(plan))
        return video.plan(path)

    def test_valid_plan_fills_video_defaults(self):
        root, data = self.load(synthetic_plan())
        self.assertEqual(root, self.run_dir.resolve())
        self.assertEqual(data["video"]["intro_seconds"], 2.5)
        self.assertEqual(Path(data["source"]["path"]), (self.run_dir / "source/service.mp4").resolve())

    def test_label_without_evidence_is_refused(self):
        plan = synthetic_plan()
        plan["labels"]["scripture"] = {"text": "Luke 17:5-10", "status": "verified"}
        with self.assertRaisesRegex(ValueError, "evidence for the scripture"):
            self.load(plan)

    def test_unsupported_status_is_refused(self):
        plan = synthetic_plan()
        plan["labels"]["scripture"]["status"] = "probably"
        with self.assertRaisesRegex(ValueError, "Unsupported label status"):
            self.load(plan)

    def test_only_the_title_may_be_editorial(self):
        plan = synthetic_plan()
        plan["labels"]["preacher"] = {"text": "Alex Example", "status": "editorial", "evidence": "Guess"}
        with self.assertRaisesRegex(ValueError, "Only the title"):
            self.load(plan)

    def test_boundaries_must_hold_the_first_and_last_words(self):
        sermon = {"start": 1200, "end": 1800, "first_word": 1199, "last_word": 1797, "boundary_evidence": "x"}
        with self.assertRaisesRegex(ValueError, "boundaries"):
            self.load(synthetic_plan(sermon=sermon))

    def test_boundaries_need_evidence(self):
        sermon = {"start": 1200, "end": 1800, "first_word": 1202, "last_word": 1797}
        with self.assertRaisesRegex(ValueError, "evidence for the sermon boundaries"):
            self.load(synthetic_plan(sermon=sermon))

    def test_unsupported_video_size_is_refused(self):
        with self.assertRaisesRegex(ValueError, "1920x1080"):
            self.load(synthetic_plan(video={"width": 1000, "height": 1000}))

    def test_run_folder_inside_the_public_plugin_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the public plugin"):
            video.private_dir(ROOT / "skills" / "sermon-video" / "never-created")
        self.assertFalse((ROOT / "skills" / "sermon-video" / "never-created").exists())

    def test_only_verified_or_editorial_labels_appear_in_artwork(self):
        _, data = self.load(synthetic_plan())
        self.assertEqual(video.visible(data, "title"), "An invitation to hope")
        self.assertEqual(video.visible(data, "scripture"), "Luke 17:5-10")
        self.assertEqual(video.visible(data, "sunday"), "")


class CaptionTests(unittest.TestCase):
    DATA = {"sermon": {"start": 100.0, "end": 130.0}, "video": {"intro_seconds": 2.5}}

    def transcription(self, words):
        return {"segments": [{"words": [{"start": a, "end": b, "word": w} for a, b, w in words]}]}

    def test_words_shift_into_video_time_after_the_opening_card(self):
        words = [(1.0, 1.4, " Grace"), (1.5, 1.9, " to"), (2.0, 2.4, " you.")]
        cues = video.caption_cues(self.DATA, self.transcription(words), origin=100.0)
        self.assertEqual(len(cues), 1)
        start, end, text = cues[0]
        self.assertAlmostEqual(start, 1.0 + 2.5)
        self.assertAlmostEqual(end, 2.4 + 2.5)
        self.assertEqual(text, "Grace to you.")

    def test_words_outside_the_sermon_are_left_out(self):
        words = [(-5.0, -4.5, " Before"), (1.0, 1.4, " Inside"), (40.0, 40.5, " After")]
        cues = video.caption_cues(self.DATA, self.transcription(words), origin=100.0)
        self.assertEqual([cue[2] for cue in cues], ["Inside"])

    def test_short_cue_is_held_for_at_least_a_second_but_not_into_the_next(self):
        words = [(1.0, 1.2, " Amen."), (5.0, 5.3, " Peace.")]
        cues = video.caption_cues(self.DATA, self.transcription(words), origin=100.0)
        self.assertAlmostEqual(cues[0][1] - cues[0][0], 1.0)
        self.assertLessEqual(cues[0][1], cues[1][0])

    def test_no_words_inside_the_sermon_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "No word timestamps"):
            video.caption_cues(self.DATA, self.transcription([(0.0, 0.5, " Early")]), origin=0.0)

    def test_timestamps_use_the_caption_formats(self):
        self.assertEqual(video.timestamp(3725.5), "01:02:05.500")
        self.assertEqual(video.timestamp(3725.5, ","), "01:02:05,500")
        self.assertAlmostEqual(video.seconds_from("01:02:05,500"), 3725.5)
        self.assertAlmostEqual(video.seconds_from("02:05.250"), 125.25)

    def test_cue_level_captions_spread_words_across_the_cue(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "service.en.srt"
            path.write_text("1\n00:00:10,000 --> 00:00:12,000\nGrace and peace\n")
            result = video.read_platform_captions(path)
        words = [w for segment in result["segments"] for w in segment["words"]]
        self.assertEqual([w["word"].strip() for w in words], ["Grace", "and", "peace"])
        self.assertAlmostEqual(words[0]["start"], 10.0)
        self.assertAlmostEqual(words[2]["end"], 12.0)
        self.assertEqual(result["provenance"]["word_times"], "estimated from cues")

    def test_youtube_json3_keeps_measured_word_times_and_drops_sound_labels(self):
        events = {"events": [{"tStartMs": 4000, "segs": [{"utf8": "Grace"}, {"utf8": " to", "tOffsetMs": 400},
                                                         {"utf8": " [Music]", "tOffsetMs": 700}]}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "service.en.json3"
            path.write_text(json.dumps(events))
            result = video.read_platform_captions(path)
        words = [w for segment in result["segments"] for w in segment["words"]]
        self.assertEqual([(w["start"], w["word"].strip()) for w in words], [(4.0, "Grace"), (4.4, "to")])
        self.assertEqual(result["provenance"]["word_times"], "measured")


class LayoutTests(unittest.TestCase):
    def audit(self, layout):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "assets").mkdir()
            (root / "assets/layout.json").write_text(json.dumps(layout))
            return video.overlay_audit(root)

    def test_unmeasured_layout_is_reported_not_passed(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(video.overlay_audit(Path(temp))["status"], "not_measured")

    def test_clear_thumbnail_and_panel_pass(self):
        layout = {
            "thumbnail": {"canvas": [1280, 720], "elements": {
                "title": {"x": 64, "y": 205, "w": 400, "h": 120},
                "portrait": {"x": 576, "y": 0, "w": 704, "h": 720}}},
            "lower-third": {"canvas": [1920, 1080], "elements": {"panel": {"x": 96, "y": 880, "w": 800, "h": 100}}},
        }
        self.assertEqual(self.audit(layout)["status"], "passed")

    def test_title_under_the_play_button_and_low_panel_fail(self):
        layout = {
            "thumbnail": {"canvas": [1280, 720], "elements": {
                "title": {"x": 64, "y": 300, "w": 700, "h": 200}}},
            "lower-third": {"canvas": [1920, 1080], "elements": {"panel": {"x": 96, "y": 1000, "w": 800, "h": 70}}},
        }
        problems = " ".join(self.audit(layout)["problems"])
        self.assertIn("play button would cover the title", problems)
        self.assertIn("too close to the bottom edge", problems)

    def test_longer_titles_get_smaller_type(self):
        self.assertGreater(video.thumbnail_title_size("Hope"), video.thumbnail_title_size("A" * 30))
        self.assertGreater(video.thumbnail_title_size("A" * 30), video.thumbnail_title_size("A" * 50))


if __name__ == "__main__":
    unittest.main()
