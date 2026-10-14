from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce, revise
from skills.bulletin.renderer.render_bulletin import psalm_block
from tests.helpers import bulletin_input, make_church


def _pages(result):
    folder = Path(result["week_folder"])
    pdf = next(path for path in folder.glob("*-modern.pdf"))
    return [" ".join((page.extract_text() or "").split()) for page in PdfReader(pdf).pages]


def _psalm_page(pages):
    return next(index for index, text in enumerate(pages) if "THE LEADER READS THE FIRST HALF" in text.upper())


class PsalmHeadingTest(unittest.TestCase):
    """The psalm prints a small rail label ("The Psalm") and a large heading
    ("Psalm 34 (Benedicam Dominum)"). A pastor asking to change the heading means
    the large line, and the production must be able to change it."""

    def test_heading_replaces_only_the_large_line(self) -> None:
        psalm = {"number": "34", "latin_title": "Benedicam Dominum", "text": "1 Line, * **response.**"}
        before = psalm_block(psalm)
        self.assertIn('<span class="sh-label">The Psalm</span>', before)
        self.assertIn("Psalm 34", before)
        after = psalm_block({**psalm, "heading": "The Psalm"})
        self.assertIn('<p class="citation">The Psalm</p>', after)
        self.assertNotIn("Psalm 34", after)
        self.assertNotIn("Benedicam", after)
        self.assertIn("<strong>response.</strong>", after)
        escaped = psalm_block({**psalm, "heading": "<b>Ours</b>"})
        self.assertIn("&lt;b&gt;Ours&lt;/b&gt;", escaped)

    def test_revision_changes_the_printed_heading_and_nothing_else(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            bulletin = bulletin_input()
            bulletin["template"] = "modern"
            bulletin["readings"]["psalm"].update(number="34", latin_title="Benedicam Dominum")
            first = produce(church, bulletin)
            self.assertEqual(first["status"], "ready_for_review", first)
            pages = _pages(first)
            index = _psalm_page(pages)
            page = pages[index].upper()
            self.assertIn("THE PSALM", page)
            self.assertIn("PSALM 34", page)
            self.assertIn("BENEDICAM DOMINUM", page)

            revised = revise(church, first["receipt_path"], {"readings": {"psalm": {"heading": "The Psalm"}}})
            self.assertEqual(revised["status"], "ready_for_review", revised)
            changed = _pages(revised)
            self.assertEqual(len(changed), len(pages))
            page = changed[index].upper()
            self.assertNotIn("PSALM 34", page)
            self.assertNotIn("BENEDICAM DOMINUM", page)
            self.assertGreaterEqual(page.count("THE PSALM"), 2)
            self.assertIn("THE LEADER READS THE FIRST HALF", page)
            for number, (old, new) in enumerate(zip(pages, changed)):
                if number != index:
                    self.assertEqual(old, new, f"page {number + 1} changed")


if __name__ == "__main__":
    unittest.main()
