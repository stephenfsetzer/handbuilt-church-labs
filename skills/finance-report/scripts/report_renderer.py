#!/usr/bin/env python3
"""Finance report renderer: report.json + church.yaml + brand.json -> PDF.

Part of the finance-report skill; the report shape is described in references/shape.md.
Nothing here is specific to one church: the church, its brand, and the
figures all come from files.

    python3 report_renderer.py finance/board/2026-08/report.json --church-folder .
    python3 report_renderer.py finance/board/2026-08/report.json --church-folder . \
        --brand finance/board/brand-previews/holdfast.json --suffix holdfast

The previous month's report.json (meta.previous_report) supplies "since last
month" figures and watch-list statuses.

Writes <stem>.html, <stem>.pdf, and <stem>.receipt.json next to report.json.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import quote

from cash_position import cash_summary, signed_money

HERE = Path(__file__).resolve().parent
SHAPE_VERSION = "1.0"  # the report shape in references/shape.md, fixed on 2026-09-26
CHURCH_ROOT = Path.cwd()  # set from --church-folder in main()
BUNDLED_FONTS = HERE.parents[1] / "bulletin" / "renderer" / "fonts"  # shared with the bulletin; OFL, see THIRD-PARTY-NOTICES.md
BUNDLED = {
    "Source Serif 4": [("SourceSerif4-Regular.ttf", 400), ("SourceSerif4-SemiBold.ttf", 600),
                       ("SourceSerif4-Bold.ttf", 700)],
    "Source Sans 3": [("SourceSans3-Regular.ttf", 400), ("SourceSans3-SemiBold.ttf", 600),
                      ("SourceSans3-Bold.ttf", 700)],
    "EB Garamond": [("EBGaramond-Regular.ttf", 400), ("EBGaramond-SemiBold.ttf", 600),
                    ("EBGaramond-Bold.ttf", 700)],
}
DEFAULTS = {
    "paper": "#ffffff", "ink": "#1c1b1a",
    "positive": ["#2f5fb3", "#1f5fa8"],
    "attention": ["#c8553d", "#d9480f", "#b3261e"],
    "heading": "Source Serif 4", "body": "Source Sans 3",
}
VOCAB = {
    "episcopal": {"body": "Vestry", "judicatory": "diocese"},
    "lutheran": {"body": "Church Council", "judicatory": "synod"},
}

HALF, FULL = 346, 720  # chart widths in px at 96 dpi (letter, 0.5in margins)


# --- color science -------------------------------------------------------

def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def to_hex(c):
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in c)


def lin(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(h):
    r, g, b = (lin(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def oklab_lin(r, g, b):
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


# Vienot 1999 dichromat simulation in linear RGB
CVD = {
    "normal": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "protan": ((0.11238, 0.88762, 0), (0.11238, 0.88762, 0), (0.00401, -0.00401, 1)),
    "deutan": ((0.29275, 0.70725, 0), (0.29275, 0.70725, 0), (-0.02234, 0.02234, 1)),
}


def lab(h, kind="normal"):
    c = [lin(v) for v in rgb(h)]
    m = CVD[kind]
    s = [max(0.0, sum(m[i][j] * c[j] for j in range(3))) for i in range(3)]
    return oklab_lin(*s)


def delta_e(a, b, kind="normal"):
    return 100 * math.dist(lab(a, kind), lab(b, kind))


def chroma(h):
    _, a, b = lab(h)
    return math.hypot(a, b)


def mix(a, b, t):
    ca, cb = rgb(a), rgb(b)
    return to_hex(tuple(x * (1 - t) + y * t for x, y in zip(ca, cb)))


# --- theme resolution -----------------------------------------------------

def resolve_theme(brand, church):
    colors = brand.get("colors", {}) or {}
    typ = brand.get("type", {}) or {}
    style = brand.get("report", {}) or {}
    log = []

    paper = colors.get("paper") or DEFAULTS["paper"]
    if luminance(paper) < 0.8:
        log.append(f"paper {paper} too dark for print; using {DEFAULTS['paper']}")
        paper = DEFAULTS["paper"]
    ink = colors.get("ink")
    if ink and contrast(ink, paper) >= 7:
        log.append(f"ink {ink} from brand.json")
    else:
        log.append(f"ink {ink} fails 7:1 on paper; using {DEFAULTS['ink']}")
        ink = DEFAULTS["ink"]

    positive = None
    for key in ("positive", "accent", "accent_deep"):
        c = colors.get(key)
        if not c:
            continue
        if contrast(c, paper) >= 3 and chroma(c) >= 0.03:
            positive = c
            log.append(f"positive {c} from colors.{key}")
            break
        log.append(f"colors.{key} {c} skipped (contrast {contrast(c, paper):.1f}, chroma {chroma(c):.3f})")
    if not positive:
        positive = DEFAULTS["positive"][0]
        log.append(f"positive fallback {positive}")

    def attention_ok(c):
        return (contrast(c, paper) >= 3 and chroma(c) >= 0.05
                and delta_e(c, positive) >= 15
                and delta_e(c, positive, "deutan") >= 8
                and delta_e(c, positive, "protan") >= 8)

    attention = None
    for key in ("attention", "rubric_red"):
        c = colors.get(key)
        if not c:
            continue
        if attention_ok(c):
            attention = c
            log.append(f"attention {c} from colors.{key}")
            break
        log.append(f"colors.{key} {c} skipped (too close to positive or low contrast)")
    if not attention:
        attention = next((c for c in DEFAULTS["attention"] if attention_ok(c)), DEFAULTS["attention"][0])
        log.append(f"attention fallback {attention}")

    ramp = colors.get("ramp")
    if not ramp:
        deep = colors.get("accent_deep")
        if luminance(positive) < 0.07:
            ramp = [positive] + [mix(positive, paper, t) for t in (0.32, 0.52, 0.7, 0.86)]
        else:
            if not (deep and deep != positive and luminance(deep) < luminance(positive) * 0.6):
                deep = mix(positive, "#000000", 0.5)
            ramp = [deep, positive] + [mix(positive, paper, t) for t in (0.45, 0.7, 0.88)]
        log.append("part-to-whole ramp derived from positive")

    heading = typ.get("heading") or DEFAULTS["heading"]
    body = typ.get("body") or DEFAULTS["body"]
    theme = {
        "paper": paper, "ink": ink, "positive": positive, "attention": attention,
        "positive_soft": mix(positive, paper, 0.55), "attention_soft": mix(attention, paper, 0.6),
        "ramp": ramp, "muted": mix(ink, paper, 0.42), "rule": mix(ink, paper, 0.85),
        "panel": colors.get("panel") or mix(positive, paper, 0.94),
        "heading": heading, "body": body,
        "heading_weight": typ.get("heading_weight", 700),
        "motif": style.get("motif"),
        "positive_word": color_word(positive), "attention_word": color_word(attention),
    }
    return theme, log


def color_word(h):
    """A plain color name for the key sentence ('blue means ahead')."""
    r, g, b = rgb(h)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 0.08:
        return "gray" if mx > 0.25 else "black"
    if mx == r:
        hue = 60 * (((g - b) / (mx - mn)) % 6)
    elif mx == g:
        hue = 60 * ((b - r) / (mx - mn) + 2)
    else:
        hue = 60 * ((r - g) / (mx - mn) + 4)
    for limit, name in ((15, "red"), (45, "orange"), (65, "gold"), (160, "green"),
                        (200, "teal"), (250, "blue"), (290, "violet"), (335, "purple"), (361, "red")):
        if hue < limit:
            if name == "blue" and mx < 0.45:
                return "navy"
            if name in ("red", "orange") and mx < 0.62:
                return "brick red" if name == "red" or hue < 25 else "rust"
            return name
    return "color"


def font_css(theme):
    css, used, families = [], [], {theme["heading"], theme["body"]}
    google = []
    for fam in sorted(families):
        files = BUNDLED.get(fam)
        if files and BUNDLED_FONTS.exists():
            for fname, weight in files:
                p = BUNDLED_FONTS / fname
                if p.exists():
                    css.append(f'@font-face {{ font-family: "{fam}"; src: url("{p.as_uri()}"); font-weight: {weight}; }}')
            used.append(f"{fam}: bundled")
        else:
            google.append(fam)
            used.append(f"{fam}: Google Fonts")
    imports = ""
    if google:
        spec = "&".join(f"family={f.replace(' ', '+')}:wght@400;600;700;800" for f in google)
        imports = f"@import url('https://fonts.googleapis.com/css2?{spec}&display=swap');\n"
    return imports + "\n".join(css), used


# --- small helpers ---------------------------------------------------------

def money(v, sign=False):
    s = f"${abs(round(v)):,}"
    if sign:
        return ("+" if v >= 0 else "−") + s
    return s


def kfmt(v):
    return f"${abs(v) / 1000:,.0f}k" if abs(v) >= 1000 else f"${abs(v):,.0f}"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Draw:
    def __init__(self, t):
        self.t = t

    def text(self, x, y, s, size=11.5, weight=400, fill=None, anchor="start"):
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{self.t["body"]}" font-size="{size}" '
                f'font-weight="{weight}" fill="{fill or self.t["ink"]}" text-anchor="{anchor}">{esc(s)}</text>')

    @staticmethod
    def rect(x, y, w, h, fill, extra="", r=2.5):
        if w < 0:
            x, w = x + w, -w
        if h < 0:
            y, h = y + h, -h
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 1.2):.1f}" height="{max(h, 1.2):.1f}" rx="{r}" fill="{fill}" {extra}/>'

    def line(self, x1, y1, x2, y2, color=None, width=1.2, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{color or self.t["ink"]}" stroke-width="{width}"{d}/>')

    @staticmethod
    def svg(w, h, body):
        return f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">{"".join(body)}</svg>'

    def sign_color(self, v, soft=False):
        if v >= 0:
            return self.t["positive_soft"] if soft else self.t["positive"]
        return self.t["attention_soft"] if soft else self.t["attention"]


# --- charts ----------------------------------------------------------------

MONTH_ABBR = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]


def chart_cash(d, cash, prev_bank=None):
    """Months-of-spending boxes; last month's level as a dashed marker."""
    t = d.t
    if cash["monthly_spending"] <= 0:
        return d.svg(HALF, 72, [d.text(0, 32, "Coverage unavailable: average spending is not positive.", 10.5, 400, t["muted"])])
    n = cash["bank"] / cash["monthly_spending"]
    boxes = min(6, max(3, math.ceil(max(n, (prev_bank or 0) / cash["monthly_spending"]))))
    gap = 10
    bw = (HALF - gap * (boxes - 1)) / boxes
    h, top = 38, 12
    o = []

    def xpos(months):
        whole = min(int(months), boxes - 1)
        return whole * (bw + gap) + bw * (months - whole)

    for i in range(boxes):
        x = i * (bw + gap)
        o.append(f'<rect x="{x + 0.6:.1f}" y="{top + 0.6}" width="{bw - 1.2:.1f}" height="{h - 1.2}" rx="2.5" '
                 f'fill="none" stroke="{t["muted"]}" stroke-width="1" stroke-dasharray="4 3"/>')
        fill = min(max(n - i, 0), 1)
        if fill > 0:
            o.append(d.rect(x, top, bw * fill, h, t["positive"]))
        if fill == 1 and bw >= 70:
            o.append(d.text(x + bw / 2, top + 24, f"Month {i + 1}", 12, 700, "#ffffff", "middle"))
    if prev_bank is not None:
        previous_months = prev_bank / cash["monthly_spending"]
        px = min(HALF - 1, max(1, xpos(previous_months)))
        label = "last month"
        if previous_months > boxes:
            label += f" (>{boxes} months)"
        elif previous_months < 0:
            label += " (<0 months)"
        # Keep edge labels inside the chart without moving the cash marker.
        half_label = len(label) * 2.7
        label_x = min(HALF - half_label - 2, max(half_label + 2, px))
        o.append(d.line(px, top - 4, px, top + h + 4, t["ink"], 1.6, "3 2"))
        o.append(d.text(label_x, top - 5, label, 9.5, 600, t["muted"], "middle"))
    o.append(d.text(0, top + h + 17, f"Each box is one month of spending, about "
                    f"{money(cash['monthly_spending'])}.", 10.5, 400, t["muted"]))
    return d.svg(HALF, top + h + 22, o)


def chart_running(d, run, pending):
    """Running total through the year: plan, last year, this year."""
    t = d.t
    W, H, left, top, bottom = HALF, 146, 4, 10, 120
    has_plan = bool(run.get("plan"))
    has_last = bool(run.get("last_year"))
    series = ([run["plan"]] if has_plan else []) + ([run["last_year"]] if has_last else []) + [run["this_year"]]
    vals = [v for s in series for v in s] + [0, run["this_year"][-1] + pending]
    hi, lo = max(vals), min(vals)
    span = (hi - lo) or 1
    usable = W - left - 58

    def x(i):
        return left + usable * i / 11

    def y(v):
        return top + (hi - v) / span * (bottom - top)

    o = []
    o.append(d.line(left, y(0), left + usable, y(0), t["ink"], 1.1))
    end_labels = [(y(0) + 3.5, "break even", 9.5, 600)]

    def path(vals, color, width, dash=None):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{da}/>'

    if has_plan:
        o.append(path(run["plan"], t["muted"], 1.4, "5 3"))
    if has_last:
        o.append(path(run["last_year"], t["positive_soft"], 2.2))
    o.append(path(run["this_year"], t["positive"], 3))
    if has_plan:
        end_labels.append((y(run["plan"][-1]) + 3.5, "plan", 10, 600))
    if has_last:
        end_labels.append((y(run["last_year"][-1]) + 3.5, str(run["last_year_label"]), 10, 700))
    # Separate nearby end labels, including break even, within the plot height.
    end_labels.sort(key=lambda item: item[0])
    baselines = []
    for index, (target, *_) in enumerate(end_labels):
        ceiling = bottom + 3.5 - 12 * (len(end_labels) - index - 1)
        floor = baselines[-1] + 12 if baselines else top + 7
        baselines.append(max(floor, min(target, ceiling)))
    for baseline, (_, label, size, weight) in zip(baselines, end_labels):
        o.append(d.text(x(11) + 5, baseline, label, size, weight, t["muted"]))
    i = len(run["this_year"]) - 1
    v = run["this_year"][-1]
    o.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" fill="{d.sign_color(v)}" stroke="#ffffff" stroke-width="1.5"/>')
    if pending:
        o.append(f'<circle cx="{x(i):.1f}" cy="{y(v + pending):.1f}" r="3.6" fill="#ffffff" '
                 f'stroke="{t["positive"]}" stroke-width="1.4"/>')
    sign = "+" if v >= 0 else "−"
    label = f"{run['this_year_label']}: {sign}{kfmt(v)}"
    lw = len(label) * 6.3 + 6
    ly_ = y(v) + 18 if y(v) <= bottom - 18 else y(v) - 10
    label_left = min(W - lw - 2, max(2, x(i) - 8 - lw))
    o.append(f'<rect x="{label_left:.1f}" y="{ly_ - 11:.1f}" width="{lw:.1f}" height="15" rx="2" fill="#ffffff" opacity="0.92"/>')
    o.append(d.text(label_left + lw - 3, ly_, label, 11, 700, None, "end"))
    for k in range(12):
        o.append(d.text(x(k), H - 8, MONTH_ABBR[k], 9.5, 600 if k <= i else 400,
                        t["ink"] if k <= i else t["muted"], "middle"))
    return d.svg(W, H, o)


def share_is_proportional(parts):
    return sum(p["amount"] for p in parts) > 0 and all(p["amount"] >= 0 for p in parts)


def chart_share(d, parts):
    t = d.t
    total = sum(p["amount"] for p in parts)
    h, gap = 30, 2
    if not share_is_proportional(parts):
        label = "Net total is zero." if not any(p["amount"] for p in parts) else "Credits included; see net amounts below. Percentages are unavailable."
        return d.svg(FULL, h, [d.text(0, 20, label, 11, 400, t["muted"])]), total
    usable = FULL - gap * (len(parts) - 1)
    x, o = 0.0, []
    for i, p in enumerate(parts):
        w = usable * p["amount"] / total
        fill = t["ramp"][min(i, len(t["ramp"]) - 1)]
        stroke = f'stroke="{t["rule"]}" stroke-width="1"' if luminance(fill) > 0.75 else ""
        o.append(d.rect(x, 0, w, h, fill, stroke))
        if w > 34:
            txt = "#ffffff" if contrast("#ffffff", fill) >= 4.5 else t["ink"]
            o.append(d.text(x + w / 2, 20, f"{p['amount'] / total:.0%}", 12, 700, txt, "middle"))
        x += w + gap
    return d.svg(FULL, h, o), total


def share_legend(t, parts, total, month_name):
    cells = []
    proportional = share_is_proportional(parts)
    for i, p in enumerate(parts):
        fill = t["ramp"][min(i, len(t["ramp"]) - 1)]
        border = f"border:0.75pt solid {t['rule']};" if luminance(fill) > 0.75 else ""
        tm = p.get("this_month")
        tm_html = f' <span class="tm">&middot; {signed_money(tm)} in {esc(month_name[:3])}</span>' if tm is not None else ""
        percent = f' <span class="muted">&middot; {p["amount"] / total:.0%}</span>' if proportional else ""
        cells.append(
            f'<div class="lg"><span class="sw" style="background:{fill};{border}"></span><div>'
            f'<b>{esc(p["name"])}</b><br>{signed_money(p["amount"])}{percent}'
            f'{tm_html}<div class="lgnote">{esc(p["note"])}</div></div></div>')
    return f'<div class="legend">{"".join(cells)}</div>'


def column_axis(values, top, height):
    hi = max(max(values), 0)
    lo = min(min(values), 0)
    span = (hi - lo) or 1
    scale = height / span
    base = top + hi * scale
    return base, scale


def chart_full_years(d, rows):
    t = d.t
    vals = [r["result"] for r in rows]
    base, scale = column_axis(vals, 14, 68)
    gw = HALF / len(rows)
    bw = 40
    o = []
    for i, r in enumerate(rows):
        cx = gw * i + gw / 2
        v = r["result"]
        o.append(d.rect(cx - bw / 2, base, bw, -v * scale, d.sign_color(v)))
        ty = base - v * scale - 5 if v >= 0 else base - v * scale + 13
        label = ("+" if v >= 0 else "−") + kfmt(v)
        o.append(d.text(cx, ty, label + ("*" if r.get("one_time") else ""), 11, 700, None, "middle"))
        o.append(d.text(cx, 112, str(r["year"]), 11.5, 700, None, "middle"))
    o.append(d.line(0, base, HALF, base, t["ink"], 1.1))
    return d.svg(HALF, 116, o)


def chart_cash_line(d, hist, monthly):
    """Month-end bank cash as an area line; a new point each month."""
    t = d.t
    W, top, bottom = FULL, 16, 104
    vals = [v for _, v in hist]
    ref = monthly * 2 if monthly > 0 else None
    lo = min([0, *vals])
    hi = max([0, *vals, *([ref] if ref is not None else [])])
    span = (hi - lo) or 1
    hi += span * 0.12
    if lo < 0:
        lo -= span * 0.12
    n = len(hist)
    usable = W - 8

    def x(i):
        return 4 + usable * i / max(1, n - 1)

    def y(v):
        return top + (hi - v) / (hi - lo) * (bottom - top)

    o = []
    if ref is not None:
        o.append(d.line(0, y(ref), W, y(ref), t["muted"], 1.2, "5 3"))
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    o.append(f'<polygon points="{x(0):.1f},{y(0):.1f} {pts} {x(n - 1):.1f},{y(0):.1f}" fill="{t["positive_soft"]}" opacity="0.55"/>')
    o.append(f'<polyline points="{pts}" fill="none" stroke="{t["positive"]}" stroke-width="2.2" stroke-linejoin="round"/>')
    lo_i = vals.index(min(vals))
    for i in {0, lo_i, n - 1}:
        o.append(f'<circle cx="{x(i):.1f}" cy="{y(vals[i]):.1f}" r="3.6" fill="{t["positive"]}" stroke="#ffffff" stroke-width="1.4"/>')
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        dy = -8 if i != lo_i or i in (0, n - 1) else 16
        o.append(d.text(x(i), y(vals[i]) + dy, ("−" if vals[i] < 0 else "") + kfmt(vals[i]), 11, 700, None, anchor))
    for i, (when, _) in enumerate(hist):
        if when.endswith("-01"):
            o.append(d.line(x(i), bottom, x(i), bottom + 4, t["muted"], 1))
            o.append(d.text(x(i), bottom + 16, when[:4], 11, 700, None, "middle"))
    o.append(d.line(0, y(0), W, y(0), t["ink"], 1.1))
    return d.svg(W, bottom + 22, o)


def chart_pressure(d, pressure):
    t = d.t
    series = pressure["series"]
    years = sorted(series[0]["values"])
    vals = [s["values"][y] for s in series for y in years]
    top, h_area = 14, 70
    scale = h_area / (max(vals) * 1.05)
    base = top + h_area
    gw = HALF / len(years)
    bw = 26
    o = []
    for i, y in enumerate(years):
        cx = gw * i + gw / 2
        for j, s in enumerate(series):
            v = s["values"][y]
            x = cx - bw - 2 if j == 0 else cx + 2
            color = t["positive"] if s["role"] == "positive" else t["attention"]
            o.append(d.rect(x, base, bw, -v * scale, color))
            o.append(d.text(x + bw / 2, base - v * scale - 4, kfmt(v), 9.5, 700, None, "middle"))
        o.append(d.text(cx, base + 15, y, 11.5, 700, None, "middle"))
    o.append(d.line(0, base, HALF, base, t["ink"], 1.1))
    return d.svg(HALF, base + 20, o)


def swatch(color, border=None):
    b = f"border:0.75pt solid {border};" if border else ""
    return f'<span class="sw inline" style="background:{color};{b}"></span>'


# --- month-to-month ------------------------------------------------------------

def load_previous(report, report_path):
    """Previous month: its report file if present, else the figures carried in this one."""
    rel = report["meta"].get("previous_report")
    if rel:
        p = (report_path.parent / rel).resolve()
        if p.exists():
            prev = json.loads(p.read_text())
            return {"as_of": prev["meta"]["through"].rsplit(",", 1)[0], "bank": prev["cash"]["bank"],
                    "ytd": prev["plan"]["actual"], "watch": prev.get("watch", []), "source": str(p)}
    carried = report.get("previous")
    if carried:
        return {**carried, "watch": [], "source": "carried in report.json"}
    return None


def watch_status(item, prev_watch):
    if item.get("status") == "Resolved":
        return "Resolved"
    prev = {w["id"]: w for w in prev_watch}
    if not prev_watch:
        return item.get("status", "New")
    if item["id"] not in prev:
        return "New"
    if "metric" in item and "metric" in prev[item["id"]]:
        now, before = item["metric"], prev[item["id"]]["metric"]
        if now == before:
            return "No change"
        improved = now < before if item.get("better", "down") == "down" else now > before
        return "Better" if improved else "Worse"
    return item.get("status", "No change")


def chip(t, status):
    styles = {
        "New": (t["panel"], t["ink"], t["rule"]),
        "Better": (t["positive_soft"], t["ink"], t["positive_soft"]),
        "Worse": (t["attention_soft"], t["ink"], t["attention_soft"]),
        "No change": ("#ffffff", t["muted"], t["rule"]),
        "Resolved": ("#ffffff", t["positive"], t["positive"]),
        "To confirm": ("#ffffff", t["muted"], t["rule"]),
        "Open": (t["attention_soft"], t["ink"], t["attention_soft"]),
        "Waived": ("#ffffff", t["muted"], t["rule"]),
    }
    bg, fg, bd = styles.get(status, ("#ffffff", t["ink"], t["rule"]))
    return f'<span class="chip" style="background:{bg};color:{fg};border-color:{bd}">{esc(status)}</span>'


def delta_text(v, unit_word_up="up", unit_word_down="down"):
    if round(v) == 0:
        return "no change"
    return f"{unit_word_up if v > 0 else unit_word_down} {money(v)}"


# --- page assembly ---------------------------------------------------------

def scale_pt(text, scale):
    """Scale every pt size except the @page margins."""
    if scale == 1.0:
        return text
    head, sep, rest = text.partition("* {")
    rest = re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * scale:.2f}pt", rest)
    return head + sep + rest


def css(t, fonts, scale=1.0, footer=""):
    footer = footer.replace('\\', '').replace('"', "'")
    return scale_pt(f"""{fonts}
@page {{ size: letter; margin: 0.42in 0.5in 0.5in 0.5in;
  @bottom-left {{ content: "{footer}"; font-family: '{t['body']}'; font-size: 7.5pt; color: {t['muted']}; }}
  @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-family: '{t['body']}'; font-size: 7.5pt; color: {t['muted']}; }} }}
* {{ box-sizing: border-box; }}
body {{ font-family: '{t['body']}', sans-serif; color: {t['ink']}; background: {t['paper']};
        font-size: 9.5pt; line-height: 1.34; margin: 0; }}
.page2 {{ break-before: page; }}
h2, .title {{ font-family: '{t['heading']}', serif; font-weight: {t['heading_weight']}; }}
.hero {{ position: relative; background: {t['panel']}; border-radius: 6pt; padding: 8pt 14pt 8pt; overflow: hidden; }}
.arc {{ position: absolute; right: 0; top: 0; width: 130pt; height: 78pt; }}
.brandline {{ font-family: '{t['heading']}'; font-weight: {t['heading_weight']}; font-size: 10pt; margin-bottom: 3pt; }}
.mark {{ height: 17pt; vertical-align: -4pt; margin-right: 5pt; }}
.logo {{ height: 28pt; margin-bottom: 3pt; }}
.eyebrow {{ font-size: 7.5pt; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: {t['muted']}; }}
.title {{ font-size: 21pt; line-height: 1.05; margin: 1pt 0 2pt; }}
.lead {{ font-size: 9.5pt; max-width: 5.7in; }}
.pos {{ color: {t['positive']}; font-weight: 700; }}
.att {{ color: {t['attention']}; font-weight: 700; }}
.short {{ border-left: 3pt solid {t['positive']}; padding: 1pt 0 1pt 10pt; margin: 7pt 0 6pt; font-size: 10pt; line-height: 1.38; }}
.tiles {{ display: flex; gap: 7pt; margin-bottom: 2pt; }}
.tile {{ flex: 1; border: 0.75pt solid {t['rule']}; border-radius: 5pt; padding: 5pt 8pt 5pt; }}
.tile .lab {{ font-size: 7.5pt; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: {t['muted']}; }}
.tile .val {{ font-family: '{t['heading']}'; font-weight: {t['heading_weight']}; font-size: 15pt; line-height: 1.15; }}
.tile .chg {{ font-size: 8.5pt; }}
.row {{ display: flex; gap: 20pt; }}
.row > div {{ flex: 1; min-width: 0; }}
.q {{ padding: 6pt 0 5pt; border-bottom: 0.75pt solid {t['rule']}; }}
.q.last {{ border-bottom: none; }}
.num {{ font-size: 7.5pt; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: {t['muted']}; }}
h2 {{ font-size: 12.5pt; margin: 0 0 2pt; line-height: 1.15; }}
.answer {{ font-size: 9.5pt; margin: 0 0 5pt; }}
.note {{ font-size: 8.5pt; color: {t['muted']}; margin: 4pt 0 0; line-height: 1.35; }}
.muted {{ color: {t['muted']}; }}
.legend {{ display: flex; gap: 10pt; margin-top: 5pt; }}
.lg {{ flex: 1; display: flex; gap: 5pt; font-size: 8.5pt; line-height: 1.25; }}
.tm {{ font-size: 8pt; font-weight: 700; }}
.sw {{ flex: none; width: 10pt; height: 10pt; border-radius: 2pt; margin-top: 1.5pt; display: inline-block; }}
.sw.inline {{ width: 9pt; height: 9pt; margin: 0 3pt 0 0; vertical-align: -1pt; }}
.lgnote {{ font-size: 7.5pt; color: {t['muted']}; }}
.keyline {{ font-size: 8.5pt; color: {t['muted']}; margin-top: 3pt; }}
.keyline span {{ margin-right: 10pt; white-space: nowrap; }}
.band {{ display: flex; justify-content: space-between; align-items: baseline;
         border-bottom: 1.25pt solid {t['ink']}; padding-bottom: 3pt; margin-bottom: 4pt; }}
.band .title {{ font-size: 17pt; margin: 0; }}
table.watch {{ width: 100%; border-collapse: collapse; font-size: 8.75pt; margin-top: 3pt; }}
table.watch th {{ text-align: left; font-size: 7.5pt; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
                  color: {t['muted']}; padding: 0 6pt 3pt 0; border-bottom: 0.75pt solid {t['rule']}; }}
table.watch td {{ padding: 3pt 6pt 3pt 0; border-bottom: 0.75pt solid {t['rule']}; vertical-align: top; line-height: 1.3; }}
table.watch td.what {{ font-weight: 700; width: 24%; }}
table.watch td.st {{ width: 11%; }}
.chip {{ display: inline-block; font-size: 7.5pt; font-weight: 700; padding: 1pt 5pt; border-radius: 8pt;
         border: 0.75pt solid; white-space: nowrap; }}
.oblig {{ display: flex; gap: 8pt; margin-top: 4pt; font-size: 8.75pt; }}
.oblig div {{ flex: 1; border: 0.75pt solid {t['rule']}; border-radius: 5pt; padding: 4pt 7pt; }}
.oblig b {{ display: block; margin-bottom: 2pt; }}
.readyrow {{ margin-top: 5pt; font-size: 8.5pt; line-height: 1.9; }}
.readyrow .ri {{ white-space: nowrap; margin-right: 8pt; }}
.how {{ margin-top: 6pt; font-size: 8pt; color: {t['muted']}; line-height: 1.35;
        border-top: 0.75pt solid {t['rule']}; padding-top: 5pt; }}
.how b {{ color: {t['ink']}; }}
.recon {{ font-size: 8pt; color: {t['attention']}; font-weight: 700; }}
""", scale)


def header(t, church, brand, meta, vocab, nq):
    name = church.get("name", "")
    logo = brand.get("logo", {}) or {}
    banner, mark = logo.get("banner"), logo.get("mark")
    if banner and (CHURCH_ROOT / banner).exists():
        brandline = f'<img class="logo" src="{(CHURCH_ROOT / banner).as_uri()}">'
    elif mark and (CHURCH_ROOT / mark).exists():
        brandline = f'<div class="brandline"><img class="mark" src="{(CHURCH_ROOT / mark).as_uri()}">{esc(name)}</div>'
    else:
        brandline = f'<div class="brandline">{esc(name)}</div>'
    arc = ""
    if t["motif"] == "arc":
        arc = (f'<svg class="arc" viewBox="0 0 200 120" xmlns="http://www.w3.org/2000/svg">'
               f'<circle cx="200" cy="0" r="95" fill="none" stroke="{t["positive"]}" stroke-width="34"/></svg>')
    status = "Draft for review" if meta["status"] != "final" else "Final"
    return f"""<div class="hero">{arc}{brandline}
<div class="eyebrow">{esc(meta['report'])} &middot; {esc(vocab['body'])}, {esc(meta['meeting_date'])} &middot; {status}</div>
<div class="title">Where we stand: {esc(meta['month_name'])}</div>
<div class="lead">{nq} questions about our money, through {esc(meta['through'])}. Where a picture
compares, <span class="pos">{t['positive_word']}</span> means money ahead and
<span class="att">{t['attention_word']}</span> means money short.</div></div>"""


def build_html(report, church_doc, brand, theme, fonts, prev):
    t, d = theme, Draw(theme)
    meta = report["meta"]
    church = church_doc.get("church", {})
    tradition = (church.get("tradition") or "").lower()
    vocab = dict(VOCAB.get(tradition, {"body": "Board", "judicatory": "judicatory"}))
    gb = (church_doc.get("leadership", {}) or {}).get("governing_body", {}) or {}
    if gb.get("label"):
        vocab["body"] = gb["label"]
    mname = meta["month_name"]
    cash, plan, tm = report["cash"], report["plan"], report["this_month"]
    pending = sum(u["amount"] for u in plan.get("unrecorded", []))

    # since last month strip
    since = f"since {prev['as_of']}" if prev else ""
    bank_chg = f"{delta_text(cash['bank'] - prev['bank'])} {since}" if prev else "&nbsp;"
    ytd_chg = f"{delta_text(plan['actual'] - prev['ytd'])} in {mname}" if prev else "&nbsp;"
    ytd_word = "ahead" if plan["actual"] >= 0 else "short"
    tiles = f"""<div class="eyebrow" style="margin-bottom:3pt">Since last month</div><div class="tiles">
<div class="tile"><div class="lab">Bank cash</div><div class="val">{signed_money(cash['bank'])}</div><div class="chg">{bank_chg}</div></div>
<div class="tile"><div class="lab">Year so far</div><div class="val">{money(plan['actual'])} {ytd_word}</div><div class="chg">{ytd_chg}</div></div>
<div class="tile"><div class="lab">Money in, {esc(mname)}</div><div class="val">{signed_money(tm['came_in'])}</div>
<div class="chg">Most: {esc(tm['top_in']['label'])}, {signed_money(tm['top_in']['amount'])}</div></div>
<div class="tile"><div class="lab">Money out, {esc(mname)}</div><div class="val">{signed_money(tm['went_out'])}</div>
<div class="chg">Largest: {esc(tm['top_out']['label'])}, {signed_money(tm['top_out']['amount'])}</div></div></div>"""

    q1 = f"""<div class="q"><div class="num">Question 1</div><h2>Can we pay our bills?</h2>
<p class="answer">{esc(cash_summary(cash['bank'], cash['monthly_spending']))}</p>{chart_cash(d, cash, prev['bank'] if prev else None)}
<p class="note">{esc(cash.get('note', ''))}</p></div>"""

    run = plan["running"]
    m = len(run["this_year"])
    ly_now, ly_end = (run["last_year"][m - 1], run["last_year"][-1]) if run.get("last_year") else (None, None)
    has_budget = plan.get("budget") is not None
    on_plan = ("Yes" if plan["actual"] >= plan["budget"] else "Not yet") if has_budget else ""
    pend_line = ""
    if pending:
        pend_line = (f'<span><svg width="10" height="10"><circle cx="5" cy="5" r="3.6" fill="#fff" stroke="{t["positive"]}" '
                     f'stroke-width="1.4"/></svg> With {money(pending)} not yet recorded</span>')
    last_sentence = (f" Last year was {money(ly_now)} {'ahead' if ly_now >= 0 else 'short'} at this point and "
                     f"ended {money(ly_end)} {'ahead' if ly_end >= 0 else 'short'}." if ly_now is not None
                     else " This is the first year the books can compare.")
    last_key = (f"<span>{swatch(t['positive_soft'])}{run['last_year_label']}</span>" if ly_now is not None else "")
    plan_key = (f'<span><svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4" stroke="{t["muted"]}" '
                f'stroke-width="1.4" stroke-dasharray="5 3"/></svg> Plan</span>') if has_budget else ""
    q2 = f"""<div class="q"><div class="num">Question 2</div><h2>Are we on plan?</h2>
<p class="answer">{(on_plan + ". The plan was <b>" + money(plan['budget']) + " ahead</b> by now; we are") if has_budget
 else "There is no budget to compare with. We are"}
<b>{money(plan['actual'])} {ytd_word}</b>.{last_sentence}</p>
{chart_running(d, run, pending)}
<div class="keyline"><span>{swatch(t['positive'])}{run['this_year_label']}</span>{last_key}
{plan_key}{pend_line}</div></div>"""

    inc_svg, inc_total = chart_share(d, report["income"]["parts"])
    sp_svg, sp_total = chart_share(d, report["spending"]["parts"])
    def share_answer(section, total, monthly, noun):
        parts = section["parts"]
        if share_is_proportional(parts):
            lead = f"{esc(section['headline'])}: <b>{parts[0]['amount'] / total:.0%}</b> of {noun} this year."
        else:
            lead = "The net total for this year is zero." if not any(p["amount"] for p in parts) else "Credits are included; percentages would be misleading."
        return f"{lead} Total {noun}: {signed_money(total)} this year; {signed_money(monthly)} in {esc(mname)}."

    q3 = f"""<div class="q"><div class="num">Question 3</div><h2>Where does our money come from?</h2>
<p class="answer">{share_answer(report['income'], inc_total, tm['came_in'], 'income')}</p>
{inc_svg}{share_legend(t, report['income']['parts'], inc_total, mname)}</div>"""
    q4 = f"""<div class="q last"><div class="num">Question 4</div><h2>Where does it go?</h2>
<p class="answer">{share_answer(report['spending'], sp_total, tm['went_out'], 'spending')}</p>
{sp_svg}{share_legend(t, report['spending']['parts'], sp_total, mname)}</div>"""

    # page 2
    prev_watch = prev.get("watch", []) if prev else []
    wrows = "".join(
        f'<tr><td class="what">{esc(w["title"])}</td><td class="st">{chip(t, watch_status(w, prev_watch))}</td>'
        f'<td>{"<span class=recon>Update needed. </span>" if w.get("needs_update") else ""}{esc(w["latest"])}</td>'
        f'<td class="muted">{esc(w["next"])}</td></tr>' for w in report.get("watch", []))
    ready = report.get("readiness")
    ready_row = ""
    if ready:
        ready_row = ('<div class="readyrow"><div><b>Books readiness</b> <span class="muted">still being fixed; '
                     'each is explained under how to read this report</span></div>' +
                     "".join(f'<span class="ri">{chip(t, r["status"].capitalize())} {esc(r["title"])}</span>' for r in ready) +
                     '</div>')
    watch = f"""<div class="q"><h2>Watch list <span class="muted" style="font-size:8.5pt;font-weight:400">open items, carried month to month until resolved</span></h2>
<table class="watch"><tr><th>Item</th><th>Status</th><th>Latest</th><th>Next step</th></tr>{wrows}</table>
<div class="oblig"><div style="flex:1.3;border:none;padding:4pt 0"><b>Obligations</b><span class="muted">Treasurer confirms each is current.</span></div>{''.join(f'<div><b>{esc(o["name"])}</b>{chip(t, o["status"])}</div>' for o in report.get('obligations', []))}</div>{ready_row}
</div>"""

    short_history = bool(report.get("short_history")) or not report.get("full_years") or not report.get("pressure")
    def longer_view():
        hist = report["cash_history"]
        first_label = MONTHS_LONG[int(hist[0][0][5:7]) - 1] + " " + hist[0][0][:4]
        lo = min(hist, key=lambda h: h[1])
        lo_label = MONTHS_LONG[int(lo[0][5:7]) - 1] + " " + lo[0][:4]
        change = hist[-1][1] - hist[0][1]
        trend_word = ("Down" if change < 0 else "Up") if abs(change) > 0.05 * abs(hist[0][1]) else "About level"
        low_note = (f" The low point was {signed_money(lo[1])} in {lo_label}." if lo[0] not in (hist[0][0], hist[-1][0]) else "")
        spending_key = (f'<span><svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4" '
                        f'stroke="{t["muted"]}" stroke-width="1.2" stroke-dasharray="5 3"/></svg> Two months of spending</span>') if cash['monthly_spending'] > 0 else ""
        q5 = f"""<div class="q"><div class="num">Question 5</div><h2>Is our cash growing or shrinking?</h2>
    <p class="answer">{trend_word} since {first_label}: from <b>{signed_money(hist[0][1])}</b> to
    <b>{signed_money(hist[-1][1])}</b> at the end of {esc(mname)}.{low_note}</p>
    {chart_cash_line(d, hist, cash['monthly_spending'])}
    <div class="keyline"><span>{swatch(t['positive'])}Bank cash at each month end</span><span><svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4" stroke="{t['ink']}" stroke-width="1.1"/></svg> Zero cash</span>{spending_key}</div>
    <p class="note">{esc(report.get('cash_history_note', ''))}</p></div>"""

        fy = report["full_years"]
        one_time = [r for r in fy if r.get("one_time")]
        ot_note = " ".join(
            f"{r['year']} leaves out a one-time {money(r['one_time']['amount'])} {esc(r['one_time']['label'])}"
            f" (the books show {money(r['reported'], True)})." for r in one_time)
        def aw(v):
            return f"{money(v)} {'ahead' if v >= 0 else 'short'}"
        if len(fy) == 1:
            fy_answer = f"{fy[0]['year']} ended <b>{aw(fy[0]['result'])}</b>."
        else:
            rising = all(fy[i]["result"] < fy[i + 1]["result"] for i in range(len(fy) - 1))
            falling = all(fy[i]["result"] > fy[i + 1]["result"] for i in range(len(fy) - 1))
            lead = "Better each year" if rising else ("Worse each year" if falling else "Up and down")
            fy_answer = (f"{lead}: from <b>{aw(fy[0]['result'])}</b> in {fy[0]['year']} "
                         f"to <b>{aw(fy[-1]['result'])}</b> in {fy[-1]['year']}.")
        q6 = f"""<div class="q last"><div class="num">Question 6 &middot; updated yearly</div><h2>How have whole years gone?</h2>
    <p class="answer">{fy_answer}</p>{chart_full_years(d, fy)}
    {f'<p class="note">* {ot_note}</p>' if ot_note else ''}</div>"""

        pr = report["pressure"]
        keys = "".join(
            f'<span>{swatch(t["positive"] if s["role"] == "positive" else t["attention"])}{esc(s["name"])}</span>'
            for s in pr["series"])
        q7 = f"""<div class="q last"><div class="num">Question 7 &middot; updated yearly</div><h2>{esc(pr['question'])}</h2>
    <p class="answer">{esc(pr['answer'])}</p>{chart_pressure(d, pr)}
    <div class="keyline">{keys}</div><p class="note">{esc(pr.get('note', ''))}</p></div>"""

        return f"""{q5}<div class="row"><div>{q6}</div><div>{q7}</div></div>"""

    longer = "" if short_history else longer_view()
    sources = "; ".join(f"{esc(s['name'])} ({esc(s['method'])}, {esc(s['pulled'])})" for s in report["sources"])
    recon = ""
    if meta.get("reconstructed"):
        recon = ('<span class="recon">Sample edition: rebuilt on ' + esc(meta["prepared"]) +
                 ' from the books as they stand today, to show the month-to-month format.</span> ')
    caveats = (" ".join(esc(r["caveat"]) + (f" (Waived: {esc(r['reason'])}.)" if r["status"] == "waived" and r.get("reason") else "")
                        for r in ready) if ready is not None
               else "Until each month is closed in the books, recent figures can still change.")
    how = f"""<div class="how">{recon}<b>How to read this report.</b> Figures are rounded to the nearest dollar.
Bank cash counts our everyday bank accounts, not the endowment. {caveats} <b>Sources:</b> {sources}.</div>"""

    footer_txt = f"{church.get('name', '')} · {meta['report']} through {meta['through']} · {vocab['body']}, {meta['meeting_date']}"
    short_answer = f'<div class="short">{esc(report["short_answer"])}</div>'
    page1 = f"""{header(t, church, brand, meta, vocab, 'Four' if short_history else 'Seven')}{short_answer}
{tiles}<div class="row"><div>{q1}</div><div>{q2}</div></div>{q3}{q4}"""
    page2 = f"""<div class="page2"><div class="band"><div class="title">Watch list and the longer view</div>
<div class="eyebrow">What to follow from month to month</div></div>{watch}{longer}{how}</div>"""
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Where We Stand</title>'
            f'<style>{css(t, fonts, theme.get("scale", 1.0), footer_txt)}</style></head><body>{page1}{page2}</body></html>')


MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]


# --- data check ----------------------------------------------------------------

def validate(data, schema, root=None, path="report"):
    """A small subset of JSON Schema: required, properties, items, enum, sizes, $ref."""
    root = root or schema
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].split("/")[-1]]
    errors = []
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} is not one of {schema['enum']}")
    if isinstance(data, dict):
        for k in schema.get("required", []):
            if k not in data:
                errors.append(f"{path}: missing '{k}'")
        for k, sub in schema.get("properties", {}).items():
            if k in data:
                errors += validate(data[k], sub, root, f"{path}.{k}")
    if isinstance(data, list):
        if len(data) < schema.get("minItems", 0) or len(data) > schema.get("maxItems", 10 ** 6):
            errors.append(f"{path}: {len(data)} items, outside {schema.get('minItems', 0)} to {schema.get('maxItems', 'any')}")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(data):
                errors += validate(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(data, str) and len(data) < schema.get("minLength", 0):
        errors.append(f"{path}: too short")
    return errors


def unverified_figures(report):
    """Dollar amounts in the written parts that match no figure in the data."""
    known = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            known.add(round(abs(x)))
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("short_answer", "latest"):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(report)
    texts = [("short answer", report.get("short_answer", ""))] + \
            [(f"watch: {w.get('title')}", w.get("latest", "")) for w in report.get("watch", [])]
    bad = []
    for where, text in texts:
        for m in re.finditer(r"\$([\d,]+(?:\.\d+)?)(k)?", text):
            v = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
            tol = 500 if m.group(2) else 1
            if not any(abs(v - k) <= tol for k in known):
                bad.append(f"{where}: {m.group(0)}")
    return bad


# --- checks ----------------------------------------------------------------

def verify(pdf, html):
    checks = {}
    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        checks["pages"] = pages
        checks["pages_ok"] = 1 <= pages <= 2
    if shutil.which("pdffonts"):
        rows = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True).stdout.splitlines()[2:]
        checks["fonts"] = [r.split()[0] for r in rows]
        checks["fonts_embedded"] = all(" yes " in f" {r} " for r in rows)
    if shutil.which("pdftotext"):
        txt = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
        checks["no_dashes"] = "—" not in txt and "–" not in txt
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--church-folder", default=".")
    ap.add_argument("--brand", help="brand file; defaults to the church's brand.json")
    ap.add_argument("--suffix", default="")
    args = ap.parse_args(argv)
    global CHURCH_ROOT
    CHURCH_ROOT = Path(args.church_folder).resolve()
    args.brand = args.brand or str(CHURCH_ROOT / "brand.json")
    args.church = str(CHURCH_ROOT / "church.yaml")

    import yaml
    import weasyprint
    report_path = Path(args.report).resolve()
    report = json.loads(report_path.read_text())
    schema = json.loads((HERE.parent / "schema" / "report.schema.json").read_text())
    problems = validate(report, schema)
    if problems:
        raise SystemExit("report.json does not match the schema:\n  " + "\n  ".join(problems))
    brand_path = Path(args.brand)
    brand = json.loads(brand_path.read_text()) if brand_path.exists() else {}
    church_doc = yaml.safe_load(Path(args.church).read_text())
    theme, log = resolve_theme(brand, church_doc)
    fonts, font_log = font_css(theme)

    short = (church_doc.get("church", {}).get("short_name") or "church").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", short.replace("'", "").replace("\u2019", "")).strip("-")
    stem = f"{slug}-finance-report-{report['meta']['month']}"
    if args.suffix:
        stem += f"-{args.suffix}"
    out = report_path.parent
    prev = load_previous(report, report_path)
    # Fit: a brand whose type runs wide steps text down, at most 10 percent.
    for scale in (1.0, 0.96, 0.92, 0.9):
        theme["scale"] = scale
        html = build_html(report, church_doc, brand, theme, fonts, prev)
        doc = weasyprint.HTML(string=html, base_url=str(out)).render()
        if len(doc.pages) <= 2:
            break
    (out / f"{stem}.html").write_text(html)
    pdf = out / f"{stem}.pdf"
    doc.write_pdf(str(pdf))
    checks = verify(pdf, html)
    checks["pages"] = len(doc.pages)
    checks["pages_ok"] = 1 <= len(doc.pages) <= 2
    bad = unverified_figures(report)
    checks["figures_verified"] = not bad
    if bad:
        checks["unverified_figures"] = bad
    receipt = {
        "rendered": date.today().isoformat(), "shape_version": SHAPE_VERSION,
        "report": str(report_path), "brand": str(Path(args.brand).resolve()),
        "theme": {k: v for k, v in theme.items() if k not in ("heading_weight",)},
        "brand_resolution": log, "fonts": font_log, "checks": checks,
        "previous_month": (prev or {}).get("source"),
        "sources": report["sources"], "status": report["meta"]["status"],
    }
    (out / f"{stem}.receipt.json").write_text(json.dumps(receipt, indent=2))
    if not checks["pages_ok"]:
        raise SystemExit("FAIL: report must be one or two pages")
    warnings = []
    if bad:
        msg = "Figures in the written parts that match nothing in the data: " + "; ".join(bad)
        if report["meta"]["status"] == "final":
            raise SystemExit("FAIL: " + msg)
        warnings.append(msg)
    print(json.dumps({"status": "ready_for_review" if report["meta"]["status"] != "final" else "ok",
                      "pdf": str(pdf), "receipt": str(out / f"{stem}.receipt.json"),
                      "checks": checks, "warnings": warnings}, indent=1))


if __name__ == "__main__":
    main()
