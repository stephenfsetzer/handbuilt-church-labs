"""Render brand/guide.md to a PDF set in the church's own brand.

The guide is the first artifact the new brand is applied to. It reads the
approved brand system from brand.json, or the staged one while the workflow
is still running, and falls back to the neutral bulletin palette and the
bundled open fonts before any brand exists.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
BUNDLED_FONTS = SKILL_DIR.parent / "bulletin" / "renderer" / "fonts"
NEUTRAL = {"ink": "#1a1a1a", "accent": "#4a5d7e", "accent_deep": "#2e3a52", "paper": "#ffffff", "rubric_red": "#8B3A3A"}

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
UNORDERED = re.compile(r"^\s*[-*]\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
DECISION_LABELS = ("**Options considered:**", "**Shown on:**", "**Recommended:**", "**Decision:**", "**Why:**")
WAYFINDING_LABELS = ("**Where you are:**", "**You decide today:**", "**Next you will see:**")


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = IMAGE.sub(lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" alt="{html.escape(m.group(1), quote=True)}">', out)
    out = INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = BOLD.sub(r"<strong>\1</strong>", out)
    out = ITALIC.sub(r"<em>\1</em>", out)
    out = LINK.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', out)
    return out


def markdown_to_html(text: str) -> str:
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            body = " ".join(s.strip() for s in paragraph)
            stripped = body.strip()
            if IMAGE.fullmatch(stripped):
                m = IMAGE.fullmatch(stripped)
                out.append(f'<figure><img src="{html.escape(m.group(2), quote=True)}" alt="{html.escape(m.group(1), quote=True)}">'
                           + (f"<figcaption>{html.escape(m.group(1))}</figcaption>" if m.group(1) else "") + "</figure>")
            elif stripped.startswith(WAYFINDING_LABELS):
                out.append(f'<p class="wayfinding">{_inline(body)}</p>')
            elif stripped.startswith(DECISION_LABELS):
                out.append(f'<p class="decision-line">{_inline(body)}</p>')
            else:
                out.append(f"<p>{_inline(body)}</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            i += 1
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        m = HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue
        if re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", line):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith("<"):
            flush()
            block = []
            while i < len(lines) and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append("\n".join(block))
            continue
        if line.lstrip().startswith(">"):
            flush()
            block = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                block.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{_inline(' '.join(block))}</p></blockquote>")
            continue
        if "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            flush()
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table>")
            continue
        if UNORDERED.match(line) or ORDERED.match(line):
            flush()
            ordered = bool(ORDERED.match(line))
            pattern = ORDERED if ordered else UNORDERED
            items = []
            while i < len(lines) and lines[i].strip():
                m = pattern.match(lines[i])
                if m:
                    items.append(m.group(1))
                elif items and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + f"</{tag}>")
            continue
        paragraph.append(line)
        i += 1
    flush()
    return "\n".join(out)


def _brand_source(root: Path) -> tuple[str, dict[str, Any], dict[str, str]]:
    brand = json.loads((root / "brand.json").read_text(encoding="utf-8"))
    colors = {k: (brand.get("colors") or {}).get(k) or NEUTRAL[k] for k in NEUTRAL}
    system = brand.get("brand_system")
    if isinstance(system, dict) and system.get("approved_on"):
        return "approved", system, colors
    staged = root / "brand" / "staging" / "brand-system.json"
    if staged.is_file():
        data = json.loads(staged.read_text(encoding="utf-8"))
        if isinstance(data.get("brand_system"), dict):
            staged_colors = data.get("colors") or {}
            colors = {k: staged_colors.get(k) or colors[k] for k in NEUTRAL}
            return "staged", data["brand_system"], colors
    return "neutral", {}, colors


def _font_faces(root: Path, system: dict[str, Any]) -> tuple[str, str, str]:
    """Return (@font-face css, display family, text family)."""
    fonts = system.get("type") if isinstance(system.get("type"), dict) else {}
    css = []
    families = {}
    weights = {"regular": ("normal", "normal"), "bold": ("700", "normal"), "italic": ("normal", "italic"),
               "bold_italic": ("700", "italic"), "semibold": ("600", "normal")}
    for role in ("display", "text"):
        entry = fonts.get(role) if isinstance(fonts.get(role), dict) else None
        if entry and isinstance(entry.get("files"), dict):
            family = entry["family"]
            for face, rel in entry["files"].items():
                weight, style = weights.get(face, ("normal", "normal"))
                src = (root / rel).resolve().as_uri()
                css.append(f'@font-face {{ font-family: "{family}"; src: url("{src}"); font-weight: {weight}; font-style: {style}; }}')
            families[role] = family
    if "display" not in families:
        for face, weight, style in (("SourceSerif4-Regular.ttf", "normal", "normal"), ("SourceSerif4-Bold.ttf", "700", "normal"), ("SourceSerif4-Italic.ttf", "normal", "italic")):
            css.append(f'@font-face {{ font-family: "Source Serif 4"; src: url("{(BUNDLED_FONTS / face).as_uri()}"); font-weight: {weight}; font-style: {style}; }}')
        families["display"] = "Source Serif 4"
    if "text" not in families:
        for face, weight, style in (("SourceSans3-Regular.ttf", "normal", "normal"), ("SourceSans3-Bold.ttf", "700", "normal"), ("SourceSans3-Italic.ttf", "normal", "italic")):
            css.append(f'@font-face {{ font-family: "Source Sans 3"; src: url("{(BUNDLED_FONTS / face).as_uri()}"); font-weight: {weight}; font-style: {style}; }}')
        families["text"] = "Source Sans 3"
    return "\n".join(css), families["display"], families["text"]


def _palette(system: dict[str, Any], colors: dict[str, str]) -> dict[str, str]:
    palette = system.get("palette") if isinstance(system.get("palette"), dict) else {}
    def pick(*keys: str, fallback: str) -> str:
        for key in keys:
            entry = palette.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("hex"), str):
                return entry["hex"]
        return fallback
    return {
        "ink": pick("ink", "text", fallback=colors["ink"]),
        "accent": pick("primary", "accent", fallback=colors["accent"]),
        "deep": pick("deep", "accent_deep", "secondary", fallback=colors["accent_deep"]),
        "paper": pick("paper", "background", fallback=colors["paper"]),
        "rubric": pick("rubric", "highlight", fallback=colors["rubric_red"]),
    }


def _church_name(root: Path) -> str:
    """church.yaml is the authority for identity; brand.json holds only overrides."""
    brand = json.loads((root / "brand.json").read_text(encoding="utf-8")).get("church") or {}
    for key in ("public_name", "short_name", "name"):
        value = brand.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        import yaml  # noqa: WPS433
        data = yaml.safe_load((root / "church.yaml").read_text(encoding="utf-8")) or {}
        church = data.get("church") if isinstance(data.get("church"), dict) else {}
        for key in ("name", "short_name"):
            value = church.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:  # noqa: BLE001
        pass
    return "Your church"


def _cover(root: Path, system: dict[str, Any], church_name: str, source: str) -> str:
    marks = system.get("marks") if isinstance(system.get("marks"), dict) else {}
    name = (system.get("name") or {}).get("wordmark") if isinstance(system.get("name"), dict) else None
    direction = (system.get("direction") or {}).get("name") if isinstance(system.get("direction"), dict) else None
    parts = ['<section class="cover">']
    wordmark = marks.get("wordmark")
    primary = marks.get("primary")
    if primary and (root / primary).is_file():
        parts.append(f'<img class="cover-mark" src="{html.escape(primary, quote=True)}" alt="">')
    if wordmark and (root / wordmark).is_file():
        parts.append(f'<img class="cover-wordmark" src="{html.escape(wordmark, quote=True)}" alt="{html.escape(name or church_name)}">')
    else:
        parts.append(f'<h1 class="cover-title">{html.escape(name or church_name)}</h1>')
    parts.append('<p class="cover-kicker">Brand Guide</p>')
    if direction:
        parts.append(f'<p class="cover-direction">{html.escape(direction)}</p>')
    status = {"approved": f"Approved {system.get('approved_on', '')}".strip(), "staged": "Working draft, not yet approved", "neutral": "Started, before any brand decision"}[source]
    parts.append(f'<p class="cover-status">{html.escape(status)} · rendered {date.today().isoformat()}</p>')
    parts.append("</section>")
    return "\n".join(parts)


def build_html(root: Path, markdown: str) -> tuple[str, str]:
    source, system, colors = _brand_source(root)
    faces, display, text = _font_faces(root, system)
    pal = _palette(system, colors)
    church_name = (system.get("name") or {}).get("short") if isinstance(system.get("name"), dict) else None
    church_name = church_name or _church_name(root)
    body = markdown_to_html(markdown)
    body = re.sub(r"^<h1>.*?</h1>\n?", "", body, count=1)
    css = f"""
{faces}
@page {{ size: letter; margin: 0.9in 0.85in 0.9in 0.85in;
  @bottom-left {{ content: "{html.escape(church_name)} · Brand Guide"; font-family: "{text}"; font-size: 8.5pt; color: {pal['deep']}; letter-spacing: 0.04em; }}
  @bottom-right {{ content: counter(page); font-family: "{text}"; font-size: 8.5pt; color: {pal['deep']}; }} }}
@page cover {{ margin: 0; @bottom-left {{ content: none; }} @bottom-right {{ content: none; }} }}
html {{ color: {pal['ink']}; background: {pal['paper']}; }}
body {{ font-family: "{display}", Georgia, serif; font-size: 11pt; line-height: 1.5; }}
.cover {{ page: cover; height: 11in; padding: 1.4in 1.1in; box-sizing: border-box; background: {pal['accent']}; color: {pal['paper']}; page-break-after: always; }}
.cover-mark {{ max-height: 1.6in; max-width: 2.4in; margin-bottom: 0.6in; }}
.cover-wordmark {{ max-width: 5.5in; max-height: 1.6in; display: block; }}
.cover-title {{ font-size: 34pt; line-height: 1.1; margin: 0; font-weight: 700; }}
.cover-kicker {{ font-family: "{text}"; text-transform: uppercase; letter-spacing: 0.18em; font-size: 10pt; margin: 0.5in 0 0 0; }}
.cover-direction {{ font-size: 16pt; margin: 0.2in 0 0 0; font-style: italic; }}
.cover-status {{ font-family: "{text}"; font-size: 9pt; position: absolute; bottom: 1.0in; left: 1.1in; opacity: 0.85; }}
h2 {{ font-size: 22pt; line-height: 1.15; margin: 0 0 14pt 0; padding-top: 0.2in; page-break-before: always; color: {pal['accent']}; }}
h2:first-of-type {{ page-break-before: auto; }}
h3 {{ font-family: "{text}"; text-transform: uppercase; letter-spacing: 0.1em; font-size: 9.5pt; color: {pal['deep']}; margin: 18pt 0 6pt 0; }}
h4 {{ font-family: "{text}"; font-size: 11pt; margin: 14pt 0 4pt 0; }}
p {{ margin: 0 0 9pt 0; }}
ul, ol {{ margin: 0 0 9pt 1.2em; padding: 0; }}
li {{ margin: 0 0 4pt 0; }}
blockquote {{ margin: 10pt 0; padding: 4pt 0 4pt 14pt; border-left: 3pt solid {pal['accent']}; color: {pal['deep']}; }}
table {{ border-collapse: collapse; width: 100%; margin: 8pt 0 12pt 0; font-family: "{text}"; font-size: 9.5pt; }}
th {{ text-align: left; border-bottom: 1.5pt solid {pal['accent']}; padding: 4pt 6pt; color: {pal['deep']}; }}
td {{ border-bottom: 0.5pt solid {pal['deep']}44; padding: 4pt 6pt; vertical-align: top; }}
figure {{ margin: 10pt 0 14pt 0; text-align: center; }}
figure img, p img {{ max-width: 100%; max-height: 4.6in; }}
figcaption {{ font-family: "{text}"; font-size: 8.5pt; color: {pal['deep']}; margin-top: 4pt; }}
code {{ font-family: Menlo, monospace; font-size: 9pt; background: {pal['deep']}12; padding: 0 3pt; }}
pre {{ font-family: Menlo, monospace; font-size: 8.5pt; background: {pal['deep']}12; padding: 8pt; white-space: pre-wrap; }}
hr {{ border: 0; border-top: 0.75pt solid {pal['deep']}; margin: 14pt 0; }}
.wayfinding {{ font-family: "{text}"; font-size: 9.5pt; color: {pal['deep']}; margin: 0 0 10pt 0; }}
.decision-line {{ font-family: "{text}"; font-size: 10pt; margin: 0 0 4pt 0; padding-left: 12pt; border-left: 3pt solid {pal['rubric']}; }}
.decision-line + .decision-line {{ margin-top: -2pt; }}
.swatch {{ display: inline-block; width: 0.5in; height: 0.5in; vertical-align: middle; margin-right: 8pt; border: 0.5pt solid {pal['deep']}55; }}
a {{ color: {pal['accent']}; text-decoration: none; }}
"""
    document = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(church_name)} Brand Guide</title><style>{css}</style></head>
<body>{_cover(root, system, church_name, source)}
<main>{body}</main></body></html>"""
    return source, document


def render(root: Path, guide: Path, target: Path) -> dict[str, Any]:
    source, document = build_html(root, guide.read_text(encoding="utf-8"))
    try:
        from weasyprint import HTML  # noqa: WPS433
    except ImportError as exc:
        raise RuntimeError("WeasyPrint is unavailable in this runtime; run the runtime doctor") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=document, base_url=str(root)).write_pdf(str(target))
    return {"brand_source": source}
