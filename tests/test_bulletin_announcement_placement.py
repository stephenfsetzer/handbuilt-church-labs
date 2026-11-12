import unittest
from pathlib import Path
from unittest.mock import patch

from skills.bulletin.renderer import render_bulletin


def _cfg(placement=None):
    options = {} if placement is None else {"announcements_placement": placement}
    return {
        "service": {"date": "2026-09-27", "occasion": "Synthetic Sunday"},
        "hymns": {}, "service_music": {}, "options": options,
        "liturgy": {"service_plan": "episcopal-rite-ii", "blessing": "omit",
                    "eucharistic_prayer": "eucharistic-prayer-a",
                    "lords_prayer": "lords-prayer-traditional",
                    "prayers_of_the_people": "prayers-of-the-people"},
        "readings": {}, "collect_of_day": "Synthetic collect",
        "announcements": [{"title": "Synthetic Event", "text": "Synthetic details."}],
    }


STUBS = {
    "cover_page": lambda *args: "<cover>",
    "service_title": lambda text: f"<{text}>",
    "liturgy_steps": lambda order, unit, ctx, **kwargs: f"<{unit}>",
    "reading_block": lambda *args: "<reading>",
    "psalm_block": lambda *args: "<psalm>",
    "gospel_block": lambda *args: "<gospel>",
    "qr_block": lambda *args: "<qr>",
    "doxology_block": lambda *args: "<doxology>",
    "blessing_block": lambda *args: "<blessing>",
    "leadership_block": lambda *args: "<leadership>",
    "leadership_directory_block": lambda *args: "",
    "footer_line": lambda *args, **kwargs: "<footer>",
    "can_merge_back_page": lambda *args: False,
}


class AnnouncementPlacementTests(unittest.TestCase):
    def _render(self, cfg):
        with patch.multiple(render_bulletin, **STUBS):
            return render_bulletin.build_full_content(
                cfg, {"church": {}}, Path("/tmp"), Path("/tmp"), "modern")

    def test_default_keeps_announcements_on_back_page(self):
        html = self._render(_cfg())
        self.assertEqual(html.count("Synthetic Event"), 1)
        self.assertGreater(html.index("Synthetic Event"), html.index("<dismissal>"))

    def test_after_connect_give_prints_once_after_qr(self):
        html = self._render(_cfg("after_connect_give"))
        self.assertEqual(html.count("Synthetic Event"), 1)
        self.assertLess(html.index("<qr>"), html.index("Synthetic Event"))
        self.assertLess(html.index("Synthetic Event"), html.index("<dismissal>"))

    def test_unknown_value_keeps_default(self):
        self.assertEqual(render_bulletin.announcements_placement(_cfg("sideways")), "back_page")


if __name__ == "__main__":
    unittest.main()
