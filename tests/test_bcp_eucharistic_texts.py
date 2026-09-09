import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LITURGY = ROOT / "skills" / "bulletin" / "renderer" / "liturgy"
SOURCE_URL = "https://www.episcopalchurch.org/wp-content/uploads/2021/02/book-of-common-prayer-2006.pdf"


def load_renderer():
    path = ROOT / "skills" / "bulletin" / "renderer" / "render_bulletin.py"
    spec = importlib.util.spec_from_file_location("handbuilt_render_bulletin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BcpEucharisticTextTests(unittest.TestCase):
    def test_standard_prayers_have_source_record_and_sanctus(self):
        for letter, pages in (("a-full", "361-363"), ("b-full", "367-369"),
                              ("c-full", "369-372"), ("d-full", "372-375")):
            text = (LITURGY / f"eucharistic-prayer-{letter}.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("The Book of Common Prayer (1979)", text)
            self.assertIn(f"pp. {pages}", text)
            self.assertIn(SOURCE_URL, text)
            self.assertIn("## The Sanctus", text)
            self.assertIn("Holy, holy, holy Lord, God of power and might,", text)
            self.assertIn("Blessed is he who comes in the name of the Lord.", text)

    def test_prayers_use_canonical_distinctive_words(self):
        a = (LITURGY / "eucharistic-prayer-a-full.md").read_text(encoding="utf-8")
        b = (LITURGY / "eucharistic-prayer-b-full.md").read_text(encoding="utf-8")
        c = (LITURGY / "eucharistic-prayer-c-full.md").read_text(encoding="utf-8")
        d = (LITURGY / "eucharistic-prayer-d-full.md").read_text(encoding="utf-8")
        self.assertIn("Holy and gracious Father", a)
        self.assertIn("O Father, in this sacrifice of praise and thanksgiving", a)
        self.assertIn("Therefore, according to his command, O Father", b)
        self.assertIn("the vast expanse of interstellar space", c)
        self.assertGreaterEqual(c.count("**People"), 11)
        self.assertIn("dwelling in light inaccessible", d)
        self.assertIn("We praise you, we bless you,", d)

    def test_preface_marker_is_only_in_a_full_and_b(self):
        a_full = (LITURGY / "eucharistic-prayer-a-full.md").read_text(encoding="utf-8")
        a_short = (LITURGY / "eucharistic-prayer-a.md").read_text(encoding="utf-8")
        self.assertIn("[Proper Preface inserted here]", a_full)
        self.assertIn("[Proper Preface inserted here]", (LITURGY / "eucharistic-prayer-b-full.md").read_text(encoding="utf-8"))
        self.assertNotIn("[Proper Preface inserted here]", a_short)
        for letter in ("c", "d"):
            text = (LITURGY / f"eucharistic-prayer-{letter}-full.md").read_text(encoding="utf-8")
            self.assertNotIn("[Proper Preface inserted here]", text)

    def test_abridged_b_c_d_identify_editorial_omissions(self):
        for letter in ("b", "c", "d"):
            text = (LITURGY / f"eucharistic-prayer-{letter}.md").read_text(encoding="utf-8")
            self.assertIn("Editorial omission:", text)
            self.assertNotIn("[Proper Preface inserted here]", text)

    def test_short_a_identifies_editorial_omissions(self):
        text = (LITURGY / "eucharistic-prayer-a.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("Editorial omission:"), 3)
        self.assertIn("Christ has died. Christ is risen. Christ will come again.", text)

    def test_d_optional_blanks_are_not_rendered(self):
        text = (LITURGY / "eucharistic-prayer-d-full.md").read_text(encoding="utf-8")
        self.assertIn("[Remember ___________.]", text)
        self.assertIn("blank source underscores are never printed", text)
        renderer = load_renderer()
        rendered = renderer.render_blocks(
            renderer.parse_liturgy(LITURGY / "eucharistic-prayer-d-full.md"), {}
        )
        self.assertNotIn("________", rendered)


if __name__ == "__main__":
    unittest.main()
