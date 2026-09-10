import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from skills.bulletin.bulletin_production.interface import produce
from tests.helpers import bulletin_input, make_church
from tests.test_bulletin_music_slots import _painted_image_colors


def _flat(text):
    """Strip ALL whitespace and casefold, for matching a heading in PDF-
    extracted text against stray spaces some fonts insert mid-word (a
    known extraction artifact, not a rendering bug)."""
    return "".join(text.split()).casefold()


def _norm(text):
    """Collapse whitespace/newlines and casefold, so a PDF's own line-wrap
    or heading-case CSS (text-transform paints actual uppercase glyphs,
    which pdftotext then extracts verbatim) doesn't break a substring
    check that only cares about the words present."""
    return " ".join(text.split()).casefold()


def _set_leadership_with_overlap(church):
    """Give the synthetic church a standing directory whose members share
    names with people credited for serving this particular week, so a
    dedup-against-the-standing-roster bug would drop those weekly credits."""
    brand_path = church / "brand.json"
    brand = json.loads(brand_path.read_text(encoding="utf-8"))
    brand["leadership"] = {
        "print_in_bulletin": True,
        "placement": "body",
        "governing_body": {
            "label": "Vestry",
            "members": [
                {"name": "Synthetic Overlap A", "role": "Vestry"},
                {"name": "Synthetic Overlap B", "role": "Vestry"},
            ],
        },
    }
    brand_path.write_text(json.dumps(brand, indent=2) + "\n", encoding="utf-8")


class WeeklyServingCreditDedupTests(unittest.TestCase):
    """PDF text extraction inserts stray spaces inside some words in the
    classic theme's justified text (a known extraction artifact, not a
    rendering bug), so these check the rendered HTML source instead of
    PDF-extracted text; production is still driven through the real
    produce() interface and the PDF is confirmed to render successfully."""

    def test_weekly_credits_survive_despite_overlapping_standing_names(self):
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                _set_leadership_with_overlap(church)
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["service"]["serving"] = [
                    {"role": "Livestream Director", "name": "Synthetic Overlap A"},
                    {"role": "Altar Guild", "name": "Synthetic Overlap B"},
                    {"role": "Usher", "name": "Synthetic Weekly Only"},
                ]
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                self.assertTrue(next(folder.glob(f"*{template}.pdf")).is_file())
                html = _norm(next(folder.glob("*.html")).read_text(encoding="utf-8"))
                # Being on the standing directory (Vestry) must not erase a
                # person's credit for serving this specific week.
                self.assertIn(_norm("Livestream Director"), html)
                self.assertIn(_norm("Synthetic Overlap A"), html)
                self.assertIn(_norm("Altar Guild"), html)
                self.assertIn(_norm("Synthetic Overlap B"), html)
                self.assertIn(_norm("Usher"), html)
                self.assertIn(_norm("Synthetic Weekly Only"), html)

    def test_one_person_in_two_different_roles_keeps_both_credits(self):
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                bulletin = bulletin_input()
                bulletin["template"] = template
                # bulletin_input's default already names the same person as
                # both celebrant and preacher.
                self.assertEqual(bulletin["service"]["celebrant"], bulletin["service"]["preacher"])
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                self.assertTrue(next(folder.glob(f"*{template}.pdf")).is_file())
                html = _norm(next(folder.glob("*.html")).read_text(encoding="utf-8"))
                self.assertIn(_norm("Celebrant"), html)
                self.assertIn(_norm("Preacher"), html)
                name = _norm(bulletin["service"]["celebrant"])
                self.assertGreaterEqual(html.count(name), 2)

    def test_exact_duplicate_role_and_name_still_collapses(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["service"]["serving"] = [
                {"role": "Reader", "name": "Synthetic Same Person"},
                {"role": "Reader", "name": "Synthetic Same Person"},
            ]
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review", result)
            folder = Path(result["week_folder"])
            self.assertTrue(next(folder.glob("*classic.pdf")).is_file())
            html = next(folder.glob("*.html")).read_text(encoding="utf-8")
            self.assertEqual(html.count("Synthetic Same Person"), 1)


class AnnouncementPosterLayoutTests(unittest.TestCase):
    def test_tall_poster_heading_paints_on_same_page_in_supplied_order(self):
        colors = [(220, 20, 60), (34, 139, 34)]
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                music_dir = church / "music"
                music_dir.mkdir(exist_ok=True)
                for i, color in enumerate(colors):
                    # Tall enough that two of them cannot share one page.
                    Image.new("RGB", (900, 2600), color).save(music_dir / f"poster{i}.png")
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["announcements"] = [
                    {"title": "Synthetic Poster Event",
                     "images": [f"music/poster{i}.png" for i in range(len(colors))]},
                ]
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])
                pdf = next(folder.glob(f"*{template}.pdf"))
                reader = PdfReader(str(pdf))
                heading_index = next(
                    index for index, page in enumerate(reader.pages)
                    if _flat("Synthetic Poster Event") in _flat(page.extract_text() or "")
                )
                pages_painting = {
                    index: _painted_image_colors(page)
                    for index, page in enumerate(reader.pages)
                }
                # The heading's own page paints the first supplied poster,
                # not a near-blank page with the second poster following.
                self.assertEqual(pages_painting[heading_index], [colors[0]])
                later_pages = [
                    index for index in sorted(pages_painting)
                    if index > heading_index and pages_painting[index]
                ]
                self.assertEqual(len(later_pages), len(colors) - 1)
                for offset, page_index in enumerate(later_pages, start=1):
                    self.assertEqual(pages_painting[page_index], [colors[offset]])

    def test_short_text_and_qr_stay_compact_in_supplied_order(self):
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                music_dir = church / "music"
                music_dir.mkdir(exist_ok=True)
                Image.new("RGB", (200, 200), (30, 60, 200)).save(music_dir / "qr.png")
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["announcements"] = [
                    {"title": "Scan To Give", "text": "Scan the code below.",
                     "images": ["music/qr.png"], "caption": "qr.example/give"},
                ]
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])

                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                title_pos = html.index("Scan To Give")
                text_pos = html.index("Scan the code below.")
                image_pos = html.index("qr.png")
                caption_pos = html.index("qr.example/give")
                # User-supplied order (title, text, image, caption) is
                # never rearranged to solve the layout problem.
                self.assertLess(title_pos, text_pos)
                self.assertLess(text_pos, image_pos)
                self.assertLess(image_pos, caption_pos)

                pdf = next(folder.glob(f"*{template}.pdf"))
                reader = PdfReader(str(pdf))
                heading_index = next(
                    index for index, page in enumerate(reader.pages)
                    if _flat("Scan To Give") in _flat(page.extract_text() or "")
                )
                painted = _painted_image_colors(reader.pages[heading_index])
                # A small graphic shares the heading's page; no big blank
                # page is inserted ahead of it, and it is not stretched
                # into a poster (still the same tiny painted color patch,
                # not repeated or split across pages).
                self.assertEqual(painted, [(30, 60, 200)])
                other_painted = [
                    index for index, page in enumerate(reader.pages)
                    if index != heading_index and _painted_image_colors(page)
                ]
                self.assertEqual(other_painted, [])

    def test_long_text_with_artwork_preserves_order_and_does_not_drop_content(self):
        for template in ("classic", "modern"):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as tmp:
                church = make_church(Path(tmp))
                music_dir = church / "music"
                music_dir.mkdir(exist_ok=True)
                Image.new("RGB", (900, 2600), (128, 0, 128)).save(music_dir / "flyer.png")
                long_text = " ".join(f"Synthetic filler sentence number {i}." for i in range(80))
                bulletin = bulletin_input()
                bulletin["template"] = template
                bulletin["announcements"] = [
                    {"title": "Synthetic Long Announcement",
                     "text": f"Opening marker. {long_text} Closing marker.",
                     "images": ["music/flyer.png"]},
                ]
                result = produce(church, bulletin)
                self.assertEqual(result["status"], "ready_for_review", result)
                folder = Path(result["week_folder"])

                html = next(folder.glob("*.html")).read_text(encoding="utf-8")
                title_pos = html.index("Synthetic Long Announcement")
                text_pos = html.index("Opening marker.")
                image_pos = html.index("flyer.png")
                # The long description is never moved after the artwork to
                # solve the stranded-heading problem.
                self.assertLess(title_pos, text_pos)
                self.assertLess(text_pos, image_pos)

                pdf = next(folder.glob(f"*{template}.pdf"))
                reader = PdfReader(str(pdf))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                self.assertIn("Opening marker.", text)
                self.assertIn("Closing marker.", text)
                painted_anywhere = [
                    index for index, page in enumerate(reader.pages)
                    if _painted_image_colors(page)
                ]
                # The artwork reaches the PDF exactly once, not dropped and
                # not duplicated by the overflow-avoidance path.
                self.assertEqual(len(painted_anywhere), 1)


if __name__ == "__main__":
    unittest.main()
