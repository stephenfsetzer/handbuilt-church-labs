import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from skills.bulletin.bulletin_production import interface
from skills.bulletin.bulletin_production.interface import produce
from skills.bulletin.renderer import render_bulletin
from tests.helpers import bulletin_input, make_church


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
