"""Booklet print gate: measure, check, and fit a rendered bulletin.

The gate reads the rendered layout, not the PDF text. It renders bulletin
HTML with WeasyPrint, records which pages each print unit occupies (music,
prayers, the inside cover, the back page, named sections), and checks the
rules a folded booklet needs: a page count that is a multiple of 4, no stray
blank pages, the back page last, and no music or prayer continuing across a
page turn.

When a bulletin fails, ``fit`` tries small, bounded layout adjustments
(a blank inside cover, looser line spacing, larger body type, music at 95%
to 100%, one section starting a new page). It never changes wording or
order, never shrinks body type, and never scales music below 95%.

This module is self-contained on purpose: it depends only on WeasyPrint and
the standard library, so the same file can run in the plugin, a web render
service, or a church folder.

Command line:

    python print_layout.py check <file.html> [--print-mode booklet] [--no-inside-cover]
    python print_layout.py fit <in.html> <out.html> [--print-mode booklet] [--no-inside-cover]
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PRINT_MODES = ("booklet", "duplex", "single")

UNIT_KINDS = ("music", "prayer", "inside-cover", "back-cover", "section")

CHECK_NAMES = (
    "booklet_page_count",
    "blank_pages_deliberate",
    "back_cover_last",
    "music_page_turn",
    "opening_music_whole",
    "prayer_page_turn",
    "page_fill",
    "wording_unchanged",
    "assets_resolved",
)

FILL_BLOCK = 0.40
FILL_WARN = 0.60
MAX_LINE_HEIGHT = 1.5
LINE_HEIGHT_STEP = 0.05
MAX_BODY_PT = 13.0
BODY_PT_STEP = 0.25
MUSIC_SCALES = (1.00, 0.99, 0.98, 0.97, 0.96, 0.95)
DEFAULT_MAX_RENDERS = 40

# Relative cost of each fitting step, used to try the smallest change first.
COST_INSIDE_COVER = 1.0
COST_LINE_HEIGHT_STEP = 1.25
COST_TYPE_STEP = 2.5

PX_PER_PT = 96.0 / 72.0

_REF_ATTR = "data-pl-ref"
_REF_TAGS = ("div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "img",
             "section", "article", "table", "ul", "ol", "figure")
_COUNT_CHECKS = ("booklet_page_count", "blank_pages_deliberate", "back_cover_last")


# --------------------------------------------------------------------------
# Public data


@dataclass
class Unit:
    kind: str
    role: str | None
    id: str | None
    first_page: int
    last_page: int
    module: str | None = None  # enclosing data-hb-module id, when the host marks modules


@dataclass
class LayoutReport:
    pages: int
    fill: list[float]
    blank: list[bool]
    units: list[Unit]
    text: str
    missing_assets: list[str] = field(default_factory=list)


@dataclass
class Finding:
    check: str
    passed: bool
    blocking: bool
    message: str
    pages: list[int] = field(default_factory=list)


@dataclass
class FitResult:
    status: str
    html: str
    report: LayoutReport
    findings: list[Finding]
    adjustments: list[dict]
    renders: int = 0
    seconds: float = 0.0


# --------------------------------------------------------------------------
# Measuring


@dataclass
class _Layout:
    """One render: the public report plus what fitting needs to edit it."""

    report: LayoutReport
    unit_refs: list[str | None]
    img_refs: dict[str | None, list[str]]
    img_px: dict[str, tuple[float, float]]
    ref_first_page: dict[str, int]
    cover_ref: str | None
    base_font_pt: float
    base_line_height: float
    class_line_heights: dict[str, float]
    back_font_pt: float | None
    back_line_height: float | None
    has_inside_cover: bool
    marked: bool


def _classes(el) -> list[str]:
    return (el.get("class") or "").split()


def _clean(text: str) -> str:
    return " ".join(text.split())


def _element_text(el) -> str:
    return _clean("".join(el.itertext()))


def _first_descendant(el, cls: str):
    for d in el.iter():
        if d is not el and cls in _classes(d):
            return d
    return None


def _heading_label(el, head_classes: tuple[str, ...]) -> str | None:
    for cls in head_classes:
        head = _first_descendant(el, cls)
        if head is not None:
            label = _first_descendant(head, "sh-label")
            text = _element_text(label if label is not None else head)
            if text:
                return text
    return None


def _is_marked(root) -> bool:
    """True when the renderer marked print units with data attributes."""
    return any(el.get("data-print-unit") for el in root.iter())


def _find_units(root, parents: dict) -> list[tuple[object, str, str | None, str | None]]:
    """Return (element, kind, role, id) for every print unit in document order.

    A document with any data-print-unit attribute is read from data attributes
    only. Older documents without them are read from their class names.
    """
    marked = _is_marked(root)
    found = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if marked:
            kind = el.get("data-print-unit")
            if kind not in UNIT_KINDS:
                continue
        else:
            cls = _classes(el)
            kind = None
            if el.tag == "div":
                if "hymn-page" in cls or "hymn-inline" in cls:
                    kind = "music"
                elif "inside-cover" in cls:
                    kind = "inside-cover"
                elif "backpage" in cls:
                    kind = "back-cover"
                elif "dialogue" in cls:
                    kind = "prayer"
                elif "section" in cls:
                    kind = "section"
            if kind is None:
                continue
        found.append([el, kind, el.get("data-print-role") or None, el.get("data-print-id") or None])

    section_els = {id(item[0]): item for item in found if item[1] == "section"}

    def section_label(el) -> str | None:
        return _heading_label(el, ("section-head",))

    for item in found:
        el, kind = item[0], item[1]
        if item[3]:
            continue
        if kind == "music":
            item[3] = _heading_label(el, ("hymn-head", "subhead", "hymn-title"))
        elif kind == "section":
            item[3] = section_label(el)
        elif kind == "inside-cover":
            item[3] = "inside cover"
        elif kind == "back-cover":
            item[3] = "back page"
        elif kind == "prayer":
            node = parents.get(el)
            while node is not None:
                if id(node) in section_els or "section" in _classes(node):
                    label = section_els[id(node)][3] if id(node) in section_els else None
                    label = label or section_label(node)
                    if label:
                        item[3] = f"prayer in {label}"
                    break
                node = parents.get(node)

    music = [item for item in found if item[1] == "music"]
    if music and not any(item[2] == "opening" for item in music):
        music[0][2] = "opening"
    return [tuple(item) for item in found]


def _ratio_line_height(style) -> float:
    value = style["line_height"]
    if isinstance(value, (int, float)):
        return float(value)
    # WeasyPrint 68 reports a unitless line height as ("NUMBER", 1.5).
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "NUMBER":
        return float(value[1])
    unit = getattr(value, "unit", None)
    number = getattr(value, "value", None)
    if number is not None:
        if unit in ("px", None):
            return float(number) / float(style["font_size"])
        if unit == "pt":
            return float(number) * PX_PER_PT / float(style["font_size"])
        if unit == "em":
            return float(number)
    return 1.2


def _has_ink(box, boxes_module) -> bool:
    """True when a box puts something on paper: text, an image, or a painted shape."""
    if isinstance(box, boxes_module.TextBox):
        return bool(box.text.strip())
    if isinstance(box, boxes_module.ReplacedBox):
        return True
    # Only empty leaf boxes count as painted shapes (rules, filled boxes), so a
    # page-wide wrapper with a background or border never counts as content.
    if getattr(box, "children", None) or isinstance(box, boxes_module.LineBox):
        return False
    el = getattr(box, "element", None)
    if el is not None and el.tag in ("html", "body"):
        return False
    try:
        if any(getattr(box, f"border_{side}_width", 0) > 0
               for side in ("top", "right", "bottom", "left")):
            return True
        filled = getattr(box.style["background_color"], "alpha", 0) > 0
        return filled and box.border_height() > 0 and box.border_width() > 0
    except (KeyError, AttributeError, TypeError):
        return False


def _iter_boxes(roots):
    stack = list(reversed(roots))
    while stack:
        box = stack.pop()
        yield box
        children = getattr(box, "children", None)
        if children:
            stack.extend(reversed(children))


def _layout(html: str, base_url: str | None) -> _Layout:
    from weasyprint import HTML
    from weasyprint.formatting_structure import boxes as wboxes

    document_source = HTML(string=html, base_url=base_url)
    document = document_source.render()
    root = document_source.etree_element
    parents = {}
    for parent in root.iter():
        for child in parent:
            parents[child] = parent

    unit_items = _find_units(root, parents)
    unit_index = {id(item[0]): i for i, item in enumerate(unit_items)}
    ancestor_cache: dict[int, tuple[int, ...]] = {}

    def unit_ancestors(el) -> tuple[int, ...]:
        key = id(el)
        if key in ancestor_cache:
            return ancestor_cache[key]
        chain = []
        node = el
        while node is not None:
            idx = unit_index.get(id(node))
            if idx is not None:
                chain.append(idx)
            node = parents.get(node)
        result = tuple(chain)
        ancestor_cache[key] = result
        return result

    img_refs: dict[str | None, list[str]] = {}
    music_img_ids = set()
    for item in unit_items:
        if item[1] == "music":
            refs = []
            for img in item[0].iter("img"):
                if img.get(_REF_ATTR):
                    refs.append(img.get(_REF_ATTR))
                    music_img_ids.add(id(img))
            img_refs[item[0].get(_REF_ATTR)] = refs

    ink_pages = [set() for _ in unit_items]
    any_pages = [set() for _ in unit_items]
    fill: list[float] = []
    blank: list[bool] = []
    texts: list[str] = []
    img_px: dict[str, tuple[float, float]] = {}
    ref_first_page: dict[str, int] = {}
    body_style = None
    class_line_heights: dict[str, float] = {}
    back_font_pt = None
    back_line_height = None
    wanted_classes = ("dialogue", "dlg-line", "lyrics-group", "reading-text")

    for number, page in enumerate(document.pages, start=1):
        page_box = page._page_box
        roots = [c for c in page_box.children if not isinstance(c, wboxes.MarginBox)]
        top = page_box.content_box_y()
        height = page_box.height or 1
        lowest = None
        for box in _iter_boxes(roots):
            el = getattr(box, "element", None)
            ink = _has_ink(box, wboxes)
            if isinstance(box, wboxes.TextBox) and box.text.strip():
                texts.append(box.text)
            if ink:
                bottom = box.position_y + (box.margin_top or 0) + box.border_height()
                lowest = bottom if lowest is None else max(lowest, bottom)
            if el is None:
                continue
            for idx in unit_ancestors(el):
                any_pages[idx].add(number)
                if ink:
                    ink_pages[idx].add(number)
            ref = el.get(_REF_ATTR)
            if ref and ref not in ref_first_page:
                ref_first_page[ref] = number
            if ref and id(el) in music_img_ids and isinstance(box, wboxes.ReplacedBox):
                img_px.setdefault(ref, (box.width, box.height))
            if body_style is None and el.tag == "body":
                body_style = box.style
            for cls in wanted_classes:
                if cls not in class_line_heights and cls in _classes(el):
                    class_line_heights[cls] = _ratio_line_height(box.style)
            if back_font_pt is None and ("backpage" in _classes(el)
                                         or el.get("data-print-unit") == "back-cover"):
                back_font_pt = float(box.style["font_size"]) / PX_PER_PT
                back_line_height = _ratio_line_height(box.style)
        if lowest is None:
            fill.append(0.0)
            blank.append(True)
        else:
            fill.append(round(max(0.0, min(1.0, (lowest - top) / height)), 4))
            blank.append(False)

    units = []
    unit_refs = []
    has_inside_cover = False
    for i, (el, kind, role, uid) in enumerate(unit_items):
        span = ink_pages[i] or any_pages[i]
        if not span:
            continue
        if kind == "inside-cover":
            has_inside_cover = True
        module = None
        node = el
        while node is not None:
            if isinstance(node.tag, str) and node.get("data-hb-module"):
                module = node.get("data-hb-module")
                break
            node = parents.get(node)
        units.append(Unit(kind=kind, role=role, id=uid,
                          first_page=min(span), last_page=max(span), module=module))
        unit_refs.append(el.get(_REF_ATTR))

    cover_ref = None
    for el in root.iter("div"):
        if "cover" in _classes(el):
            cover_ref = el.get(_REF_ATTR)
            break

    if body_style is not None:
        base_font_pt = float(body_style["font_size"]) / PX_PER_PT
        base_line_height = _ratio_line_height(body_style)
    else:
        base_font_pt, base_line_height = 12.0, 1.2

    report = LayoutReport(pages=len(document.pages), fill=fill, blank=blank,
                          units=units, text=_clean(" ".join(texts)),
                          missing_assets=missing_assets(html, base_url))
    return _Layout(report=report, unit_refs=unit_refs, img_refs=img_refs,
                   img_px=img_px, ref_first_page=ref_first_page,
                   cover_ref=cover_ref, base_font_pt=round(base_font_pt, 3),
                   base_line_height=round(base_line_height, 4),
                   class_line_heights=class_line_heights,
                   back_font_pt=back_font_pt, back_line_height=back_line_height,
                   has_inside_cover=has_inside_cover, marked=_is_marked(root))


_ASSET_URL = re.compile(r"""(?:\bsrc\s*=\s*["']|url\(\s*["']?)([^"')\s]+)""", re.I)


def missing_assets(html: str, base_url: str | None = None) -> list[str]:
    """Return local fonts and pictures the HTML names that do not exist.

    WeasyPrint does not fail on a missing font or picture: it substitutes a
    fallback font or leaves a hole, and the page count and look change. A
    bulletin rendered from an old package can point at a folder that no
    longer exists, so this is checked before trusting any layout.
    """
    from urllib.parse import unquote, urlparse

    base = Path(base_url[7:] if base_url and base_url.startswith("file://") else base_url or ".")
    missing: list[str] = []
    for raw in _ASSET_URL.findall(html):
        if raw.startswith(("data:", "http:", "https:", "#")):
            continue
        if raw.startswith("file://"):
            path = Path(unquote(urlparse(raw).path))
        else:
            path = base / unquote(raw)
        if not path.exists() and str(path) not in missing:
            missing.append(str(path))
    return missing


def measure(html: str, *, base_url: str | None = None) -> LayoutReport:
    """Render the HTML and report pages, fill, blank pages, units, and text."""
    return _layout(html, base_url).report


# --------------------------------------------------------------------------
# Checking


def _plural_pages(pages: list[int]) -> str:
    pages = sorted(pages)
    if len(pages) == 1:
        return f"Page {pages[0]}"
    if len(pages) == 2:
        return f"Pages {pages[0]} and {pages[1]}"
    return "Pages " + ", ".join(str(p) for p in pages[:-1]) + f", and {pages[-1]}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _short(label: str | None) -> str | None:
    if not label:
        return None
    # "Entrance Hymn · Hymn 423" reads as "Entrance Hymn" in a sentence.
    return label.split("·")[0].strip() or label


def _named(unit: Unit, fallback: str) -> str:
    """A name for use mid-sentence, such as 'the Entrance Hymn'."""
    label = _short(unit.id)
    if not label:
        return fallback
    if label.startswith(("The ", "the ")):
        return label
    return f"the {label}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _turn_ok(unit: Unit) -> bool:
    if unit.first_page == unit.last_page:
        return True
    return unit.last_page == unit.first_page + 1 and unit.first_page % 2 == 0


def _span_clause(name: str, unit: Unit) -> str:
    if unit.last_page == unit.first_page + 1:
        return f"{name} continues from page {unit.first_page} onto page {unit.last_page}"
    return f"{name} runs from page {unit.first_page} to page {unit.last_page}"


def _exempt_pages(report: LayoutReport) -> set[int]:
    exempt = {1}
    for unit in report.units:
        if unit.kind in ("inside-cover", "back-cover"):
            exempt.update(range(unit.first_page, unit.last_page + 1))
    return exempt


def _allowed_blank_pages(report: LayoutReport, inside_cover_allowed: bool) -> set[int]:
    if not inside_cover_allowed:
        return set()
    return {2 for unit in report.units
            if unit.kind == "inside-cover" and unit.first_page <= 2 <= unit.last_page}


def check(report: LayoutReport, *, print_mode: str = "booklet",
          inside_cover_allowed: bool = True) -> list[Finding]:
    """Evaluate every layout rule for this print mode, passing ones too."""
    if print_mode not in PRINT_MODES:
        raise ValueError(f"print_mode must be one of {', '.join(PRINT_MODES)}")
    findings: list[Finding] = []
    pages = report.pages
    blank_pages = [i + 1 for i, b in enumerate(report.blank) if b]
    stray_blanks: list[int] = []

    if print_mode == "booklet":
        if pages % 4 == 0:
            findings.append(Finding("booklet_page_count", True, True,
                                    f"The bulletin has {pages} pages, which folds into a booklet.",
                                    [pages]))
        else:
            lower, upper = pages - pages % 4, pages - pages % 4 + 4
            options = f"{lower} or {upper}" if lower else f"{upper}"
            findings.append(Finding(
                "booklet_page_count", False, True,
                f"The bulletin has {pages} pages, but a folded booklet needs a multiple of 4 "
                f"({options}).", [pages]))

        allowed = _allowed_blank_pages(report, inside_cover_allowed)
        stray_blanks = [p for p in blank_pages if p not in allowed]
        if stray_blanks:
            verb = "is" if len(stray_blanks) == 1 else "are"
            findings.append(Finding(
                "blank_pages_deliberate", False, True,
                f"{_plural_pages(stray_blanks)} {verb} blank, and the only blank page "
                "allowed is the inside front cover (page 2).", stray_blanks))
        else:
            message = ("The only blank page is the inside front cover (page 2)."
                       if blank_pages else "There are no blank pages.")
            findings.append(Finding("blank_pages_deliberate", True, True, message, blank_pages))

    backs = [u for u in report.units if u.kind == "back-cover"]
    if not backs:
        findings.append(Finding("back_cover_last", True, True,
                                "There is no designed back page to check.", []))
    else:
        back = backs[-1]
        if back.first_page == back.last_page == pages:
            findings.append(Finding("back_cover_last", True, True,
                                    f"The back page prints last, on page {pages}.", [pages]))
        elif back.last_page == pages:
            findings.append(Finding(
                "back_cover_last", False, True,
                f"The back page runs from page {back.first_page} onto page {back.last_page}, "
                "but it must fit on the last page.",
                list(range(back.first_page, back.last_page + 1))))
        else:
            findings.append(Finding(
                "back_cover_last", False, True,
                f"The back page prints on page {back.last_page}, but the bulletin ends on "
                f"page {pages}, so it would not be on the back.", [back.last_page, pages]))

    music = [u for u in report.units if u.kind == "music"]
    bad_music = [u for u in music if not _turn_ok(u)]
    if bad_music:
        clauses = [_span_clause(_named(u, "a piece of music"), u) for u in bad_music]
        ending = "across a page turn" if len(bad_music) == 1 else "across page turns"
        findings.append(Finding(
            "music_page_turn", False, True,
            _cap(_join(clauses)) + f", {ending}.",
            sorted({p for u in bad_music for p in (u.first_page, u.last_page)})))
    else:
        findings.append(Finding(
            "music_page_turn", True, True,
            "Every piece of music prints on one page or across facing pages."
            if music else "There is no music to check.", []))

    opening = next((u for u in music if u.role == "opening"), None)
    if opening is None:
        findings.append(Finding("opening_music_whole", True, True,
                                "There is no opening music to check.", []))
    elif opening.first_page == opening.last_page:
        findings.append(Finding(
            "opening_music_whole", True, True,
            f"{_cap(_named(opening, 'the opening music'))} prints whole on page "
            f"{opening.first_page}.", [opening.first_page]))
    else:
        span = (f"pages {opening.first_page} and {opening.last_page}"
                if opening.last_page == opening.first_page + 1
                else f"pages {opening.first_page} to {opening.last_page}")
        findings.append(Finding(
            "opening_music_whole", False, True,
            f"{_cap(_named(opening, 'the opening music'))} is split across {span}, "
            "but it must print whole on one page.",
            list(range(opening.first_page, opening.last_page + 1))))

    prayers = [u for u in report.units if u.kind == "prayer"]
    bad_prayers = []
    seen = set()
    for unit in prayers:
        if _turn_ok(unit):
            continue
        key = (unit.id, unit.first_page, unit.last_page)
        if key in seen:
            continue
        seen.add(key)
        bad_prayers.append(unit)
    if bad_prayers:
        clauses = [_span_clause(_named(u, "a prayer"), u) for u in bad_prayers]
        ending = "across a page turn" if len(bad_prayers) == 1 else "across page turns"
        findings.append(Finding(
            "prayer_page_turn", False, True, _cap(_join(clauses)) + f", {ending}.",
            sorted({p for u in bad_prayers for p in (u.first_page, u.last_page)})))
    else:
        findings.append(Finding(
            "prayer_page_turn", True, True,
            "No prayer continues across a page turn." if prayers
            else "There are no prayers to check.", []))

    exempt = _exempt_pages(report)
    low, thin = [], []
    for i, value in enumerate(report.fill):
        number = i + 1
        if number in exempt or number in stray_blanks:
            continue
        if report.blank[i] and print_mode == "booklet":
            continue
        if value < FILL_BLOCK:
            low.append(number)
        elif value < FILL_WARN:
            thin.append(number)

    def pct(number: int) -> str:
        return f"{round(report.fill[number - 1] * 100)}%"

    if low:
        verb = "is" if len(low) == 1 else "are"
        message = (f"{_plural_pages(low)} {verb} less than 40% full "
                   f"({_join([pct(p) for p in low])}), which leaves too much white space")
        if thin:
            message += f", and {_plural_pages(thin).lower()} {'is' if len(thin) == 1 else 'are'} under 60%"
        findings.append(Finding("page_fill", False, True, message + ".", low + thin))
    elif thin:
        verb = "is" if len(thin) == 1 else "are"
        findings.append(Finding(
            "page_fill", False, False,
            f"{_plural_pages(thin)} {verb} only {_join([pct(p) for p in thin])} full; "
            "this is allowed but leaves noticeable white space.", thin))
    else:
        findings.append(Finding("page_fill", True, True,
                                "Every content page is at least 60% full.", []))

    if report.missing_assets:
        names = sorted({Path(item).name for item in report.missing_assets})
        shown = ", ".join(names[:4]) + (f", and {len(names) - 4} more" if len(names) > 4 else "")
        findings.append(Finding(
            "assets_resolved", False, True,
            f"The bulletin names fonts or pictures that cannot be found ({shown}), "
            "so it would print with substitutes.", []))
    else:
        findings.append(Finding("assets_resolved", True, True,
                                "Every font and picture the bulletin names was found.", []))
    return findings


def _wording_finding(before: str, after: str) -> Finding:
    if re.sub(r"\s+", "", before) == re.sub(r"\s+", "", after):
        return Finding("wording_unchanged", True, True,
                       "The wording matches the original render.", [])
    return Finding("wording_unchanged", False, True,
                   "The wording changed during fitting, so the fitted version cannot be used.",
                   [])


def _blocking_failures(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if not f.passed and f.blocking]


# --------------------------------------------------------------------------
# Fitting


@dataclass(frozen=True)
class _Params:
    inside_cover: bool = False
    line_height: float | None = None
    font_pt: float | None = None
    music: tuple[tuple[str, float], ...] = ()
    sections: tuple[str, ...] = ()


def _annotate(html: str) -> str:
    """Give every block-level start tag in the body a stable reference."""
    body = re.search(r"<body\b", html, re.IGNORECASE)
    start = body.start() if body else 0
    counter = itertools.count(1)
    pattern = re.compile(r"<(" + "|".join(_REF_TAGS) + r")(?=[\s/>])", re.IGNORECASE)

    def repl(match: re.Match) -> str:
        return f'<{match.group(1)} {_REF_ATTR}="{next(counter)}"'

    head, rest = html[:start], html[start:]
    # Leave scripts, styles, and comments alone.
    pieces = re.split(r"(<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>)", rest,
                      flags=re.IGNORECASE | re.DOTALL)
    for i in range(0, len(pieces), 2):
        pieces[i] = pattern.sub(repl, pieces[i])
    return head + "".join(pieces)


def _strip_refs(html: str) -> str:
    return re.sub(r" " + _REF_ATTR + r'="\d+"', "", html)


def _tag_span(html: str, ref: str) -> tuple[int, int] | None:
    match = re.search(r"<\w+ " + _REF_ATTR + r'="' + re.escape(ref) + r'"[^>]*>', html)
    return (match.start(), match.end()) if match else None


def _add_style(tag: str, declaration: str) -> str:
    match = re.search(r'\sstyle\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
    if match:
        existing = match.group(1).strip().rstrip(";")
        joined = f"{existing}; {declaration}" if existing else declaration
        return tag[:match.start()] + f' style="{joined}"' + tag[match.end():]
    end = -2 if tag.endswith("/>") else -1
    return tag[:end] + f' style="{declaration}"' + tag[end:]


def _edit_tag(html: str, ref: str, edit) -> str:
    span = _tag_span(html, ref)
    if span is None:
        return html
    return html[:span[0]] + edit(html[span[0]:span[1]]) + html[span[1]:]


def _format_number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _scale_img_tag(tag: str, scale: float, measured: tuple[float, float] | None) -> str:
    match = re.search(r'\sstyle\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
    style = match.group(1) if match else ""
    dimension = re.compile(r"\b(width|height)\s*:\s*([\d.]+)\s*(in|px|pt|cm|mm|pc|em|rem)?",
                           re.IGNORECASE)
    found = {m.group(1).lower() for m in dimension.finditer(style)}
    if found >= {"width", "height"} or (found and measured is None):
        new_style = dimension.sub(
            lambda m: f"{m.group(1)}:{_format_number(float(m.group(2)) * scale)}{m.group(3) or ''}",
            style)
    elif measured is not None:
        stripped = dimension.sub("", style).strip().strip(";").strip()
        sized = (f"width:{_format_number(measured[0] * scale)}px; "
                 f"height:{_format_number(measured[1] * scale)}px")
        new_style = f"{stripped}; {sized}" if stripped else sized
    else:
        return tag
    if match:
        return tag[:match.start()] + f' style="{new_style}"' + tag[match.end():]
    end = -2 if tag.endswith("/>") else -1
    return tag[:end] + f' style="{new_style}"' + tag[end:]


def _close_of_div(html: str, start: int) -> int | None:
    """Index just past the </div> that closes the div starting at ``start``."""
    depth = 0
    for match in re.compile(r"<div\b|</div\s*>", re.IGNORECASE).finditer(html, start):
        if match.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return match.end()
        else:
            depth += 1
    return None


_INSIDE_COVER_DIV = '<div class="inside-cover" data-print-unit="inside-cover"></div>'
_INSIDE_COVER_DIV_UNMARKED = '<div class="inside-cover"></div>'
_INSIDE_COVER_CSS = ("@page inside-cover { @bottom-center { content: none; } }\n"
                     ".inside-cover { page: inside-cover; break-before: page; "
                     "break-after: page; height: 1pt; }")


def _insert_inside_cover(html: str, base: _Layout) -> str:
    # Match the document's own marking style, so adding the inside cover never
    # switches an unmarked document over to data-attribute reading.
    div = _INSIDE_COVER_DIV if base.marked else _INSIDE_COVER_DIV_UNMARKED
    if base.cover_ref:
        span = _tag_span(html, base.cover_ref)
        if span:
            end = _close_of_div(html, span[0])
            if end is not None:
                return html[:end] + "\n" + div + html[end:]
    later = [int(ref) for ref, page in base.ref_first_page.items() if page >= 2]
    if not later:
        return html
    span = _tag_span(html, str(min(later)))
    if span is None:
        return html
    return html[:span[0]] + div + "\n" + html[span[0]:]


def _build(source: str, params: _Params, base: _Layout) -> str:
    html = source
    css: list[str] = []
    if params.inside_cover:
        html = _insert_inside_cover(html, base)
        css.append(_INSIDE_COVER_CSS)
    if params.line_height is not None:
        delta = params.line_height - base.base_line_height
        css.append(f"body {{ line-height: {_format_number(params.line_height)}; }}")
        groups: dict[str, list[str]] = {}
        for cls in ("dialogue", "dlg-line", "lyrics-group", "reading-text"):
            if cls in base.class_line_heights:
                value = _format_number(base.class_line_heights[cls] + delta)
                groups.setdefault(value, []).append(f".{cls}")
        for value, selectors in groups.items():
            css.append(f"{', '.join(selectors)} {{ line-height: {value}; }}")
    if params.line_height is not None or params.font_pt is not None:
        # Keep the designed back page at its original size so it still fits.
        back = '.backpage, [data-print-unit="back-cover"]'
        keep = []
        if base.back_font_pt is not None:
            keep.append(f"font-size: {_format_number(base.back_font_pt)}pt")
        if base.back_line_height is not None and params.line_height is not None:
            keep.append(f"line-height: {_format_number(base.back_line_height)}")
        if keep:
            css.append(f"{back} {{ {'; '.join(keep)}; }}")
        if params.line_height is not None:
            for cls, value in base.class_line_heights.items():
                css.append(f".backpage .{cls}, [data-print-unit=\"back-cover\"] .{cls} "
                           f"{{ line-height: {_format_number(value)}; }}")
    if params.font_pt is not None:
        css.append(f"body {{ font-size: {_format_number(params.font_pt)}pt; }}")
    for ref, scale in params.music:
        html = _edit_tag(html, ref, lambda tag: _add_style(tag, "break-inside: avoid"))
        if scale != 1.0:
            for img_ref in base.img_refs.get(ref, []):
                measured = base.img_px.get(img_ref)
                html = _edit_tag(html, img_ref,
                                 lambda tag, m=measured: _scale_img_tag(tag, scale, m))
    for ref in params.sections:
        html = _edit_tag(html, ref, lambda tag: _add_style(tag, "break-before: page"))
    if css:
        block = '<style data-print-fit="1">\n' + "\n".join(css) + "\n</style>\n"
        head_end = re.search(r"</head\s*>", html, re.IGNORECASE)
        if head_end:
            html = html[:head_end.start()] + block + html[head_end.start():]
        else:
            body = re.search(r"<body\b", html, re.IGNORECASE)
            at = body.start() if body else 0
            html = html[:at] + block + html[at:]
    return html


def _steps(start: float, stop: float, step: float) -> list[float]:
    values = [round(start, 4)]
    value = (int(start / step + 1e-6) + 1) * step
    while value <= stop + 1e-6:
        if value > start + 1e-6:
            values.append(round(value, 4))
        value += step
    return values


class _Budget(Exception):
    pass


class _Fitter:
    def __init__(self, html, base_url, print_mode, inside_cover_allowed, pinned, max_renders):
        self.source = _annotate(html)
        self.base_url = base_url
        self.print_mode = print_mode
        self.inside_cover_allowed = inside_cover_allowed
        self.pinned = set(pinned)
        self.max_renders = max_renders
        self.renders = 0
        self.cache: dict[_Params, tuple[_Layout, list[Finding]]] = {}
        self.best: tuple | None = None
        self.base: _Layout | None = None

    def render(self, params: _Params) -> tuple[_Layout, list[Finding]]:
        if params in self.cache:
            return self.cache[params]
        if self.renders >= self.max_renders:
            raise _Budget()
        self.renders += 1
        layout = _layout(_build(self.source, params, self.base) if self.base else self.source,
                         self.base_url)
        if self.base is None:
            self.base = layout
        findings = check(layout.report, print_mode=self.print_mode,
                         inside_cover_allowed=self.inside_cover_allowed)
        findings.append(_wording_finding(self.base.report.text, layout.report.text))
        self.cache[params] = (layout, findings)
        score = (len(_blocking_failures(findings)), self.cost(params), self.renders)
        if self.best is None or score < self.best[0]:
            self.best = (score, params)
        return layout, findings

    def cost(self, params: _Params) -> float:
        base = self.base
        cost = COST_INSIDE_COVER if params.inside_cover else 0.0
        if params.line_height is not None and base is not None:
            cost += COST_LINE_HEIGHT_STEP * round(
                (params.line_height - base.base_line_height) / LINE_HEIGHT_STEP + 0.4999)
        if params.font_pt is not None and base is not None:
            cost += COST_TYPE_STEP * round((params.font_pt - base.base_font_pt) / BODY_PT_STEP)
        cost += sum(0.5 + (1.0 - k) * 20 for _, k in params.music)
        cost += 3.0 * len(params.sections)
        return cost

    def count_ok(self, findings: list[Finding]) -> bool:
        return all(f.passed for f in findings if f.check in _COUNT_CHECKS)

    def candidates(self) -> list[_Params]:
        base = self.base
        ic_options = [False]
        if (self.print_mode == "booklet" and self.inside_cover_allowed
                and not base.has_inside_cover):
            ic_options.append(True)
        lh_values = [None] + _steps(base.base_line_height, MAX_LINE_HEIGHT, LINE_HEIGHT_STEP)[1:]
        fs_values = [None] + _steps(base.base_font_pt, MAX_BODY_PT, BODY_PT_STEP)[1:]
        options = [_Params(inside_cover=ic, line_height=lh, font_pt=fs)
                   for ic in ic_options for lh in lh_values for fs in fs_values]
        return sorted(options, key=lambda p: (self.cost(p), p.font_pt or 0, p.line_height or 0))

    def predicted_pages(self, params: _Params) -> int | None:
        """The inside cover adds exactly one page, so its twin predicts the count."""
        twin = _Params(inside_cover=not params.inside_cover, line_height=params.line_height,
                       font_pt=params.font_pt)
        if twin in self.cache:
            pages = self.cache[twin][0].report.pages
            return pages + 1 if params.inside_cover else pages - 1
        return None

    def unit_failing(self, layout: _Layout, ref: str) -> bool:
        for unit, unit_ref in zip(layout.report.units, layout.unit_refs):
            if unit_ref == ref:
                if not _turn_ok(unit):
                    return True
                if unit.role == "opening" and unit.first_page != unit.last_page:
                    return True
                return False
        return False

    def fix_music(self, params: _Params) -> tuple[_Params, bool]:
        layout, findings = self.render(params)
        changed = False
        done = {ref for ref, _ in params.music}
        while True:
            failing = [ref for unit, ref in zip(layout.report.units, layout.unit_refs)
                       if unit.kind == "music" and ref and ref not in done
                       and self.unit_failing(layout, ref)]
            if not failing:
                return params, changed
            ref = failing[0]
            done.add(ref)

            def attempt(scale: float) -> tuple[bool, _Params]:
                trial = _Params(params.inside_cover, params.line_height, params.font_pt,
                                params.music + ((ref, scale),), params.sections)
                trial_layout, trial_findings = self.render(trial)
                ok = (not self.unit_failing(trial_layout, ref)) and self.count_ok(trial_findings)
                return ok, trial

            ok, trial = attempt(MUSIC_SCALES[0])
            chosen = trial if ok else None
            if not ok:
                ok_low, trial_low = attempt(MUSIC_SCALES[-1])
                if ok_low:
                    chosen = trial_low
                    lo, hi = 1, len(MUSIC_SCALES) - 2
                    while lo <= hi:
                        mid = (lo + hi) // 2
                        ok_mid, trial_mid = attempt(MUSIC_SCALES[mid])
                        if ok_mid:
                            chosen = trial_mid
                            hi = mid - 1
                        else:
                            lo = mid + 1
            if chosen is not None:
                params = chosen
                layout, findings = self.render(params)
                changed = True

    def fix_sections(self, params: _Params) -> tuple[_Params, bool]:
        layout, findings = self.render(params)
        report = layout.report
        exempt = _exempt_pages(report)
        failures = len(_blocking_failures(findings))
        changed = False
        low_pages = [i + 1 for i, v in enumerate(report.fill)
                     if v < FILL_BLOCK and (i + 1) not in exempt and not report.blank[i]]
        for page in low_pages:
            options = [(unit, ref) for unit, ref in zip(report.units, layout.unit_refs)
                       if unit.kind == "section" and unit.first_page == page - 1 and ref
                       and ref not in params.sections and unit.id not in self.pinned
                       and unit.module not in self.pinned]
            if not options:
                continue
            unit, ref = options[-1]
            trial = _Params(params.inside_cover, params.line_height, params.font_pt,
                            params.music, params.sections + (ref,))
            trial_layout, trial_findings = self.render(trial)
            trial_failures = len(_blocking_failures(trial_findings))
            if self.count_ok(trial_findings) and trial_failures < failures:
                params, layout, findings, failures = trial, trial_layout, trial_findings, trial_failures
                report = layout.report
                changed = True
        return params, changed

    def repair(self, params: _Params) -> _Params | None:
        for _ in range(3):
            params, music_changed = self.fix_music(params)
            if not _blocking_failures(self.render(params)[1]):
                return params
            params, section_changed = self.fix_sections(params)
            if not _blocking_failures(self.render(params)[1]):
                return params
            if not (music_changed or section_changed):
                break
        return None

    def run(self) -> _Params | None:
        _, findings = self.render(_Params())
        if not _blocking_failures(findings):
            return _Params()
        for params in self.candidates():
            predicted = self.predicted_pages(params)
            if (predicted is not None and self.print_mode == "booklet"
                    and predicted % 4 != 0):
                continue
            _, findings = self.render(params)
            if not self.count_ok(findings):
                continue
            if not _blocking_failures(findings):
                return params
            repaired = self.repair(params)
            if repaired is not None:
                return repaired
        return None


def _adjustments(params: _Params, base: _Layout, final: _Layout, print_mode: str) -> list[dict]:
    pages = final.report.pages
    common = {"pages": pages, "pages_before": base.report.pages, "print_mode": print_mode}
    result: list[dict] = []
    if params.inside_cover:
        result.append({"step": "inside_cover", "detail": {"page": 2, **common},
                       "summary": "page 2 is left blank"})
    if params.line_height is not None:
        result.append({"step": "line_height",
                       "detail": {"from": base.base_line_height, "to": params.line_height,
                                  **common},
                       "summary": "line spacing is a little looser"})
    if params.font_pt is not None:
        result.append({"step": "type_size",
                       "detail": {"from_pt": base.base_font_pt, "to_pt": params.font_pt,
                                  **common},
                       "summary": f"body type is a little larger "
                                  f"({_format_number(params.font_pt)}pt)"})
    by_ref = dict(zip(final.unit_refs, final.report.units))
    for ref, scale in params.music:
        unit = by_ref.get(ref)
        name = _named(unit, "a piece of music") if unit else "a piece of music"
        page = unit.first_page if unit else None
        where = (f"page {unit.first_page}" if unit and unit.first_page == unit.last_page
                 else f"pages {unit.first_page} and {unit.last_page}" if unit else "its pages")
        if scale < 1.0:
            summary = f"{name} prints at {round(scale * 100)}% so it fits on {where}"
        else:
            summary = f"{name} is kept together on {where}"
        result.append({"step": "music_scale",
                       "detail": {"id": unit.id if unit else None, "scale": scale,
                                  "page": page, **common},
                       "summary": summary})
    for ref in params.sections:
        unit = by_ref.get(ref)
        label = unit.id if unit and unit.id else "a section"
        page = unit.first_page if unit else None
        result.append({"step": "section_start",
                       "detail": {"id": unit.id if unit else None, "page": page, **common},
                       "summary": f"{label} starts a new page"
                                  + (f" (page {page})" if page else "")})
    return result


def describe_adjustments(adjustments: list[dict]) -> str:
    """One plain sentence naming every fitting adjustment."""
    if not adjustments:
        return "No layout adjustments were needed."
    detail = adjustments[0].get("detail", {})
    pages = detail.get("pages")
    before = detail.get("pages_before", pages)
    mode = detail.get("print_mode", "booklet")
    if mode == "booklet" and pages and before != pages:
        lead = f"To fold into {pages} pages, "
    elif pages:
        lead = f"To print cleanly on {pages} pages, "
    else:
        lead = "To print cleanly, "
    return lead + _join([a["summary"] for a in adjustments]) + "."


def fit(html: str, *, base_url: str | None = None, print_mode: str = "booklet",
        inside_cover_allowed: bool = True, pinned_section_ids: tuple[str, ...] = (),
        max_renders: int = DEFAULT_MAX_RENDERS) -> FitResult:
    """Fit a bulletin to its print mode with the smallest allowed adjustments."""
    if print_mode not in PRINT_MODES:
        raise ValueError(f"print_mode must be one of {', '.join(PRINT_MODES)}")
    started = time.monotonic()
    fitter = _Fitter(html, base_url, print_mode, inside_cover_allowed,
                     pinned_section_ids, max(1, max_renders))
    try:
        chosen = fitter.run()
    except _Budget:
        chosen = None
    base = fitter.base
    if chosen == _Params():
        layout, findings = fitter.cache[_Params()]
        return FitResult("unchanged", html, layout.report, findings, [],
                         fitter.renders, round(time.monotonic() - started, 2))
    status = "fit"
    if chosen is None:
        status = "failed"
        chosen = fitter.best[1]
    layout, findings = fitter.cache[chosen]
    fitted = html if chosen == _Params() else _strip_refs(_build(fitter.source, chosen, base))
    adjustments = _adjustments(chosen, base, layout, print_mode)
    return FitResult(status, fitted, layout.report, findings, adjustments,
                     fitter.renders, round(time.monotonic() - started, 2))


# --------------------------------------------------------------------------
# Command line


def _finding_dicts(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or fit a bulletin for printing.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "fit"):
        command = sub.add_parser(name)
        command.add_argument("html")
        if name == "fit":
            command.add_argument("out")
        command.add_argument("--print-mode", default="booklet", choices=PRINT_MODES)
        command.add_argument("--no-inside-cover", action="store_true")
        command.add_argument("--base-url", default=None)
        if name == "fit":
            command.add_argument("--pin", action="append", default=[],
                                 help="a section name whose page start must not move")
            command.add_argument("--max-renders", type=int, default=DEFAULT_MAX_RENDERS)
    args = parser.parse_args(argv)
    path = Path(args.html)
    html = path.read_text(encoding="utf-8")
    base_url = args.base_url or str(path.resolve().parent) + "/"
    allowed = not args.no_inside_cover
    if args.command == "check":
        report = measure(html, base_url=base_url)
        findings = check(report, print_mode=args.print_mode, inside_cover_allowed=allowed)
        print(json.dumps({"pages": report.pages, "findings": _finding_dicts(findings),
                          "fill": report.fill}, indent=2, ensure_ascii=False))
        return 1 if _blocking_failures(findings) else 0
    result = fit(html, base_url=base_url, print_mode=args.print_mode,
                 inside_cover_allowed=allowed, pinned_section_ids=tuple(args.pin),
                 max_renders=args.max_renders)
    Path(args.out).write_text(result.html, encoding="utf-8")
    print(json.dumps({"status": result.status, "pages": result.report.pages,
                      "adjustments": result.adjustments,
                      "summary": describe_adjustments(result.adjustments),
                      "findings": _finding_dicts(result.findings),
                      "renders": result.renders, "seconds": result.seconds},
                     indent=2, ensure_ascii=False))
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
