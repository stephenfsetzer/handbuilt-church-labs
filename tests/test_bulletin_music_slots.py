import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from pypdf.generic import ContentStream

from skills.bulletin.bulletin_production import interface
from skills.bulletin.bulletin_production.interface import produce
from skills.bulletin.renderer import render_bulletin
from tests.helpers import bulletin_input, make_church


def _painted_image_colors(page):
    """Average colors of every Image XObject this page's content stream
    actually paints with a ``Do`` operator, recursing into Form XObjects.

    A resource dictionary can be shared across every page by the renderer,
    so listing ``/Resources/XObject`` proves nothing about what a given
    page paints. Reading the page's own drawing operations does.
    """
    colors = []
    seen_forms = set()

    def xobjects_of(resources):
        if resources is None:
            return {}
        table = resources.get("/XObject")
        return dict(table) if table else {}

    def walk(contents, resources):
        stream = ContentStream(contents, page.pdf)
        table = xobjects_of(resources)
        for operands, operator in stream.operations:
            if operator != b"Do" or not operands:
                continue
            name = str(operands[0])
            ref = table.get(name) or table.get(name.lstrip("/"))
            if ref is None:
                continue
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Form":
                key = getattr(ref, "indirect_reference", None) or id(obj)
                if key in seen_forms:
                    continue
                seen_forms.add(key)
                walk(obj, obj.get("/Resources", resources))
            elif obj.get("/Subtype") == "/Image":
                from PIL import Image
                import io
                width, height = obj["/Width"], obj["/Height"]
                data = obj.get_data()
                try:
                    image = Image.open(io.BytesIO(data))
                except Exception:
                    image = Image.frombytes("RGB", (width, height), data[: width * height * 3])
                colors.append(image.convert("RGB").getpixel((image.width // 2, image.height // 2)))

    contents = page.get_contents()
    if contents is not None:
        walk(contents, page.get("/Resources"))
    return colors


def _music(title):
    return {"title": title, "composer": "A & <Composer>",
            "lyrics": [{"speaker": "All", "lines": [title]}]}


class ServiceMusicValidationTests(unittest.TestCase):
    def test_unknown_nonempty_slot_is_actionable(self):
        with self.assertRaises(interface.StageFailure) as raised:
            interface._validate_service_music({
                "liturgy": {"service_plan": "episcopal-rite-ii"},
                "service_music": {"organ_interlude": _music("Lost")},
            })
        self.assertEqual(raised.exception.code, "unsupported_service_music")
        self.assertEqual(raised.exception.field, "service_music.organ_interlude")

    def test_empty_unknown_slot_remains_compatible(self):
        interface._validate_service_music({
            "liturgy": {"service_plan": "episcopal-rite-ii"},
            "service_music": {"organ_interlude": None},
        })


class ServiceMusicRenderingTests(unittest.TestCase):
    def test_supported_slots_render_in_service_order(self):
        music = {slot: _music(slot) for slot in (
            "prelude", "gloria", "psalm_antiphon", "offertory_anthem",
            "sursum_corda", "communion_anthem", "postlude")}
        cfg = {
            "service": {"preacher": "Synthetic Preacher"},
            "hymns": {}, "service_music": music, "options": {},
            "liturgy": {"service_plan": "episcopal-rite-ii", "blessing": "omit",
                        "eucharistic_prayer": "eucharistic-prayer-a",
                        "lords_prayer": "lords-prayer-traditional",
                        "prayers_of_the_people": "prayers-of-the-people"},
            "readings": {}, "collect_of_day": "Synthetic collect",
        }
        stubs = {
            "cover_page": lambda *args: "<cover>",
            "service_title": lambda text: f"<{text}>",
            "liturgy_steps": lambda order, unit, ctx, **kwargs: f"<{unit}>",
            "reading_block": lambda *args: "<reading>",
            "psalm_block": lambda *args: "<psalm>",
            "gospel_block": lambda *args: "<gospel>",
            "qr_block": lambda *args: "<qr>",
            "doxology_block": lambda *args: "<doxology>",
            "blessing_block": lambda *args: "<blessing>",
            "announcements_block": lambda *args: "<announcements>",
            "can_merge_back_page": lambda *args: False,
        }
        with patch.multiple(render_bulletin, **stubs):
            html = render_bulletin.build_full_content(
                cfg, {"church": {}}, Path("/tmp"), Path("/tmp"), "classic")
        positions = [html.index(slot) for slot in (
            "prelude", "gloria", "psalm_antiphon", "offertory_anthem",
            "sursum_corda", "communion_anthem", "postlude")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("<eucharistic-prayer>", html)
        self.assertIn("Composer: A &amp; &lt;Composer&gt;", html)

    def test_canonical_production_preserves_supplied_lyrics_and_image_classic_and_modern(self):
        for template, service_date in (("classic", "2026-09-20"), ("modern", "2026-09-27")):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                music_dir = church / "music"
                music_dir.mkdir(exist_ok=True)
                from PIL import Image
                Image.new("RGB", (240, 120), "white").save(music_dir / "supplied.png")
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["service"]["date"] = service_date
                bulletin["service_music"] = {
                    "prelude": {"title": "Supplied Prelude", "composer": "Synthetic Composer",
                                "image": "music/supplied.png",
                                "lyrics": [{"speaker": "All", "lines": ["Supplied lyric survives"]}]},
                    "offertory_anthem": {"title": "Supplied Anthem", "lyrics": [
                        {"speaker": "Choir", "lines": ["Anthem lyric survives"]}]},
                }
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                supplied_fallbacks = [
                    item for item in result["warnings"]
                    if item["code"] == "music_title_fallback"
                    and item.get("field", "").startswith("service_music.")
                ]
                self.assertEqual(supplied_fallbacks, [])
                folder = Path(result["week_folder"])
                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                self.assertIn("Supplied Prelude", html)
                self.assertIn("Supplied lyric survives", html)
                self.assertIn("Anthem lyric survives", html)
                self.assertIn("hymn-images/supplied.png", html)
                self.assertIn("Synthetic Composer", html)
                pdf = next(folder.glob(f"*{template}.pdf"))
                text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
                self.assertIn("Supplied Prelude", text)
                self.assertIn("Supplied lyric survives", text)

    def test_long_sanctus_setting_keeps_its_heading_with_the_first_system(self):
        # Real page geometry, not HTML class presence, and not merely
        # /Resources/XObject presence (WeasyPrint can share one resource
        # dictionary across every page, so that proves nothing about what a
        # given page paints). Eight distinct panels, checked in both
        # canonical layouts, through the actual produce() interface.
        from PIL import Image
        colors = [
            (220, 20, 60), (34, 139, 34), (30, 60, 200), (255, 165, 0),
            (128, 0, 128), (0, 139, 139), (184, 134, 11), (105, 105, 105),
        ]
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                music_dir = church / "music"
                music_dir.mkdir(exist_ok=True)
                for i, color in enumerate(colors):
                    # Tall enough that each system alone approaches a full
                    # page, so eight of them cannot be compressed together.
                    Image.new("RGB", (500, 2000), color).save(music_dir / f"sanctus{i}.png")

                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["liturgy"].update({
                    "eucharistic_prayer": "A", "lords_prayer": "traditional",
                    "prayers_of_the_people": "III", "blessing": "omit",
                })
                bulletin["service_music"]["sanctus"] = {
                    "title": "Long Sanctus Setting",
                    "images": [f"music/sanctus{i}.png" for i in range(len(colors))],
                }
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                for i in range(len(colors)):
                    self.assertIn(f"hymn-images/sanctus{i}.png", html)

                pdf = next(folder.glob(f"*{template}.pdf"))
                reader = PdfReader(str(pdf))
                pages_painting = {
                    index: _painted_image_colors(page)
                    for index, page in enumerate(reader.pages)
                }
                heading_index = next(
                    index for index, page in enumerate(reader.pages)
                    if "Sung by all." in (page.extract_text() or "")
                )

                # The heading's own page paints the first supplied system,
                # and only it: later systems flow to their own pages rather
                # than all eight being forced together with the heading.
                self.assertEqual(pages_painting[heading_index], [colors[0]])

                # Every system reached the PDF, none dropped or duplicated,
                # each on its own later page, in supplied order.
                later_pages = [
                    index for index in sorted(pages_painting)
                    if index > heading_index and pages_painting[index]
                ]
                self.assertEqual(len(later_pages), len(colors) - 1)
                for offset, page_index in enumerate(later_pages, start=1):
                    self.assertEqual(pages_painting[page_index], [colors[offset]])

    def test_unsupported_lutheran_slot_blocks_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            before = sorted((church / "bulletins").rglob("*")) if (church / "bulletins").exists() else []
            bulletin = bulletin_input()
            bulletin["service_music"] = {"gloria": _music("Unsupported Gloria")}
            bulletin["liturgy"]["service_plan"] = "lutheran-holy-communion"
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["code"], "unsupported_service_music")
            after = sorted((church / "bulletins").rglob("*")) if (church / "bulletins").exists() else []
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
