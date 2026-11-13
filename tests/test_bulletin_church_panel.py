"""A back cover with nothing else on it says who the church is and when it worships."""
import unittest
from pathlib import Path

from skills.bulletin.renderer import render_bulletin as R

ROOT = Path(__file__).resolve().parents[1]

# An invented church.
BRAND = {"church": {
    "name": "Harbor Light Chapel", "address": "12 Quay Road, Tidewater",
    "phone": "555-0100", "website": "https://harborlight.example",
    "regular_services": [
        {"day": "Saturday", "time": "5:00 PM", "label": "Evening Prayer"},
        {"day": "Sunday", "time": "9:30 AM", "label": "Holy Eucharist with music"},
    ],
}}


def back(cfg, brand=BRAND, **options):
    return R.announcements_block({"service": {}, **cfg}, brand, ROOT, **options)


class ChurchPanelTests(unittest.TestCase):
    def test_an_empty_back_cover_carries_the_church_and_its_services(self):
        html = back({"announcements": []})
        self.assertIn("church-panel", html)
        self.assertIn("Harbor Light Chapel", html)
        self.assertIn("Worship with Us", html)
        self.assertIn("Saturday", html)
        self.assertIn("5:00 PM", html)
        self.assertIn("Holy Eucharist with music", html)
        self.assertIn("12 Quay Road, Tidewater", html)
        self.assertIn("https://harborlight.example", html)

    def test_announcements_take_the_back_cover_and_the_panel_stays_away(self):
        html = back({"announcements": [{"title": "Harvest supper", "text": "Bring a dish."}]})
        self.assertIn("Harvest supper", html)
        self.assertNotIn("church-panel", html)

    def test_saved_welcome_text_also_keeps_the_panel_away(self):
        html = back({"announcements": [],
                     "parish_information": {"after_service": [{"title": "Welcome", "text": "Stay for coffee."}]}})
        self.assertIn("Stay for coffee.", html)
        self.assertNotIn("church-panel", html)

    def test_announcements_printed_earlier_still_leave_a_panel_on_the_back(self):
        html = back({"announcements": [{"title": "Harvest supper", "text": "Bring a dish."}]},
                    include_items=False)
        self.assertIn("church-panel", html)
        self.assertNotIn("Harvest supper", html)

    def test_only_saved_details_print(self):
        html = R.church_panel({"church": {"name": "Harbor Light Chapel"}})
        self.assertIn("Harbor Light Chapel", html)
        for absent in ("Worship with Us", "Find Us", "Phone", "Email"):
            self.assertNotIn(absent, html)

    def test_a_church_with_nothing_saved_prints_no_panel(self):
        self.assertEqual(R.church_panel({"church": {}}), "")

    def test_details_are_escaped(self):
        html = R.church_panel({"church": {"name": "Saints <Peter & Paul>"}})
        self.assertIn("Saints &lt;Peter &amp; Paul&gt;", html)


class BrandStagingTests(unittest.TestCase):
    def test_every_regular_service_reaches_the_renderer(self):
        source = (ROOT / "skills/bulletin/bulletin_production/interface.py").read_text(encoding="utf-8")
        self.assertIn('printed["regular_services"]', source)


if __name__ == "__main__":
    unittest.main()
