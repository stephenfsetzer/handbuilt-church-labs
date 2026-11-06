"""When a pastor's words grow or shrink, the bulletin lays itself out again.

A pastor changes words, never positions, so the renderer owns every move a
word change causes. These tests grow and shrink words on the synthetic
Riverbend fixture and read the laid-out pages back from WeasyPrint after each
step, so every part crosses a page edge at some step:

- a heading never ends a page apart from what it introduces;
- a hymn's heading and title stay on the page with its first line of music;
- no page is left empty behind a shorter change;
- announcements that outgrow the back page flow onto added pages in the
  same type size, never shrunk to fit.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import weasyprint
from PIL import Image, ImageDraw

from skills.bulletin.renderer import render_bulletin as renderer
from tests.helpers import REPO_ROOT, bulletin_input


BRAND = {"church": {"name": "Riverbend Lutheran Church"}, "colors": {}, "texts": {}}
TEMPLATES = ("classic", "modern")
# A heading and the lines that belong with it: a hymn's title and composer
# lines travel with its heading, and an announcement's title with its words.
HEADING_CLASSES = {"section-head", "hymn-head", "hymn-title", "hymn-composer", "ann-title"}
SENTENCE = "The reader speaks a synthetic sentence for layout. "


def _music_system(folder: Path, name: str) -> str:
    """A synthetic line of music: five staff lines on a wide white strip."""
    image = Image.new("RGB", (1800, 420), "white")
    draw = ImageDraw.Draw(image)
    for line in range(5):
        y = 80 + line * 40
        draw.line((40, y, 1760, y), fill="black", width=4)
    image.save(folder / name)
    return name


class Pages:
    """The laid-out pages: which page each line of words or music landed on."""

    def __init__(self, document):
        self.count = len(document.pages)
        self.order = []
        self.pages = {}
        self.heading = {}
        self.font_size = {}
        self.inside = {}
        for number, page in enumerate(document.pages):
            self._walk(page._page_box, number, None, ())

    def _walk(self, box, page, heading, ancestors):
        element = getattr(box, "element", None)
        if element is not None and (not ancestors or ancestors[-1] is not element):
            ancestors = ancestors + (element,)
        if element is not None and HEADING_CLASSES & set((element.get("class") or "").split()):
            heading = element
        text = getattr(box, "text", None)
        if element is not None and ((text and text.strip()) or element.tag == "img"):
            key = id(element)
            if key not in self.pages:
                self.order.append(element)
                self.heading[key] = heading
                self.font_size[key] = box.style["font_size"]
                self.inside[key] = ancestors
            self.pages.setdefault(key, set()).add(page)
        for child in getattr(box, "children", None) or []:
            self._walk(child, page, heading, ancestors)

    def stranded_headings(self):
        """Headings whose last line ends a page before the next thing starts."""
        stranded = []
        for line, after in zip(self.order, self.order[1:]):
            heading = self.heading[id(line)]
            if heading is None or self.heading[id(after)] is heading:
                continue
            if max(self.pages[id(line)]) < min(self.pages[id(after)]):
                stranded.append("".join(heading.itertext()).strip())
        return stranded

    def empty_pages(self):
        used = set().union(*self.pages.values())
        return [page + 1 for page in range(self.count) if page not in used]

    def first_lines(self, name):
        """The first line inside each element with this class, in reading order."""
        found, lines = set(), []
        for line in self.order:
            owner = next((element for element in self.inside[id(line)]
                          if name in (element.get("class") or "").split()), None)
            if owner is not None and id(owner) not in found:
                found.add(id(owner))
                lines.append(line)
        return lines


class BulletinReflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._folder = tempfile.TemporaryDirectory()
        cls.folder = Path(cls._folder.name)
        base = bulletin_input()
        base["liturgy"].update({"eucharistic_prayer": "A", "lords_prayer": "traditional",
                                "prayers_of_the_people": "III", "blessing": "omit"})
        for slot, hymn in base["hymns"].items():
            hymn["images"] = [_music_system(cls.folder, f"{slot}-{n}.png") for n in range(3)]
        cls.base = base

    @classmethod
    def tearDownClass(cls) -> None:
        cls._folder.cleanup()

    def lay_out(self, cfg, template) -> Pages:
        content = renderer.build_full_content(cfg, BRAND, REPO_ROOT, self.folder, template)
        html = (f'<html><head><style>{renderer.build_css(template, BRAND)}</style></head>'
                f'<body class="tpl-{template}">{content}</body></html>')
        return Pages(weasyprint.HTML(string=html, base_url=str(self.folder)).render())

    def growing_words(self):
        """Longer and longer words near the front, so every later part crosses a page edge."""
        for steps in range(0, 40, 4):
            cfg = copy.deepcopy(self.base)
            cfg["readings"]["first"]["text"] = SENTENCE * (1 + steps * 3)
            yield steps, cfg

    def test_a_heading_never_ends_a_page_apart_from_what_it_introduces(self) -> None:
        for template in TEMPLATES:
            seen = set()
            for steps, cfg in self.growing_words():
                with self.subTest(template=template, steps=steps):
                    pages = self.lay_out(cfg, template)
                    seen.add(pages.count)
                    self.assertEqual(pages.stranded_headings(), [])
            # The sweep must have moved parts across pages for the check to mean anything.
            self.assertGreater(len(seen), 1, template)

    def test_a_hymn_heading_stays_with_its_first_line_of_music(self) -> None:
        for template in TEMPLATES:
            for steps, cfg in self.growing_words():
                with self.subTest(template=template, steps=steps):
                    pages = self.lay_out(cfg, template)
                    heads = pages.first_lines("hymn-head")
                    self.assertEqual(len(heads), len(cfg["hymns"]))
                    for head in heads:
                        music = next(line for line in pages.order[pages.order.index(head):]
                                     if line.tag == "img")
                        self.assertEqual(min(pages.pages[id(music)]), max(pages.pages[id(head)]),
                                         "".join(head.itertext()))

    def test_a_shorter_change_leaves_no_empty_page_behind(self) -> None:
        for template in TEMPLATES:
            for steps, cfg in reversed(list(self.growing_words())):
                with self.subTest(template=template, steps=steps):
                    self.assertEqual(self.lay_out(cfg, template).empty_pages(), [])

    def test_announcements_flow_onto_added_pages_in_the_same_type(self) -> None:
        for template in TEMPLATES:
            counts, sizes = [], set()
            for many in (1, 6, 14):
                cfg = copy.deepcopy(self.base)
                cfg["announcements"] = [
                    {"title": f"Notice {n + 1}", "text": "Synthetic words for a notice. " * (6 + 3 * n)}
                    for n in range(many)
                ]
                with self.subTest(template=template, announcements=many):
                    pages = self.lay_out(cfg, template)
                    counts.append(pages.count)
                    self.assertEqual(pages.stranded_headings(), [])
                    self.assertEqual(pages.empty_pages(), [])
                    words = pages.first_lines("ann-text")
                    self.assertEqual(len(words), many)
                    sizes.update(pages.font_size[id(line)] for line in words)
            self.assertLess(counts[0], counts[-1], template)
            self.assertEqual(len(sizes), 1, f"{template}: announcement type changed size: {sizes}")


if __name__ == "__main__":
    unittest.main()
