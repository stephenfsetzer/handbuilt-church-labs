from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from PIL import Image

from tests.helpers import make_church
from tests.test_image_limits import png_header
from tools.image_limits import MAX_IMAGE_BYTES

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "build-my-brand"))

from brand_workflow import DIRECTION_APPLICATIONS, INTERVIEW_KEYS, STAGES, record, survival  # noqa: E402
from brand_workflow import images  # noqa: E402
import urllib.error  # noqa: E402
from brand_workflow import WorkflowFailure  # noqa: E402

CLI = ROOT / "skills" / "build-my-brand" / "scripts" / "brand_workflow.py"
PHASES = [
    {"title": "Start", "stages": ["fork", "discover", "assets", "interview", "identity"], "you_see": "a", "you_decide": "b", "time": "c"},
    {"title": "Idea", "stages": ["direction", "develop", "refine-1", "refine-2"], "you_see": "a", "you_decide": "b", "time": "c"},
    {"title": "System", "stages": ["color", "type", "voice", "art-direction", "build", "prove", "connect", "handoff"], "you_see": "a", "you_decide": "b", "time": "c"},
]
BRIEF = """# Concept: the open door

Use case: the primary mark for an invented parish, printed in one color on a
bulletin cover and stitched on a banner.

Keep: one bold doorway shape with a clear opening; a single flat dark color.
Avoid: crosses added as decoration, gradients, text, clip-art doves.
Composition: centered, generous white ground, nothing touching the edge.
Color: deep navy on plain white.
"""
INSTRUCTION = "Keep everything. Make the opening of the doorway a little taller and the outer edge a little heavier.\n"
# A vectorizer's layered output: a white ground, a dark square moved into
# place by a transform, a white counter over it, and a white speck on the ground.
LAYERED = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
<rect x="0" y="0" width="200" height="200" fill="#FFFFFF"/>
<path d="M0 0 L120 0 L120 120 L0 120 Z" fill="#1B2A44" transform="translate(40,40)"/>
<circle cx="100" cy="100" r="30" fill="#fefefe"/>
<path d="M5 5h4v4h-4z" fill="white"/>
</svg>"""


def _metadata(stage: str) -> dict:
    meta: dict = {}
    if stage == "roadmap":
        meta["phases"] = PHASES
    if stage in {"fork", "identity", "direction"}:
        meta.update({"decision": "new" if stage == "fork" else f"{stage} choice", "rationale": "why",
                     "speaker": "writer" if stage == "voice" else "creative director"})
    if stage == "direction":
        meta.update({"options": ["A", "B"], "applications": list(DIRECTION_APPLICATIONS),
                     "built_from": ["admired: a neighborhood bakery sign", "wild card: a transit map"]})
    if stage == "discover":
        meta["sources"] = [{"label": "site", "kind": "website"}]
    if stage == "assets":
        meta.update({"photos": [], "gaps": ["Every photo"]})
    if stage == "interview":
        meta["answers"] = {k: "a" for k in INTERVIEW_KEYS}
    return meta


def _transparent_png(shade: int = 30) -> bytes:
    """A dark square on a fully transparent ground, the way image models often return a mark."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(20, 44):
        for y in range(20, 44):
            image.putpixel((x, y), (shade, shade, 60, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class FakeImages:
    """A provider with no network: records what it was asked and returns transparent PNGs."""

    name = "fake"

    def __init__(self, svg: str = LAYERED):
        self.calls: list[dict] = []
        self.svg = svg

    def draw(self, prompt, *, n, references, size):
        self.calls.append({"op": "draw", "prompt": prompt, "n": n, "references": references, "size": size})
        return images.Drawn([_transparent_png(20 + i) for i in range(n)], "fake-model-1", None, {"images": n})

    def edit(self, image, instruction, *, n, size):
        self.calls.append({"op": "edit", "image": image, "instruction": instruction, "n": n})
        return images.Drawn([_transparent_png(50 + i) for i in range(n)], "fake-model-1")

    def vectorize(self, image):
        self.calls.append({"op": "vectorize", "image": image})
        return images.Vectorized(self.svg)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ImageStudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.church = make_church(base)
        self.support = base / "support"
        self.env = mock.patch.dict(os.environ, {"HANDBUILT_RUNTIME_HOME": str(self.support / "runtime")})
        self.env.start()
        for name in ("OPENAI_API_KEY", "RECRAFT_API_KEY", "GEMINI_API_KEY", "HANDBUILT_OPENAI_IMAGE_MODEL",
                     "HANDBUILT_RECRAFT_IMAGE_MODEL", "HANDBUILT_GEMINI_IMAGE_MODEL"):
            os.environ.pop(name, None)
        self.briefs = self.church / ".handbuilt" / "build-my-brand" / "scratch" / "briefs"
        self.briefs.mkdir(parents=True)
        (self.briefs / "door.md").write_text(BRIEF)
        (self.briefs / "taller.md").write_text(INSTRUCTION)
        self.brief = ".handbuilt/build-my-brand/scratch/briefs/door.md"
        self.instruction = ".handbuilt/build-my-brand/scratch/briefs/taller.md"
        refs = self.church / ".handbuilt" / "build-my-brand" / "scratch" / "references"
        refs.mkdir(parents=True)
        (refs / "ref.png").write_bytes(_transparent_png())
        self.reference = ".handbuilt/build-my-brand/scratch/references/ref.png"

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _through_direction(self):
        for stage in STAGES:
            self.assertEqual(record(self.church, stage, "text", _metadata(stage))["status"], "recorded")
            if stage == "direction":
                break

    def _receipt(self, result: dict) -> dict:
        return json.loads(Path(result["receipt"]).read_text())

    def test_source_image_header_is_bounded_before_pixel_load_or_conversion(self):
        path = self.church / ".handbuilt" / "build-my-brand" / "scratch" / "references" / "oversized.png"
        path.write_bytes(png_header(5000, 4000))
        raw = path.relative_to(self.church).as_posix()
        with mock.patch.object(Image.Image, "load", side_effect=AssertionError("pixels decoded")), \
                mock.patch.object(Image.Image, "convert", side_effect=AssertionError("pixels converted")):
            with self.assertRaises(WorkflowFailure):
                images._image_input(self.church, raw, "reference")

    def test_source_image_byte_cap_precedes_file_read(self):
        path = self.church / ".handbuilt" / "build-my-brand" / "scratch" / "references" / "oversized.png"
        with path.open("wb") as handle:
            handle.truncate(MAX_IMAGE_BYTES + 1)
        raw = path.relative_to(self.church).as_posix()
        with self.assertRaises(WorkflowFailure):
            images._image_input(self.church, raw, "reference")

    def test_reference_count_is_capped_before_file_read_or_provider_call(self):
        self._through_direction()
        fake = FakeImages()
        references = [self.reference] * (images.MAX_IMAGES + 1)
        with mock.patch.object(images, "_image_input", side_effect=AssertionError("reference read")):
            result = images.draw(self.church, "door-1", self.brief, references=references, provider=fake)
        self.assertEqual(result["errors"][0]["code"], "invalid_count")
        self.assertEqual(fake.calls, [])

    def test_import_count_is_capped_before_file_read_or_layout(self):
        self._through_direction()
        (self.briefs / "prompt.md").write_text(BRIEF)
        files = [self.reference] * (images.MAX_IMAGES + 1)
        with mock.patch.object(images, "_image_input", side_effect=AssertionError("image read")), \
                mock.patch.object(images, "_lay_out", side_effect=AssertionError("layout")):
            result = images.import_images(self.church, "host-1", files, self.brief, tool="Host image generator")
        self.assertEqual(result["errors"][0]["code"], "invalid_count")

    def test_import_total_byte_cap_stops_before_reading_next_image(self):
        self._through_direction()
        (self.briefs / "prompt.md").write_text(BRIEF)
        directory = self.church / ".handbuilt" / "build-my-brand" / "scratch" / "host"
        directory.mkdir(parents=True)
        first = directory / "first.png"
        second = directory / "second.png"
        payload = _transparent_png()
        first.write_bytes(payload)
        second.write_bytes(payload)
        files = [first.relative_to(self.church).as_posix(), second.relative_to(self.church).as_posix()]
        original_open = Path.open
        reads_of_second = []

        class ReadTracked:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def fileno(self):
                return self.handle.fileno()

            def read(self, size=-1):
                reads_of_second.append(size)
                raise AssertionError("second image bytes were read")

        def tracked_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path == second:
                return ReadTracked(handle)
            return handle

        with mock.patch.object(images, "MAX_IMAGE_BATCH_BYTES", len(payload) + 1), \
                mock.patch.object(Path, "open", autospec=True, side_effect=tracked_open), \
                mock.patch.object(images, "_lay_out", side_effect=AssertionError("layout")):
            result = images.import_images(self.church, "host-1", files,
                                          ".handbuilt/build-my-brand/scratch/briefs/prompt.md", tool="Host image generator")
        self.assertEqual(result["errors"][0]["code"], "invalid_image")
        self.assertEqual(reads_of_second, [])

    def test_layout_checks_count_and_total_bytes_before_rendering(self):
        with mock.patch.object(images, "MAX_IMAGE_BATCH_BYTES", 4), \
                mock.patch.object(images, "flatten_on_white", side_effect=AssertionError("image rendered")):
            with self.assertRaises(WorkflowFailure):
                images._lay_out(self.church, "round", "import", [b"123", b"45"], maker="test", receipt={},
                                brief_text="", brief_name="prompt")
        with mock.patch.object(images, "flatten_on_white", side_effect=AssertionError("image rendered")):
            with self.assertRaises(WorkflowFailure):
                images._lay_out(self.church, "round", "import", [b""] * (images.MAX_IMAGES + 1), maker="test", receipt={},
                                brief_text="", brief_name="prompt")

    def test_prepared_reference_byte_cap_blocks_the_provider(self):
        self._through_direction()
        fake = FakeImages()
        with mock.patch.object(images, "MAX_IMAGE_BATCH_BYTES", 4), \
                mock.patch.object(images, "_image_input", return_value=(Path(self.reference), b"a")), \
                mock.patch.object(images, "flatten_on_white", return_value=b"12345"):
            result = images.draw(self.church, "door-1", self.brief, references=[self.reference], provider=fake)
        self.assertEqual(result["errors"][0]["code"], "invalid_image")
        self.assertEqual(fake.calls, [])

    def test_base64_image_limit_is_checked_before_decode(self):
        too_long = "A" * (((MAX_IMAGE_BYTES + 2) // 3) * 4 + 1)
        with mock.patch("base64.b64decode", side_effect=AssertionError("base64 decoded before length check")):
            with self.assertRaises(WorkflowFailure):
                images._decode_limited_base64(too_long, field="synthetic result")

    def test_draw_saves_flattened_pngs_on_the_contact_sheet_with_a_receipt(self):
        fake = FakeImages()
        early = images.draw(self.church, "door-1", self.brief, n=2, provider=fake)
        self.assertEqual(early["errors"][0]["code"], "stage_out_of_order")
        self._through_direction()
        self.assertEqual(images.draw(self.church, "door-1", self.brief, n=0, provider=fake)["errors"][0]["code"], "invalid_count")
        result = images.draw(self.church, "Door 1", self.brief, n=3, references=[self.reference], provider=fake)
        self.assertEqual(result["status"], "drawn", result)
        self.assertEqual(result["round"], "door-1")
        self.assertEqual([a["id"] for a in result["added"]], ["door-1-01", "door-1-02", "door-1-03"])
        for item in result["added"]:
            path = self.church / item["file"]
            self.assertTrue(item["file"].startswith("brand/staging/explorations/door-1/"))
            with Image.open(path) as image:
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertTrue((self.church / result["contact_sheet"]).is_file())
        self.assertEqual(fake.calls[0]["prompt"], BRIEF)
        with Image.open(io.BytesIO(fake.calls[0]["references"][0])) as sent:
            self.assertEqual(sent.mode, "RGB")
        receipt = self._receipt(result)
        self.assertEqual(receipt["kind"], "image-draw")
        self.assertEqual((receipt["provider"], receipt["model"]), ("fake", "fake-model-1"))
        self.assertEqual(receipt["brief"], self.brief)
        self.assertEqual(receipt["brief_sha256"], _sha(BRIEF.encode()))
        self.assertEqual(receipt["inputs"], [{"file": self.reference, "sha256": _sha(_transparent_png()), "role": "reference"}])
        self.assertIsNone(receipt["cost"])
        self.assertEqual(receipt["usage"], {"images": 3})
        self.assertTrue(receipt["flattened_on_white"])
        for output in receipt["outputs"]:
            self.assertEqual(output["sha256"], _sha((self.church / output["file"]).read_bytes()))
        self.assertTrue((self.church / receipt["outputs"][0]["original"]["file"]).is_file())

    def test_edit_one_chosen_image_adds_variations_with_a_receipt(self):
        self._through_direction()
        fake = FakeImages()
        drawn = images.draw(self.church, "door-1", self.brief, n=2, provider=fake)
        chosen = drawn["added"][1]["file"]
        result = images.edit(self.church, "door-1", chosen, self.instruction, n=2, provider=fake)
        self.assertEqual(result["status"], "edited", result)
        self.assertEqual(result["files"], 4)
        self.assertEqual(fake.calls[-1]["instruction"], INSTRUCTION)
        receipt = self._receipt(result)
        self.assertEqual(receipt["kind"], "image-edit")
        self.assertEqual(receipt["inputs"][0]["file"], chosen)
        self.assertEqual(receipt["inputs"][0]["sha256"], _sha((self.church / chosen).read_bytes()))
        self.assertEqual(receipt["brief_sha256"], _sha(INSTRUCTION.encode()))
        with Image.open(self.church / result["added"][0]["file"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_import_registers_host_images_without_network(self):
        self._through_direction()
        made = self.church / ".handbuilt" / "build-my-brand" / "scratch" / "host"
        made.mkdir(parents=True)
        (made / "a.png").write_bytes(_transparent_png())
        (self.briefs / "prompt.md").write_text(BRIEF)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
            result = images.import_images(self.church, "host-1", [".handbuilt/build-my-brand/scratch/host/a.png"],
                                          ".handbuilt/build-my-brand/scratch/briefs/prompt.md", tool="Host image generator")
        self.assertEqual(result["status"], "imported", result)
        with Image.open(self.church / result["added"][0]["file"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        receipt = self._receipt(result)
        self.assertEqual(receipt["kind"], "image-import")
        self.assertEqual((receipt["provider"], receipt["tool"], receipt["network"]), ("import", "Host image generator", False))
        self.assertEqual(receipt["brief_sha256"], _sha(BRIEF.encode()))
        missing_tool = images.import_images(self.church, "host-1", [".handbuilt/build-my-brand/scratch/host/a.png"],
                                            ".handbuilt/build-my-brand/scratch/briefs/prompt.md", tool=" ")
        self.assertEqual(missing_tool["errors"][0]["field"], "tool")

    def test_normalize_folds_layers_into_one_evenodd_current_color_path(self):
        svg, summary = images.normalize_mark_svg(LAYERED)
        root = ET.fromstring(svg)
        children = list(root)
        self.assertEqual(len(children), 1)
        path = children[0]
        self.assertEqual(path.tag.rsplit("}", 1)[-1], "path")
        self.assertEqual(path.get("fill"), "currentColor")
        self.assertEqual(path.get("fill-rule"), "evenodd")
        self.assertEqual(len(re.findall("M", path.get("d"))), 2)
        box = [float(v) for v in root.get("viewBox").split()]
        self.assertAlmostEqual(box[2], box[3])
        self.assertLessEqual(box[0], 40)
        self.assertGreaterEqual(box[0] + box[2], 160)
        self.assertEqual((summary["background_removed"], summary["holes_folded"], summary["white_specks_dropped"]), (1, 1, 1))
        self.assertNotIn("#1B2A44", svg)
        self.assertNotIn("rect", svg)
        dark_ground = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#102030"/><circle cx="5" cy="5" r="2" fill="#fff"/></svg>'
        with self.assertRaises(images.WorkflowFailure) as caught:
            images.normalize_mark_svg(dark_ground)
        self.assertIn("white ground", caught.exception.message)

    def test_vectorize_writes_a_checked_mark_and_a_receipt(self):
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            self.skipTest("WeasyPrint is not available in this interpreter")
        self._through_direction()
        fake = FakeImages()
        drawn = images.draw(self.church, "door-1", self.brief, n=1, provider=fake)
        source = drawn["added"][0]["file"]
        outside = images.vectorize(self.church, source, "brand/mark.svg", provider=fake)
        self.assertEqual(outside["errors"][0]["field"], "out")
        result = images.vectorize(self.church, source, "brand/staging/marks/mark.svg", provider=fake)
        self.assertEqual(result["status"], "vectorized", result)
        mark = self.church / "brand" / "staging" / "marks" / "mark.svg"
        survival.validate_mark_svg(mark, one_color=True)
        self.assertEqual(result["normalized"]["holes_folded"], 1)
        checks = {c["check"]: c["passed"] for c in result["survival"]["checks"]}
        self.assertTrue(checks["one_color"])
        self.assertTrue(checks["reversal"])
        with Image.open(io.BytesIO(fake.calls[-1]["image"])) as sent:
            self.assertEqual(sent.mode, "RGB")
        receipt = self._receipt(result)
        self.assertEqual(receipt["kind"], "image-vectorize")
        self.assertEqual(receipt["inputs"][0]["sha256"], _sha((self.church / source).read_bytes()))
        self.assertEqual(receipt["outputs"][0]["sha256"], _sha(mark.read_bytes()))
        self.assertIsNone(receipt["cost"])
        self.assertTrue((self.church / receipt["raw_svg"]["file"]).is_file())

    def test_missing_key_is_a_clear_pastor_safe_stop_before_any_network(self):
        self._through_direction()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
            result = images.draw(self.church, "door-1", self.brief, n=1, provider="openai")
            vector = images.vectorize(self.church, self.reference, "brand/staging/marks/mark.svg")
        self.assertEqual(result["status"], "blocked")
        error = result["errors"][0]
        self.assertEqual(error["code"], "image_key_missing")
        self.assertIn("nothing was charged", error["message"])
        self.assertIn("keys set --provider openai", error["message"])
        self.assertIn("Do not ask the pastor for a key", error["message"])
        self.assertIn("Without an image service", error["message"])
        self.assertIn("never in the church folder", error["message"])
        self.assertEqual(vector["errors"][0]["code"], "image_key_missing")
        self.assertFalse((self.church / "brand" / "staging" / "explorations" / "door-1").exists())
        stub = images.draw(self.church, "door-1", self.brief, n=1, provider="handbuilt")
        self.assertEqual(stub["errors"][0]["code"], "not_available_yet")

    def test_openai_request_sends_the_brief_and_reads_images(self):
        os.environ["OPENAI_API_KEY"] = "fake-openai-value-123"
        payload = base64.b64encode(_transparent_png()).decode()
        seen = {}

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=-1):
                return self.body if size < 0 else self.body[:size]

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data)
            seen["auth"] = request.get_header("Authorization")
            return Response(json.dumps({"data": [{"b64_json": payload}], "usage": {"total_tokens": 7}}).encode())

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            drawn = images.OpenAIImages().draw("a brief", n=1, references=[], size="1024x1024")
        self.assertEqual(seen["url"], "https://api.openai.com/v1/images/generations")
        self.assertEqual(seen["body"], {"model": "gpt-image-2.5-sunburst", "prompt": "a brief", "n": 1, "size": "1024x1024", "background": "opaque"})
        self.assertEqual(seen["auth"], "Bearer fake-openai-value-123")
        self.assertEqual(drawn.images, [_transparent_png()])
        self.assertIsNone(drawn.cost)
        os.environ["HANDBUILT_OPENAI_IMAGE_MODEL"] = "another-image-model"
        self.assertEqual(images.OpenAIImages().model, "another-image-model")

    def test_openai_falls_back_when_the_account_cannot_use_the_newest_model(self):
        os.environ["OPENAI_API_KEY"] = "fake-openai-value-123"
        payload = base64.b64encode(_transparent_png()).decode()
        asked = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=-1):
                body = json.dumps({"data": [{"b64_json": payload}]}).encode()
                return body if size < 0 else body[:size]

        def fake_urlopen(request, timeout=None):
            model = json.loads(request.data)["model"]
            asked.append(model)
            if model != "gpt-image-1":
                body = io.BytesIO(json.dumps({"error": {"message": f"Your organization must be verified to use the model {model}."}}).encode())
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, body)
            return Response()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            drawn = images.OpenAIImages().draw("a brief", n=1, references=[], size="1024x1024")
        self.assertEqual(asked, ["gpt-image-2.5-sunburst", "gpt-image-2", "gpt-image-1"])
        self.assertEqual(drawn.model, "gpt-image-1")

        def refuse_everything(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error": {"message": "Incorrect API key"}}'))

        with mock.patch("urllib.request.urlopen", side_effect=refuse_everything):
            with self.assertRaises(WorkflowFailure) as caught:
                images.OpenAIImages().draw("a brief", n=1, references=[], size="1024x1024")
        self.assertIn("HTTP 401", caught.exception.message)

    def test_openai_edit_asks_for_an_opaque_image(self):
        os.environ["OPENAI_API_KEY"] = "fake-openai-value-123"
        payload = base64.b64encode(_transparent_png()).decode()
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=-1):
                body = json.dumps({"data": [{"b64_json": payload}]}).encode()
                return body if size < 0 else body[:size]

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["body"] = request.data
            return Response()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            images.OpenAIImages().edit(_transparent_png(), "make the ground navy", n=1, size="1536x1024")
        self.assertEqual(seen["url"], "https://api.openai.com/v1/images/edits")
        self.assertRegex(seen["body"], rb'name="background"\r\n\r\nopaque\r\n')

    def test_gemini_request_sends_the_brief_and_references_once_per_image(self):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-value-456"
        payload = base64.b64encode(_transparent_png()).decode()
        seen = []

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=-1):
                return self.body if size < 0 else self.body[:size]

        def fake_urlopen(request, timeout=None):
            seen.append({"url": request.full_url, "body": json.loads(request.data),
                         "key": request.get_header("X-goog-api-key"), "auth": request.get_header("Authorization")})
            return Response(json.dumps({"candidates": [{"content": {"parts": [{"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": payload}}]}}],
                                        "usageMetadata": {"totalTokenCount": 9}}).encode())

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            drawn = images.GeminiImages().draw("a brief", n=2, references=[b"ref"], size="1536x1024")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent")
        self.assertEqual(seen[0]["key"], "fake-gemini-value-456")
        self.assertIsNone(seen[0]["auth"])
        parts = seen[0]["body"]["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "a brief"})
        self.assertEqual(parts[1]["inline_data"]["data"], base64.b64encode(b"ref").decode())
        self.assertEqual(seen[0]["body"]["generationConfig"]["imageConfig"], {"aspectRatio": "3:2"})
        self.assertEqual(drawn.images, [_transparent_png(), _transparent_png()])
        self.assertIsNone(drawn.cost)
        with self.assertRaises(images.WorkflowFailure):
            images.GeminiImages().vectorize(b"x")

    def _cli(self, *argv: str, stdin: str = "") -> tuple[int, str, dict]:
        done = subprocess.run([sys.executable, str(CLI), *argv], input=stdin, capture_output=True, text=True, env=dict(os.environ))
        return done.returncode, done.stdout, json.loads(done.stdout)

    def test_keys_live_on_this_computer_and_status_never_prints_them(self):
        value = "fake-openai-value-123"
        code, _out, status = self._cli("keys", "status", "--church-folder", str(self.church))
        self.assertEqual(code, 0)
        self.assertFalse(status["providers"]["openai"]["configured"])
        self.assertEqual(status["studio"], "none")
        self.assertIn("Do not ask the pastor for keys", status["next_action"])
        code, out, saved = self._cli("keys", "set", "--provider", "openai", "--church-folder", str(self.church), stdin=value + "\n")
        self.assertEqual(code, 0, out)
        self.assertNotIn(value, out)
        path = Path(saved["key_file"])
        self.assertEqual(path, self.support / images.KEY_FILE_NAME)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn(str(self.church), str(path))
        code, out, status = self._cli("keys", "status", "--church-folder", str(self.church))
        self.assertNotIn(value, out)
        self.assertEqual(status["providers"]["openai"]["source"], "key_file")
        self.assertFalse(status["providers"]["recraft"]["configured"])
        self.assertEqual(images.service_key("openai"), value)
        os.environ["RECRAFT_API_KEY"] = "fake-recraft-value-456"
        code, out, status = self._cli("keys", "status")
        self.assertNotIn("fake-recraft-value-456", out)
        self.assertEqual(status["providers"]["recraft"]["source"], "environment")
        self.assertEqual(status["studio"], "image services")
        self.assertNotIn("fake-recraft-value-456", path.read_text())
        os.environ["HANDBUILT_RUNTIME_HOME"] = str(self.church / "runtime")
        refused = images.keys_set("openai", value, self.church)
        self.assertEqual(refused["errors"][0]["code"], "key_inside_church_folder")
        self.assertFalse((self.church / images.KEY_FILE_NAME).exists())

    def test_cli_and_launcher_expose_the_image_studio(self):
        for command in ("draw", "edit", "vectorize", "import-images", "keys"):
            done = subprocess.run([sys.executable, str(CLI), command, "--help"], capture_output=True, text=True)
            self.assertEqual(json.loads(done.stdout)["status"], "help")
        source = (ROOT / "tools" / "church_workflow.py").read_text()
        for operation in ("draw", "edit", "vectorize", "import-images", "keys"):
            self.assertIn(f'"{operation}"', source)


if __name__ == "__main__":
    unittest.main()
