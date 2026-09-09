import json
import unittest
from pathlib import Path


DATA = Path(__file__).parents[1] / "skills" / "bulletin" / "resources" / "bcp1979" / "sunday.json"


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


class BcpSundayDataTests(unittest.TestCase):
    def test_psalter_has_all_150_psalms_and_contiguous_verses(self):
        data = load_data()
        assert list(data["psalms"]) == [str(number) for number in range(1, 151)]
        for number, psalm in data["psalms"].items():
            assert [verse["number"] for verse in psalm["verses"]] == list(range(1, len(psalm["verses"]) + 1))
            assert all(isinstance(verse["number"], int) for verse in psalm["verses"])
            assert all("first" in verse and "second" in verse for verse in psalm["verses"])
            assert psalm["source_pages"] == list(range(psalm["source_pages"][0], psalm["source_pages"][-1] + 1))
            assert 585 <= psalm["source_pages"][0] <= psalm["source_pages"][-1] <= 808


    def test_known_psalm_shapes_and_source_pages(self):
        data = load_data()
        assert len(data["psalms"]["23"]["verses"]) == 6
        assert len(data["psalms"]["119"]["verses"]) == 176
        assert len(data["psalms"]["150"]["verses"]) == 6
        assert data["psalms"]["1"]["source_pages"] == [585]
        assert data["psalms"]["150"]["source_pages"] == [807, 808]
        assert data["psalms"]["23"]["verses"][0]["first"] == "The Lord is my shepherd;"
        assert data["psalms"]["23"]["verses"][0]["second"] == "I shall not be in want."
        assert data["psalms"]["150"]["verses"][-1]["second"].endswith("Hallelujah!")


    def test_collects_keep_named_alternatives_and_all_saints_page(self):
        data = load_data()
        collects = data["collects"]
        assert {key for key in collects if key.startswith("christmas-day")} == {
            "christmas-day",
            "christmas-day-2",
            "christmas-day-3",
        }
        assert {key for key in collects if key.startswith("easter-day")} == {
            "easter-day",
            "easter-day-2",
            "easter-day-3",
        }
        assert {key for key in collects if key.startswith("pentecost")} == {"pentecost", "pentecost-2"}
        assert collects["all-saints-day"]["source_pages"] == [245]
        assert "knit together your elect" in collects["all-saints-day"]["text"]
        assert all("Preface of " not in item["text"] for item in collects.values())


    def test_prefaces_keep_lords_day_and_saint_alternatives(self):
        data = load_data()
        prefaces = data["prefaces"]
        assert {key for key in prefaces if key.startswith("lords-day")} == {
            "lords-day",
            "lords-day-2",
            "lords-day-3",
        }
        assert {key for key in prefaces if key.startswith("a-saint")} == {"a-saint", "a-saint-2", "a-saint-3"}
        assert "[on this day]" in data["prefaces"]["pentecost"]["text"]
