"""Synthetic regression tests for the booklet print gate.

Every bulletin here is synthetic: generic wording, gray boxes and generated
images standing in for music. No church data belongs in this file.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER = REPO_ROOT / "skills" / "bulletin" / "renderer"
if str(RENDERER) not in sys.path:
    sys.path.insert(0, str(RENDERER))

try:
    import weasyprint  # noqa: F401
    from PIL import Image
    HAVE_RUNTIME = True
except ImportError:  # pragma: no cover - the managed runtime has both
    HAVE_RUNTIME = False

import print_layout as pl  # noqa: E402

DASHES = (chr(0x2014), chr(0x2013))  # em dash and en dash

# US Letter with the bulletin margins: the content area is 936px tall.
BASE_CSS = """
@page { size: letter; margin: 0.55in 0.6in 0.7in 0.6in;
        @bottom-center { content: counter(page); } }
body { font-family: serif; font-size: 12pt; line-height: 1.4; margin: 0; }
p { margin: 0; }
h2 { margin: 0; }
.cover { height: 9.2in; }
.backpage { break-before: page; }
.ink { background: #888; }
.hymn-page, .hymn-inline { margin: 0; }
.hymn-head { font-size: 12pt; line-height: 20px; height: 20px; margin: 0 0 10px 0; }
.hymn-img { display: block; margin: 0; }
.section-head { font-size: 12pt; line-height: 20px; height: 20px; margin: 0 0 10px 0; }
.inside-cover { page: inside-cover; break-before: page; break-after: page; height: 1pt; }
@page inside-cover { @bottom-center { content: none; } }
"""

COVER = '<div class="cover"><p>Synthetic Parish</p><p>Morning Prayer</p></div>'
BACK = ('<div class="backpage"><p>Closing words for the back page.</p>'
        '<div class="ink" style="height:120px"></div></div>')


def page(body: str, css: str = "") -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{BASE_CSS}{css}</style></head><body>{body}</body></html>")


def block(height: int, label: str | None = None, extra: str = "") -> str:
    head = (f'<h2 class="section-head"><span class="sh-label">{label}</span></h2>'
            if label else "")
    return (f'<div class="section" style="break-inside: avoid{extra}">{head}'
            f'<div class="ink" style="height:{height}px"></div></div>')


def hymn(label: str, staves: int, stave_px: int, cls: str = "hymn-page", attrs: str = "") -> str:
    imgs = "".join(
        f'<img class="hymn-img" src="stave.png" alt="" style="width:6.33in; height:{stave_px}px;">'
        for _ in range(staves))
    return (f'<div class="{cls}"{attrs}><h2 class="hymn-head"><span class="sh-label">'
            f'{label}</span></h2>{imgs}</div>')


def unit(kind, first, last, role=None, uid=None):
    return pl.Unit(kind=kind, role=role, id=uid, first_page=first, last_page=last)


def report(pages, units=(), fill=None, blank=None):
    fill = list(fill) if fill is not None else [0.9] * pages
    blank = list(blank) if blank is not None else [False] * pages
    return pl.LayoutReport(pages=pages, fill=fill, blank=blank, units=list(units),
                           text="Synthetic words.")


def by_check(findings):
    return {f.check: f for f in findings}


def one_sentence(text: str) -> bool:
    body = text.strip()
    return body.endswith(".") and ". " not in body[:-1] and not any(d in body for d in DASHES)


class CheckRuleTests(unittest.TestCase):
    """Rules evaluated on hand-built layout reports (no rendering)."""

    def test_one_finding_per_check_and_names_are_stable(self):
        findings = pl.check(report(16, [unit("back-cover", 16, 16)]))
        names = [f.check for f in findings]
        self.assertEqual(names, ["booklet_page_count", "blank_pages_deliberate",
                                 "back_cover_last", "music_page_turn",
                                 "opening_music_whole", "prayer_page_turn", "page_fill",
                                 "assets_resolved"])
        self.assertTrue(set(names) <= set(pl.CHECK_NAMES))
        self.assertTrue(all(f.passed for f in findings))

    def test_fourteen_pages_fail_booklet_page_count(self):
        result = by_check(pl.check(report(14)))["booklet_page_count"]
        self.assertFalse(result.passed)
        self.assertTrue(result.blocking)
        self.assertIn("14 pages", result.message)
        self.assertTrue(one_sentence(result.message))

    def test_duplex_and_single_skip_booklet_only_checks(self):
        for mode in ("duplex", "single"):
            names = {f.check for f in pl.check(report(14), print_mode=mode)}
            self.assertNotIn("booklet_page_count", names)
            self.assertNotIn("blank_pages_deliberate", names)
            self.assertIn("music_page_turn", names)

    def test_unknown_print_mode_is_refused(self):
        with self.assertRaises(ValueError):
            pl.check(report(16), print_mode="folded")

    def test_padding_blank_before_back_cover_fails(self):
        blank = [False] * 16
        blank[13] = blank[14] = True
        fill = [0.9] * 16
        fill[13] = fill[14] = 0.0
        findings = by_check(pl.check(report(16, [unit("back-cover", 16, 16)], fill, blank)))
        self.assertFalse(findings["blank_pages_deliberate"].passed)
        self.assertEqual(findings["blank_pages_deliberate"].pages, [14, 15])
        self.assertIn("Pages 14 and 15 are blank", findings["blank_pages_deliberate"].message)

    def test_inside_cover_blank_is_deliberate_only_when_allowed(self):
        blank = [False] * 16
        blank[1] = True
        fill = [0.9] * 16
        fill[1] = 0.0
        units = [unit("inside-cover", 2, 2), unit("back-cover", 16, 16)]
        allowed = by_check(pl.check(report(16, units, fill, blank)))
        self.assertTrue(allowed["blank_pages_deliberate"].passed)
        refused = by_check(pl.check(report(16, units, fill, blank), inside_cover_allowed=False))
        self.assertFalse(refused["blank_pages_deliberate"].passed)
        self.assertEqual(refused["blank_pages_deliberate"].pages, [2])

    def test_back_cover_not_last_fails(self):
        findings = by_check(pl.check(report(16, [unit("back-cover", 14, 14)]),
                                     print_mode="duplex"))
        self.assertFalse(findings["back_cover_last"].passed)
        self.assertTrue(findings["back_cover_last"].blocking)
        self.assertIn("page 14", findings["back_cover_last"].message)
        self.assertTrue(one_sentence(findings["back_cover_last"].message))

    def test_music_across_facing_pages_passes_and_across_a_turn_fails(self):
        facing = by_check(pl.check(report(16, [unit("music", 6, 7, uid="Gradual Hymn")])))
        self.assertTrue(facing["music_page_turn"].passed)
        turn = by_check(pl.check(report(16, [unit("music", 5, 6, uid="Gradual Hymn")])))
        self.assertFalse(turn["music_page_turn"].passed)
        self.assertEqual(turn["music_page_turn"].message,
                         "The Gradual Hymn continues from page 5 onto page 6, "
                         "across a page turn.")
        self.assertEqual(turn["music_page_turn"].pages, [5, 6])
        # Longer than two pages: a turn is unavoidable, so it must start on a
        # left-hand page and show a full spread first.
        three = by_check(pl.check(report(16, [unit("music", 6, 8, uid="Long Anthem")])))
        self.assertTrue(three["music_page_turn"].passed)
        odd = by_check(pl.check(report(16, [unit("music", 5, 7, uid="Long Anthem")])))
        self.assertFalse(odd["music_page_turn"].passed)
        self.assertIn("starts on a right-hand page", odd["music_page_turn"].message)
        self.assertTrue(one_sentence(odd["music_page_turn"].message))

    def test_back_matter_may_run_long_only_when_unfolded(self):
        long_back = report(16, [unit("back-cover", 15, 16)])
        booklet = by_check(pl.check(long_back))["back_cover_last"]
        self.assertFalse(booklet.passed)
        self.assertIn("back cover", booklet.message)
        for mode in ("duplex", "single"):
            self.assertTrue(by_check(pl.check(long_back, print_mode=mode))["back_cover_last"].passed)

    def test_opening_music_must_be_whole(self):
        split = unit("music", 3, 4, role="opening", uid="Entrance Hymn · Hymn 1")
        findings = by_check(pl.check(report(16, [split])))
        whole = findings["opening_music_whole"]
        self.assertFalse(whole.passed)
        self.assertEqual(whole.message, "The Entrance Hymn is split across pages 3 and 4, "
                                        "but it must print whole on one page.")
        # Facing pages are fine for other music but not for the opening hymn.
        facing = unit("music", 2, 3, role="opening", uid="Entrance Hymn")
        findings = by_check(pl.check(report(16, [facing])))
        self.assertTrue(findings["music_page_turn"].passed)
        self.assertFalse(findings["opening_music_whole"].passed)

    def test_prayer_across_a_turn_fails_and_across_facing_pages_passes(self):
        facing = by_check(pl.check(report(16, [unit("prayer", 10, 11, uid="prayer in Confession")])))
        self.assertTrue(facing["prayer_page_turn"].passed)
        turn = by_check(pl.check(report(16, [unit("prayer", 11, 12, uid="prayer in Confession")])))
        self.assertFalse(turn["prayer_page_turn"].passed)
        self.assertIn("from page 11 onto page 12", turn["prayer_page_turn"].message)
        self.assertTrue(one_sentence(turn["prayer_page_turn"].message))

    def test_page_fill_blocks_under_40_and_warns_under_60_with_exemptions(self):
        fill = [0.1, 0.0, 0.9, 0.3, 0.9, 0.5, 0.9, 0.1]
        blank = [False, True, False, False, False, False, False, False]
        units = [unit("inside-cover", 2, 2), unit("back-cover", 8, 8)]
        findings = by_check(pl.check(report(8, units, fill, blank)))
        result = findings["page_fill"]
        self.assertFalse(result.passed)
        self.assertTrue(result.blocking)
        self.assertEqual(result.pages, [4, 6])
        self.assertNotIn(1, result.pages)
        self.assertNotIn(2, result.pages)
        self.assertNotIn(8, result.pages)

        fill[3] = 0.9
        warning = by_check(pl.check(report(8, units, fill, blank)))["page_fill"]
        self.assertFalse(warning.passed)
        self.assertFalse(warning.blocking)
        self.assertEqual(warning.pages, [6])

        fill[5] = 0.7
        self.assertTrue(by_check(pl.check(report(8, units, fill, blank)))["page_fill"].passed)

    def test_wording_unchanged_ignores_line_breaks_but_catches_changes(self):
        self.assertTrue(pl._wording_finding("Lord, have mercy.", "Lord,\n have  mercy.").passed)
        changed = pl._wording_finding("Lord, have mercy.", "Lord, have mercy upon us.")
        self.assertFalse(changed.passed)
        self.assertTrue(changed.blocking)

    def test_describe_adjustments_is_one_plain_sentence(self):
        common = {"pages": 16, "pages_before": 14, "print_mode": "booklet"}
        adjustments = [
            {"step": "inside_cover", "detail": {"page": 2, **common},
             "summary": "page 2 is left blank"},
            {"step": "line_height", "detail": {"from": 1.45, "to": 1.5, **common},
             "summary": "line spacing is a little looser"},
            {"step": "music_scale", "detail": {"id": "Entrance Hymn", "scale": 0.96, "page": 3,
                                               **common},
             "summary": "the Entrance Hymn prints at 96% so it fits on page 3"},
        ]
        sentence = pl.describe_adjustments(adjustments)
        self.assertEqual(sentence, "To fold into 16 pages, page 2 is left blank, line spacing "
                                   "is a little looser, and the Entrance Hymn prints at 96% so "
                                   "it fits on page 3.")
        self.assertTrue(one_sentence(sentence))
        self.assertEqual(pl.describe_adjustments([]), "No layout adjustments were needed.")


@unittest.skipUnless(HAVE_RUNTIME, "needs the managed WeasyPrint runtime")
class RenderedTests(unittest.TestCase):
    """Rendered synthetic bulletins. Renders are shared across tests."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        Image.new("RGB", (600, 200), (40, 40, 40)).save(cls.dir / "stave.png")
        cls.base_url = str(cls.dir) + "/"
        cls._cache = {}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def measure(self, html):
        if html not in self._cache:
            self._cache[html] = pl.measure(html, base_url=self.base_url)
        return self._cache[html]

    # -- fixtures ------------------------------------------------------------

    @staticmethod
    def fourteen_page_service() -> str:
        lines = "".join(f"<p>Service line {i} for the synthetic test.</p>"
                        for i in range(1, 481))
        body = (COVER + '<div class="section"><h2 class="section-head"><span class="sh-label">'
                'The Service</span></h2>' + lines + "</div>" + BACK)
        return page(body)

    @staticmethod
    def tall_opening_hymn() -> str:
        # Four staves of 232px plus a 30px heading: 958px against a 936px page,
        # so the last stave lands on page 4. At 97% it fits on page 3.
        blocks = "".join(block(380, f"Part {i}") for i in range(1, 24))
        body = (COVER + '<div class="inside-cover"></div>'
                + hymn("Entrance Hymn · Hymn 1", 4, 232) + blocks + BACK)
        return page(body)

    # -- measuring -----------------------------------------------------------

    def test_measure_finds_class_name_units_and_page_spans(self):
        body = (COVER + '<div class="inside-cover"></div>'
                + hymn("Entrance Hymn · Hymn 1", 1, 200)
                + block(200, "The Greeting")
                + '<div class="section"><h2 class="section-head"><span class="sh-label">'
                  'The Confession</span></h2><div class="dialogue"><p>Most merciful God,</p>'
                  '<p>we confess that we have sinned.</p></div></div>'
                + hymn("Sequence Hymn", 1, 200, cls="hymn-inline") + BACK)
        result = self.measure(page(body))
        kinds = [(u.kind, u.role, u.id, u.first_page, u.last_page) for u in result.units]
        self.assertIn(("inside-cover", None, "inside cover", 2, 2), kinds)
        self.assertIn(("music", "opening", "Entrance Hymn · Hymn 1", 3, 3), kinds)
        self.assertIn(("music", None, "Sequence Hymn", 3, 3), kinds)
        self.assertIn(("section", None, "The Greeting", 3, 3), kinds)
        self.assertIn(("prayer", None, "prayer in The Confession", 3, 3), kinds)
        self.assertIn(("back-cover", None, "back page", 4, 4), kinds)
        self.assertEqual(result.pages, 4)
        self.assertEqual(result.blank, [False, True, False, False])
        self.assertIn("Most merciful God", result.text)
        # Page numbers live in margin boxes and stay out of the text.
        self.assertNotRegex(result.text, r"\b[34]\b")

    def test_data_attributes_override_class_names(self):
        body = (COVER
                + hymn("Ignored Hymn", 1, 200)
                + '<div data-print-unit="music" data-print-id="Gathering Song">'
                  '<div class="ink" style="height:200px"></div></div>'
                + '<div data-print-unit="music" data-print-role="opening" '
                  'data-print-id="Processional"><div class="ink" style="height:200px"></div></div>'
                + '<div class="dialogue" data-print-unit="section" data-print-id="Prayers">'
                  '<p>Words said together.</p></div>'
                + '<div class="backpage" data-print-unit="back-cover"><p>End.</p></div>')
        result = self.measure(page(body))
        units = [(u.kind, u.role, u.id) for u in result.units]
        self.assertEqual(units, [("music", None, "Gathering Song"),
                                 ("music", "opening", "Processional"),
                                 ("section", None, "Prayers"),
                                 ("back-cover", None, "back page")])

    def test_rendered_music_and_prayer_turns(self):
        # A 600px section, then two 232px staves: the second stave moves on.
        music = block(600) + hymn("Gradual Hymn", 2, 232)
        facing = self.measure(page(COVER + music + BACK))
        span = [(u.first_page, u.last_page) for u in facing.units if u.kind == "music"]
        self.assertEqual(span, [(2, 3)])
        self.assertTrue(by_check(pl.check(facing, print_mode="duplex"))["music_page_turn"].passed)

        turn = self.measure(page(COVER + '<div class="inside-cover"></div>' + music + BACK))
        span = [(u.first_page, u.last_page) for u in turn.units if u.kind == "music"]
        self.assertEqual(span, [(3, 4)])
        finding = by_check(pl.check(turn))["music_page_turn"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.message, "The Gradual Hymn continues from page 3 onto page 4, "
                                          "across a page turn.")

        lines = "".join(f"<p>Prayer line {i}.</p>" for i in range(1, 16))
        said = block(750) + f'<div class="dialogue">{lines}</div>'
        facing = self.measure(page(COVER + said + BACK))
        span = [(u.first_page, u.last_page) for u in facing.units if u.kind == "prayer"]
        self.assertEqual(span, [(2, 3)])
        self.assertTrue(by_check(pl.check(facing, print_mode="duplex"))["prayer_page_turn"].passed)

        turn = self.measure(page(COVER + '<div class="inside-cover"></div>' + said + BACK))
        span = [(u.first_page, u.last_page) for u in turn.units if u.kind == "prayer"]
        self.assertEqual(span, [(3, 4)])
        self.assertFalse(by_check(pl.check(turn))["prayer_page_turn"].passed)

    def test_measured_fill_and_exemptions(self):
        body = (COVER + '<div class="inside-cover"></div>'
                + '<div class="ink" style="height:281px"></div>'          # 30%
                + '<div class="ink" style="height:468px; break-before: page"></div>'  # 50%
                + '<div class="ink" style="height:900px; break-before: page"></div>'
                + '<div class="backpage"><div class="ink" style="height:60px"></div></div>')
        result = self.measure(page(body))
        self.assertEqual(result.pages, 6)
        self.assertAlmostEqual(result.fill[2], 0.30, delta=0.01)
        self.assertAlmostEqual(result.fill[3], 0.50, delta=0.01)
        self.assertTrue(result.blank[1])
        findings = by_check(pl.check(result, print_mode="duplex"))
        self.assertFalse(findings["page_fill"].passed)
        self.assertTrue(findings["page_fill"].blocking)
        self.assertEqual(findings["page_fill"].pages, [3, 4])

    def test_back_cover_not_last_when_a_page_follows_it(self):
        body = (COVER + block(600) + BACK
                + '<div style="break-before: page"><p>Stray notice.</p></div>')
        result = self.measure(page(body))
        findings = by_check(pl.check(result, print_mode="duplex"))
        self.assertFalse(findings["back_cover_last"].passed)

    # -- fitting -------------------------------------------------------------

    def test_fourteen_page_service_fits_sixteen_with_inside_cover(self):
        html = self.fourteen_page_service()
        before = self.measure(html)
        self.assertEqual(before.pages, 14)
        self.assertFalse(by_check(pl.check(before))["booklet_page_count"].passed)

        result = pl.fit(html, base_url=self.base_url)
        self.assertEqual(result.status, "fit")
        self.assertEqual(result.report.pages, 16)
        steps = [a["step"] for a in result.adjustments]
        self.assertEqual(steps[0], "inside_cover")
        findings = by_check(result.findings)
        self.assertTrue(findings["wording_unchanged"].passed)
        self.assertTrue(findings["blank_pages_deliberate"].passed)
        self.assertTrue(findings["back_cover_last"].passed)
        # The only blank page is the inside cover; no padding blanks.
        self.assertEqual([i + 1 for i, b in enumerate(result.report.blank) if b], [2])
        self.assertEqual(result.report.text, before.text)
        self.assertNotIn("data-pl-ref", result.html)
        self.assertIn('class="inside-cover"', result.html)
        summary = pl.describe_adjustments(result.adjustments)
        self.assertTrue(summary.startswith("To fold into 16 pages, page 2 is left blank"))
        self.assertTrue(one_sentence(summary))
        self.assertLessEqual(result.renders, pl.DEFAULT_MAX_RENDERS)

    def test_tall_opening_hymn_is_scaled_to_fit_its_page(self):
        html = self.tall_opening_hymn()
        before = self.measure(html)
        findings = by_check(pl.check(before))
        self.assertEqual(before.pages, 16)
        self.assertFalse(findings["opening_music_whole"].passed)
        self.assertIn("pages 3 and 4", findings["opening_music_whole"].message)

        result = pl.fit(html, base_url=self.base_url)
        self.assertEqual(result.status, "fit")
        music = [a for a in result.adjustments if a["step"] == "music_scale"]
        self.assertEqual(len(music), 1)
        scale = music[0]["detail"]["scale"]
        self.assertGreaterEqual(scale, 0.95)
        self.assertLess(scale, 1.0)
        self.assertEqual(music[0]["detail"]["page"], 3)
        self.assertIn(f"prints at {round(scale * 100)}% so it fits on page 3",
                      music[0]["summary"])
        opening = [u for u in result.report.units if u.role == "opening"][0]
        self.assertEqual((opening.first_page, opening.last_page), (3, 3))
        self.assertTrue(by_check(result.findings)["wording_unchanged"].passed)
        self.assertEqual(result.report.pages, 16)
        self.assertIn("break-inside: avoid", result.html)
        self.assertNotIn("data-print-fit", html)

    def test_short_page_is_rebalanced_by_starting_a_section_on_a_new_page(self):
        css = "body { font-size: 13pt; line-height: 1.5; }"
        body = (COVER + block(500, "The Gathering") + block(300, "The Peace")
                + block(200, "Announcements") + block(700, "Offertory Anthem") + BACK)
        html = page(body, css)
        before = by_check(pl.check(self.measure(html), print_mode="duplex"))
        self.assertFalse(before["page_fill"].passed)
        self.assertTrue(before["page_fill"].blocking)

        result = pl.fit(html, base_url=self.base_url, print_mode="duplex")
        self.assertEqual(result.status, "fit")
        moved = [a for a in result.adjustments if a["step"] == "section_start"]
        self.assertEqual([a["detail"]["id"] for a in moved], ["The Peace"])
        self.assertIn("The Peace starts a new page", pl.describe_adjustments(result.adjustments))

        pinned = pl.fit(html, base_url=self.base_url, print_mode="duplex",
                        pinned_section_ids=("The Peace",))
        self.assertEqual(pinned.status, "failed")
        self.assertFalse([a for a in pinned.adjustments if a["step"] == "section_start"])

        # A host that names its modules (data-hb-module) pins by module id.
        wrapped = html.replace(block(300, "The Peace"),
                               '<div class="hb-module" data-hb-module="peace">' + block(300, "The Peace") + '</div>')
        self.assertNotEqual(wrapped, html)
        by_module = pl.fit(wrapped, base_url=self.base_url, print_mode="duplex",
                           pinned_section_ids=("peace",))
        self.assertFalse([a for a in by_module.adjustments if a["step"] == "section_start"
                          and a["detail"]["id"] == "The Peace"])

    def test_unitless_line_height_is_read_in_either_weasyprint_form(self):
        # WeasyPrint 70 gives a number; WeasyPrint 68 gives ("NUMBER", 1.5).
        self.assertEqual(pl._ratio_line_height({"line_height": 1.5, "font_size": 16}), 1.5)
        self.assertEqual(pl._ratio_line_height({"line_height": ("NUMBER", 1.5), "font_size": 16}), 1.5)

    def test_unfixable_bulletin_fails_with_a_plain_sentence(self):
        # Already at the largest type and line spacing, in duplex mode, with an
        # opening hymn far taller than a page: nothing in the ladder can fix it.
        css = "body { font-size: 13pt; line-height: 1.5; }"
        html = page(COVER + hymn("Entrance Hymn", 6, 232) + block(300, "Dismissal") + BACK, css)
        result = pl.fit(html, base_url=self.base_url, print_mode="duplex")
        self.assertEqual(result.status, "failed")
        failing = [f for f in result.findings if not f.passed and f.blocking]
        self.assertIn("opening_music_whole", [f.check for f in failing])
        for finding in failing:
            self.assertTrue(one_sentence(finding.message), finding.message)
        self.assertTrue(result.html)
        self.assertLessEqual(result.renders, 5)

    def test_passing_bulletin_is_unchanged(self):
        sections = "".join(block(800, name) for name in
                           ("Opening", "Word", "Prayers", "Table", "Sending"))
        html = page(COVER + '<div class="inside-cover"></div>' + sections + BACK)
        result = pl.fit(html, base_url=self.base_url)
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(result.html, html)
        self.assertEqual(result.adjustments, [])
        self.assertEqual(result.renders, 1)

    def test_a_missing_font_or_picture_blocks(self):
        # A retired plugin folder once left a real bulletin's fonts unfound;
        # WeasyPrint silently printed it in substitute fonts.
        html = page(COVER + block(800, "Opening") + BACK,
                    css='@font-face { font-family: Gone; src: url("file:///nowhere/retired/Gone-Regular.ttf"); }')
        html = html.replace("</body>", '<img src="missing-staff.png"></body>')
        found = pl.missing_assets(html, str(self.dir))
        self.assertEqual(sorted(Path(p).name for p in found), ["Gone-Regular.ttf", "missing-staff.png"])
        finding = next(f for f in pl.check(pl.measure(html, base_url=str(self.dir)))
                       if f.check == "assets_resolved")
        self.assertFalse(finding.passed)
        self.assertTrue(finding.blocking)
        self.assertIn("Gone-Regular.ttf", finding.message)
        self.assertFalse(any(d in finding.message for d in DASHES))

    def test_cli_check_reports_json_and_exit_code(self):
        path = self.dir / "fourteen.html"
        path.write_text(self.fourteen_page_service(), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pl.main(["check", str(path)])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(data["pages"], 14)
        self.assertEqual(len(data["fill"]), 14)
        self.assertIn("booklet_page_count",
                      [f["check"] for f in data["findings"] if not f["passed"]])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pl.main(["check", str(path), "--print-mode", "duplex"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
