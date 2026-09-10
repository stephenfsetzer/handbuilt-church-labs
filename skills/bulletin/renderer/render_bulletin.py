#!/usr/bin/env python3
"""
Handbuilt bulletin renderer (v2).

Generates a print-ready worship bulletin PDF from a bulletin-config.json,
a church brand file (brand.json), and the liturgy markdown files in
./liturgy/. Three template standards ship with this component:

  classic  Traditional Anglican: EB Garamond, centered small-cap heads,
           red rubrics, full order of service with music images.
  modern   Brand-forward: Source Serif 4 + Source Sans 3, left-aligned
           heads with an accent rule, full order of service with music.
  compact  Four-page order-of-service outline: prayer book page numbers
           and hymn numbers instead of full texts. Needs no music images,
           so it works before a church has built a music library.

Finished page size is US Letter. Print as a booklet on 11x17 paper:
run impose_booklet.py on the output PDF to get pre-imposed 2-up
saddle-stitch sheets, or use the sequential PDF with a copier's own
booklet mode.

Usage:
    python3 render_bulletin.py --config <bulletin-config.json> \
        --template classic|modern|compact [--brand <brand.json>] [--out <dir>]
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
LITURGY_DIR = HERE / "liturgy"
FONTS_DIR = HERE / "fonts"
THEMES_DIR = HERE / "themes"

SPEAKERS = ("Priest", "People", "Together", "Leader", "Reader", "Deacon",
            "Presider", "Celebrant", "Bishop")

NEUTRAL_BRAND = {
    "church": {
        "name": "Example Episcopal Church",
        "address": "", "website": "",
        "service_line": "Holy Eucharist, Rite II",
        "service_time": "",
    },
    "logo": {},
    "colors": {
        "ink": "#1a1a1a", "accent": "#4a5d7e", "accent_deep": "#2e3a52",
        "paper": "#ffffff", "rubric_red": "#8B3A3A",
    },
    "texts": {},
    "qr": {},
}


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def smart_quotes(s):
    s = re.sub(r'(^|[\s(\[])"', "\\1\u201c", s)
    s = s.replace('"', "\u201d")
    s = re.sub(r"(\w)'(\w)", "\\1\u2019\\2", s)
    s = re.sub(r"(^|[\s(\[])'", "\\1\u2018", s)
    s = s.replace("'", "\u2019")
    return s


def inline_md(s):
    """Escape, then convert inline bold, italics, and typographic quotes."""
    s = esc(smart_quotes(s))
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", s)
    return s


# ---------------------------------------------------------------------------
# Liturgy markdown parsing
# ---------------------------------------------------------------------------

def parse_liturgy(path):
    """Parse a liturgy .md file into a list of (kind, payload) blocks.

    Kinds: title, subtitle, rubric, speaker_mark, dialogue
    (payload {speaker, lines, bold}), prose (payload [lines]).
    """
    blocks = []
    cur = None  # open dialogue or prose block
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            cur = None
            continue
        if line.startswith("## "):
            blocks.append(("subtitle", line[3:].strip()))
            cur = None
            continue
        if line.startswith("# "):
            blocks.append(("title", line[2:].strip()))
            cur = None
            continue
        stripped = line.strip()
        # Full-line italic: a rubric, or a *Speaker* marker
        m = re.fullmatch(r"\*([^*].*?)\*", stripped)
        if m and not stripped.startswith("**"):
            inner = m.group(1).strip()
            if inner in SPEAKERS:
                blocks.append(("speaker_mark", inner))
            else:
                blocks.append(("rubric", inner))
            cur = None
            continue
        # Dialogue opener: Speaker<tabs>text  or  **Speaker<tabs>text...
        m = re.match(r"^(\*\*)?([A-Za-z]+)\t+(.*)$", line)
        if m and m.group(2) in SPEAKERS:
            bold = bool(m.group(1))
            text = m.group(3).strip()
            cur = {"speaker": m.group(2), "lines": [(None, text)], "bold": bold}
            blocks.append(("dialogue", cur))
            continue
        # Continuation of an open dialogue block (leading whitespace).
        # Extra tabs beyond the block's base indent mark BCP indent levels.
        if raw[:1] in ("\t", " ") and cur is not None and isinstance(cur, dict):
            tabs = len(raw) - len(raw.lstrip("\t"))
            cur["lines"].append((tabs, stripped))
            continue
        # Plain prose paragraph line; leading tabs mark BCP-style
        # indent levels for said-by-all poetry (the Creed)
        level = len(raw) - len(raw.lstrip("\t"))
        if cur is not None and isinstance(cur, list):
            cur.append((level, stripped))
        else:
            cur = [(level, stripped)]
            blocks.append(("prose", cur))
    return blocks


def strip_bold_markers(s):
    return s.replace("**", "")


def render_blocks(blocks, ctx):
    """Render parsed liturgy blocks to HTML. ctx allows substitutions."""
    out = []
    swallow_dialogue = False
    custom_communion_welcome_rendered = False
    previous_dialogue_speaker = None
    previous_dialogue_bold = False
    for block_index, (kind, payload) in enumerate(blocks):
        if kind == "title":
            continue  # section headers are added by the caller
        if kind == "dialogue" and swallow_dialogue:
            swallow_dialogue = False
            continue
        if kind == "subtitle":
            hook = ctx.get("subtitle_hook")
            if hook:
                replacement = hook(payload)
                if replacement is not None:
                    out.append(replacement)
                    # a music image replaces the spoken text that follows
                    swallow_dialogue = True
                    continue
            out.append(f'<h3 class="subhead">{esc(payload)}</h3>')
        elif kind == "rubric":
            text = payload
            if (ctx.get("rubric_style", "concise") == "concise"
                    and text in {"Then, facing the Holy Table, the Celebrant proceeds.", "Then, facing the Holy Table, the Celebrant proceeds"}):
                text = "The celebrant proceeds."
            if "[Proper Preface inserted here]" in text:
                preface = ctx.get("proper_preface")
                if preface:
                    out.append(f'<p class="prose">{inline_md(preface)}</p>')
                continue
            if "[Communion welcome inserted here]" in text:
                welcome = ctx.get("communion_welcome")
                if welcome:
                    files = ctx.get("liturgy_files", {})
                    staged = None
                    if isinstance(files, dict):
                        staged = files.get(welcome) or files.get("communion_welcome")
                    staged_path = LITURGY_DIR / f"{staged or welcome}.md"
                    if staged_path.is_file():
                        welcome_blocks = [
                            block for block in parse_liturgy(staged_path)
                            if block[0] != "title"
                        ]
                        welcome_ctx = dict(ctx)
                        welcome_ctx["communion_welcome_instruction"] = True
                        out.append(render_blocks(welcome_blocks, welcome_ctx))
                    else:
                        out.append(f'<p class="rubric">{inline_md(welcome)}</p>')
                    custom_communion_welcome_rendered = True
                continue
            if (custom_communion_welcome_rendered
                    and text.startswith("If you would rather not receive communion")):
                continue
            out.append(f'<p class="rubric">{inline_md(text)}</p>')
        elif kind == "speaker_mark":
            out.append(f'<p class="speaker-mark">{esc(payload)}</p>')
        elif kind == "dialogue":
            sp = payload["speaker"]
            bold = payload["bold"]
            raw_lines = payload["lines"]
            if len(raw_lines) == 1:
                body = inline_md(strip_bold_markers(raw_lines[0][1]))
            else:
                # Multi-line blocks render as BCP-style poetry: each
                # source line hangs; deeper tab levels step in.
                tab_counts = [t for t, _ in raw_lines if t is not None]
                base = min(tab_counts) if tab_counts else 0
                body = ""
                for tabs, text in raw_lines:
                    lvl = 0 if tabs is None else min(max(tabs - base, 0), 2)
                    body += (f'<p class="dlg-line lvl{lvl}">'
                             f'{inline_md(strip_bold_markers(text))}</p>')
            cls = "dialogue response" if bold else "dialogue"
            suppress_label = (
                ctx.get("prayer_presentation", "continuous") == "continuous"
                and not bold
                and sp in {"Celebrant", "Priest"}
                and sp == previous_dialogue_speaker
                and not previous_dialogue_bold
            )
            speaker = ('' if suppress_label else esc(sp))
            speaker_attr = ' aria-hidden="true"' if suppress_label else ''
            out.append(("dlg", bold,
                        f'<div class="{cls}"><span class="speaker"{speaker_attr}>{speaker}</span>'
                        f'<span class="line">{body}</span></div>'))
            previous_dialogue_speaker = sp
            previous_dialogue_bold = bold
            continue
        elif kind == "prose":
            if ctx.get("communion_welcome_instruction"):
                body = " ".join(inline_md(t) for _, t in payload)
                out.append(f'<p class="rubric">{body}</p>')
                continue
            # Fully-bold paragraphs are said by all: render them
            # line-by-line with BCP-style hanging indents (first lines
            # flush, continuations one step in, sub-clauses a second
            # step), per BCP p. 326/358 and cathedral leaflet practice.
            all_bold = all(t.strip().startswith("**") for _, t in payload)
            if all_bold:
                lines = "".join(
                    f'<p class="cong-line lvl{min(l, 2)}">{inline_md(t)}</p>'
                    for l, t in payload)
                out.append(f'<div class="congregational">{lines}</div>')
            else:
                body = " ".join(inline_md(t) for _, t in payload)
                paragraph = f'<p class="prose">{body}</p>'
                following = blocks[block_index + 1] if block_index + 1 < len(blocks) else None
                if following and following[0] == "dialogue" and following[1]["bold"]:
                    # Keep a prayer's closing sentence with its spoken response
                    # without adding a repeated Celebrant label.
                    out.append(("dlg", False, paragraph))
                else:
                    out.append(paragraph)
    return "\n".join(_pair_dialogues(out))


def _pair_dialogues(items):
    """Wrap each call (plain dialogue) with its following responses (bold
    dialogues) in a keep-together block so a page break never separates a
    call from its response."""
    result = []
    i = 0
    while i < len(items):
        item = items[i]
        if not (isinstance(item, tuple) and item[0] == "dlg"):
            result.append(item)
            i += 1
            continue
        group = [item[2]]
        j = i + 1
        while (j < len(items) and isinstance(items[j], tuple)
               and items[j][0] == "dlg" and items[j][1]):
            group.append(items[j][2])
            j += 1
        if len(group) > 1:
            result.append('<div class="dialogue-group">' + '\n'.join(group) + '</div>')
        else:
            result.append(group[0])
        i = j
    return result


# ---------------------------------------------------------------------------
# Shared HTML fragments
# ---------------------------------------------------------------------------

def keep(*parts):
    return '<div class="keep-together">\n' + "\n".join(parts) + "\n</div>"


def section_head(text):
    # The label rides in a span so themes can attach a rule that runs
    # from the label to the right margin (editorial rule-out heads).
    return (f'<h2 class="section-head">'
            f'<span class="sh-label">{esc(text)}</span></h2>')


def service_title(text):
    return f'<h1 class="service-title">{esc(text)}</h1>'


def dialogue_pair(sp1, t1, sp2, t2):
    return keep(
        f'<div class="dialogue"><span class="speaker">{esc(sp1)}</span>'
        f'<span class="line">{esc(t1)}</span></div>',
        f'<div class="dialogue response"><span class="speaker">{esc(sp2)}</span>'
        f'<span class="line">{esc(t2)}</span></div>',
    )


def liturgy_section(name, ctx, head=None):
    files = ctx.get("liturgy_files", {})
    if isinstance(files, dict):
        name = files.get(name, name)
    path = LITURGY_DIR / f"{name}.md"
    blocks = parse_liturgy(path)
    if name == "prayers-of-the-people-vi" and ctx.get("omit_form_vi_confession"):
        # The source form includes a confession. Honor an explicit omission
        # without inventing a second response pattern or altering private text.
        boundary = next(i for i, (kind, payload) in enumerate(blocks)
                        if kind == "dialogue" and payload["lines"][0][1]
                        == "We pray to you also for the forgiveness of our sins.")
        blocks = blocks[:boundary] + [("rubric", "The Celebrant adds a concluding Collect.")]
    title = head
    if title is None:
        for kind, payload in blocks:
            if kind == "title":
                title = payload
                break
    html = render_blocks(blocks, ctx)
    # Short sections (a few dialogue lines and rubrics) stay on one page
    n_content = sum(1 for k, _ in blocks if k != "title")
    if n_content <= 6 and "<img" not in html:
        return f'<div class="section keep-together">{section_head(title) if title else ""}\n{html}</div>'
    return keep_or_flow(title, html)


def configured_liturgy_file(cfg, key, legacy_key=None, migration_default=None):
    """Resolve a liturgy identifier without selecting a worship variable."""
    liturgy = cfg.get("liturgy", {})
    value = liturgy.get(key) if isinstance(liturgy, dict) else None
    if not str(value or "").strip() and legacy_key:
        value = cfg.get("options", {}).get(legacy_key)
    if not str(value or "").strip():
        value = migration_default
    if not str(value or "").strip():
        raise ValueError(f"No resolved worship choice for liturgy.{key}")
    value = str(value).strip()
    aliases = {
        ("eucharistic_prayer", "A"): "eucharistic-prayer-a",
        ("eucharistic_prayer", "A_full"): "eucharistic-prayer-a-full",
        ("eucharistic_prayer", "B"): "eucharistic-prayer-b",
        ("eucharistic_prayer", "C"): "eucharistic-prayer-c",
        ("eucharistic_prayer", "D"): "eucharistic-prayer-d",
        ("lords_prayer", "contemporary"): "lords-prayer-contemporary",
        ("prayers_of_the_people", "I"): "prayers-of-the-people-i",
        ("prayers_of_the_people", "II"): "prayers-of-the-people-ii",
        ("prayers_of_the_people", "IV"): "prayers-of-the-people-iv",
        ("prayers_of_the_people", "V"): "prayers-of-the-people-v",
        ("prayers_of_the_people", "VI"): "prayers-of-the-people-vi",
        ("lords_prayer", "traditional"): "lords-prayer-traditional",
        ("prayers_of_the_people", "III"): "prayers-of-the-people",
    }
    value = aliases.get((key, value), value)
    if Path(value).name != value or Path(value).suffix == ".md":
        value = Path(value).stem
    return value


def keep_or_flow(title, html):
    """Section header must stay with at least the start of its content."""
    return (f'<div class="section">'
            f'{section_head(title) if title else ""}\n{html}</div>')


def file_uri(p):
    return Path(p).resolve().as_uri()


# ---------------------------------------------------------------------------
# Content builders (full templates: classic, modern)
# ---------------------------------------------------------------------------

def fmt_date(datestr):
    d = datetime.strptime(datestr, "%Y-%m-%d")
    return d.strftime("%B %-d, %Y")


def cover_logo(brand, repo_root, template="classic"):
    """Use the church's available local logo, regardless of its saved shape."""
    logos = brand.get("logo") or {}
    if not isinstance(logos, dict):
        raise ValueError("Save the church logo under brand.json logo.mark or logo.banner as a local image path.")
    configured = False
    order = ("banner", "mark", "episcopal_shield") if template == "modern" else ("mark", "banner", "episcopal_shield")
    for key in order:
        raw = logos.get(key)
        if raw is None or raw == "":
            continue
        configured = True
        if not isinstance(raw, str):
            raise ValueError("The church logo must name a local image file.")
        if re.match(r"^https?://", raw, re.I):
            continue
        path = (repo_root / raw).resolve()
        # Production validates church-folder containment before staging
        # absolute paths for the renderer.
        if path.is_file():
            return path
    if configured:
        raise ValueError("A church logo is configured but no local image is available. The agent must retrieve or restore it inside the church folder and update brand.json before producing the cover.")
    return None


def cover_page(cfg, brand, repo_root, template):
    svc = cfg["service"]
    church = brand["church"]
    # Classic: the available church logo plus the church name set in type.
    # Modern: the horizontal wordmark banner.
    logo_html = ""
    if template == "classic":
        mark = cover_logo(brand, repo_root, template)
        if mark:
            logo_html = (f'<img class="cover-mark" '
                         f'src="{file_uri(mark)}" alt="Church logo">')
        name = church.get("public_name") or church.get("name", "")
        logo_html += f'<p class="cover-church-name">{esc(smart_quotes(name))}</p>'
    else:
        logo = cover_logo(brand, repo_root, template)
        if logo:
            banner = (brand.get("logo") or {}).get("banner")
            uses_banner = isinstance(banner, str) and banner and (repo_root / banner).resolve() == logo
            logo_class = "cover-logo" if uses_banner else "cover-logo cover-logo-mark"
            logo_html = (f'<img class="{logo_class}" '
                         f'src="{file_uri(logo)}" alt="Church logo">')
            if not uses_banner:
                name = church.get("public_name") or church.get("name", "")
                logo_html += f'<p class="cover-church-name">{esc(smart_quotes(name))}</p>'
        else:
            name = church.get("public_name") or church.get("name", "")
            logo_html = f'<p class="cover-church-name">{esc(smart_quotes(name))}</p>'
    occasion = svc["occasion"]
    proper = svc.get("proper", "")
    date_line = fmt_date(svc["date"])
    time = svc.get("time", church.get("service_time", ""))
    if time:
        # service_time reads like "Sundays at 11:00 am"; keep just the time
        m = re.search(r"(\d[\d:]*\s*[ap]m)", time)
        date_line += f" &middot; {esc(m.group(1) if m else str(time))}"
    addr = church.get("address", "")
    site = church.get("website", "")
    color = svc.get("liturgical_color", "")
    service_line = resolved_service_display(cfg, church)
    return f"""
<div class="cover">
  {logo_html}
  <div class="cover-middle">
    <p class="cover-kicker">{esc(service_line)}</p>
    <h1 class="cover-occasion">{esc(occasion)}</h1>
    {f'<p class="cover-proper">{esc(proper)}</p>' if proper else ''}
    <p class="cover-date">{date_line}</p>
  </div>
  <div class="cover-foot">
    <p>{esc(addr)}</p>
    <p>{esc(site)}</p>
  </div>
</div>
"""


def resolved_service_display(cfg, church):
    """Return resolved service display data without changing standing brand data."""
    service = cfg.get("service", {}) or {}
    liturgy = cfg.get("liturgy", {}) or {}
    variant = liturgy.get("service_variant") if isinstance(liturgy, dict) else None
    variant_name = (variant.get("name") if isinstance(variant, dict)
                    and variant.get("id") != "none" else None)
    plan_name = {"episcopal-rite-ii": "Holy Eucharist, Rite II",
                 "lutheran-holy-communion": "Holy Communion"}.get(
                     liturgy.get("service_plan") if isinstance(liturgy, dict) else None)
    return (service.get("display_name")
            or variant_name
            or service.get("service_line")
            or church.get("service_line") or plan_name or "Holy Eucharist")


def trim_whitespace(path):
    """Crop large white borders off a music scan (parish scans often carry
    a full page of margin). Returns a cached cropped copy, or the original
    path if the borders are already tight. Preserves DPI metadata."""
    from PIL import Image
    with Image.open(path) as im:
        dpi = (im.info.get("dpi") or (96, 96))
        gray = im.convert("L")
        bw = gray.point(lambda x: 0 if x > 242 else 255)
        bbox = bw.getbbox()
        if not bbox:
            return path
        area_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / (im.width * im.height)
        if area_ratio > 0.90:
            return path
        pad = int(0.015 * im.width)
        box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
               min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad))
        cache_dir = path.parent / ".render-cache"
        cache_dir.mkdir(exist_ok=True)
        out = cache_dir / f"{path.stem}-trim{path.suffix}"
        if not out.exists():
            im.crop(box).save(out, dpi=(dpi[0], dpi[1]))
        return out


def sized_img(path, cls, content_w=7.3, max_h=8.2, max_upscale=1.25):
    """Emit an <img> with explicit dimensions computed from the file's
    pixel size and DPI metadata, so mixed-DPI music scans render at a
    consistent, undistorted size."""
    try:
        path = trim_whitespace(path)
        from PIL import Image
        with Image.open(path) as im:
            dpi = (im.info.get("dpi") or (96, 96))[0] or 96
            w_in, h_in = im.width / dpi, im.height / dpi
    except Exception:
        return f'<img class="{cls}" src="{path.as_uri()}" alt="">'
    scale = min(content_w / w_in, max_h / h_in, max_upscale)
    return (f'<img class="{cls}" src="{path.as_uri()}" alt="" '
            f'style="width:{w_in * scale:.2f}in; height:{h_in * scale:.2f}in;">')


def hymn_block(label, hymn, config_dir, full_page=True, max_h=None, content_w=None, lead_in=""):
    if not hymn:
        return ""
    num = hymn.get("number")
    title = hymn.get("title", "")
    tune = hymn.get("tune")
    composer = hymn.get("composer")
    lyrics = hymn.get("lyrics") or []
    if label and num:
        head = f"{label} &middot; Hymn {num}"
    else:
        head = label or (f"Hymn {num}" if num else "")
    sub = esc(title) + (f' <span class="tune">({esc(tune)})</span>' if tune else "")
    imgs = hymn.get("images") or ([hymn["image"]] if hymn.get("image") else [])
    if max_h is None:
        max_h = 8.2 if full_page else 5.2
    systems = []
    for img in imgs:
        p = (config_dir / img).resolve()
        if p.exists():
            # Inline music sits inside the modern theme's left-rail section,
            # so its usable width is the text column, not the full page.
            image_w = content_w if content_w is not None else (5.75 if not full_page else 7.3)
            systems.append(sized_img(p, "hymn-img", content_w=image_w, max_h=max_h))
    if hymn.get("custom_text"):
        systems.append(f'<p class="rubric">{esc(hymn["custom_text"])}</p>')
    lyrics_html = lyrics_block(lyrics, hymn.get("lyric_columns")) if lyrics else ""
    cls = "hymn-page" if full_page else "hymn-inline"
    head_html = (f'<h2 class="hymn-head"><span class="sh-label">{head}</span></h2>'
                 if head else "")
    composer_html = (f'<p class="hymn-composer">Composer: {esc(str(composer))}</p>'
                     if str(composer or "").strip() else "")
    header = lead_in + head_html + f'<p class="hymn-title">{sub}</p>' + composer_html
    # Keep any caller-supplied lead-in (a subtitle and rubric, say) with the
    # heading and only the first system, all as one unit. A long piece's
    # later systems then flow across pages on their own, instead of the
    # whole piece being forced onto a fresh page as one unbreakable block
    # and stranding the page before it near-empty.
    first_system, later_systems = (systems[0], systems[1:]) if systems else ("", [])
    return (f'<div class="{cls}">'
            + keep(header, first_system)
            + "\n".join(later_systems)
            + lyrics_html
            + "</div>")


def normalize_lyric_group(group):
    """Accept both Labs speaker/bold and compatible part/people lyric shapes."""
    if not isinstance(group, dict):
        return {"label": "", "lines": [str(group)], "bold": False}
    lines = group.get("lines") or []
    if isinstance(lines, str):
        lines = lines.splitlines()
    return {
        "label": str(group.get("speaker") or group.get("part") or ""),
        "lines": [str(line) for line in lines],
        "bold": bool(group.get("bold") or group.get("people")),
    }


def lyrics_block(groups, lyric_columns=None):
    """Render licensed lyric-only music as structured bulletin text."""
    rendered = []
    for group in groups:
        normalized = normalize_lyric_group(group)
        speaker = esc(normalized["label"])
        lines = normalized["lines"]
        bold = normalized["bold"]
        line_html = "".join(
            f'<p class="lyrics-line">{inline_md(str(line))}</p>'
            for line in lines
        )
        cls = "lyrics-group response" if bold else "lyrics-group"
        rendered.append(
            f'<div class="{cls}">'
            f'<span class="lyrics-speaker">{speaker}</span>'
            f'<div class="lyrics-lines">{line_html}</div>'
            f'</div>'
        )
    columns = " lyrics-2col" if lyric_columns == 2 else ""
    return f'<div class="lyrics{columns}">' + "\n".join(rendered) + '</div>'


def _reading_paragraphs(reading):
    """Return shaped reading paragraphs, with legacy text as a fallback."""
    if "paragraphs" in reading and isinstance(reading.get("paragraphs"), list):
        return [str(paragraph).strip() for paragraph in reading["paragraphs"]
                if str(paragraph).strip()]
    text = str(reading.get("text", ""))
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def _reading_body(reading):
    paragraphs = _reading_paragraphs(reading)
    if reading.get("format") != "poetry":
        return "\n".join(
            f'<p class="reading-text">{inline_md(paragraph)}</p>'
            for paragraph in paragraphs
        )
    rendered = []
    for paragraph in paragraphs:
        lines = paragraph.splitlines() or [paragraph]
        line_html = "<br>\n".join(inline_md(line) for line in lines)
        rendered.append(f'<p class="reading-text reading-poetry">{line_html}</p>')
    return "\n".join(rendered)


def _psalm_legacy_verses(psalm):
    verses = []
    for raw in str(psalm.get("text", "")).split("\n\n"):
        raw = raw.strip()
        if not raw:
            continue
        match = re.match(r"^(\d+)\s+(.*)$", raw, re.S)
        number, body = (match.group(1), match.group(2)) if match else ("", raw)
        if " * " in body:
            first, second = body.split(" * ", 1)
            verses.append({"number": number, "first": first + " *", "second": second})
        else:
            verses.append({"number": number, "first": body, "second": ""})
    return verses


def _psalm_verses(psalm, mode):
    """Normalize explicit shaped verses without guessing a half-verse split."""
    shaped = psalm.get("verses")
    if isinstance(shaped, list):
        verses = []
        for item in shaped:
            if not isinstance(item, dict):
                continue
            number = str(item.get("number", ""))
            if mode == "responsive_half_verse":
                verses.append({"number": number, "first": str(item.get("first", "")),
                               "second": str(item.get("second", ""))})
            else:
                verses.append({"number": number, "text": str(item.get("text", ""))})
        return verses
    if mode == "responsive_half_verse":
        return _psalm_legacy_verses(psalm)
    verses = []
    for raw in str(psalm.get("text", "")).split("\n\n"):
        raw = raw.strip()
        if not raw:
            continue
        match = re.match(r"^(\d+)\s+(.*)$", raw, re.S)
        number, body = (match.group(1), match.group(2)) if match else ("", raw)
        verses.append({"number": number, "text": body})
    return verses


def _bold_psalm_response(text):
    clean = strip_bold_markers(str(text)).strip()
    return f"<strong>{inline_md(clean)}</strong>"


def psalm_block(psalm):
    num = psalm.get("number", "")
    latin = psalm.get("latin_title", "")
    explicit_mode = psalm.get("format")
    mode = explicit_mode or "responsive_half_verse"
    if mode not in {"responsive_half_verse", "responsive_whole_verse", "unison", "plain"}:
        mode = "responsive_half_verse"
    verses = _psalm_verses(psalm, mode)
    rows = []
    for index, verse in enumerate(verses):
        vnum = esc(str(verse.get("number", "")))
        if mode == "responsive_half_verse":
            first_text = str(verse.get("first", ""))
            first = inline_md(strip_bold_markers(first_text) if explicit_mode else first_text)
            second = verse.get("second", "")
            row = (f'<p class="psalm-verse"><span class="vnum">{vnum}</span>{first}</p>')
            if second:
                row += f'<p class="psalm-response">{_bold_psalm_response(second)}</p>'
        else:
            text = strip_bold_markers(str(verse.get("text", "")))
            response = mode == "unison" or (
                mode == "responsive_whole_verse"
                and index % 2 == (0 if psalm.get("response_start") == "first" else 1)
            )
            body = (_bold_psalm_response(text) if response else inline_md(text))
            cls = "psalm-response psalm-whole-verse" if response else "psalm-verse"
            row = f'<p class="{cls}"><span class="vnum">{vnum}</span>{body}</p>'
        rows.append(keep(row))
    rubric = {
        "responsive_half_verse": "Read responsively; the congregation reads the words in bold.",
        "responsive_whole_verse": "Read responsively; the congregation reads the bold verses.",
        "unison": "Read together.",
        "plain": "Read aloud.",
    }[mode]
    latin_html = f' <span class="tune">({esc(latin)})</span>' if latin else ""
    return (f'<div class="section">'
            + section_head("The Psalm")
            + f'<p class="citation">Psalm {esc(str(num))}{latin_html}</p>'
            + f'<p class="rubric">{rubric}</p>'
            + "\n".join(rows) + "</div>")


def reading_block(label, reading, response=("Reader", "The Word of the Lord.",
                                            "People", "Thanks be to God.")):
    citation = reading.get("citation", "")
    body = _reading_body(reading)
    return (f'<div class="section">'
            + keep(section_head(label),
                   f'<p class="citation">{esc(citation)}</p>')
            + body
            + dialogue_pair(*response)
            + "</div>")


GOSPEL_ACCLAMATIONS = ("lord", "savior")


def gospel_acclamation_choice(cfg):
    """Resolve the saved wording for the Gospel announcement dialogue.

    Sources vary on an actual, verified point of wording: the standard BCP
    text reads "our Lord Jesus Christ"; some parishes' printed bulletins
    read "our Savior Jesus Christ" instead. This is source fidelity, not
    cosmetic rewording, so it is a saved choice, not a hardcoded default
    silently applied to every church. ``lord`` is the standard BCP default
    used when no local choice is supplied; any other or missing value keeps
    that default rather than guessing.
    """
    liturgy = cfg.get("liturgy")
    value = str(liturgy.get("gospel_acclamation", "")).strip().lower() if isinstance(liturgy, dict) else ""
    return value if value in GOSPEL_ACCLAMATIONS else "lord"


def gospel_block(reading, acclamation="lord"):
    citation = reading.get("citation", "")
    book = citation.split()[0] if citation else "the Gospel"
    title = "Savior" if acclamation == "savior" else "Lord"
    body = _reading_body(reading)
    return (f'<div class="section">'
            + keep(section_head("The Holy Gospel"),
                   f'<p class="citation">{esc(citation)}</p>',
                   dialogue_pair("Priest",
                                 f"The Holy Gospel of our {title} Jesus Christ according to {book}.",
                                 "People", "Glory to you, Lord Christ."))
            + body
            + dialogue_pair("Priest", "The Gospel of the Lord.",
                            "People", "Praise to you, Lord Christ.")
            + "</div>")


QR_COPY = {
    "heading": "Connect and Give",
    "connect_head": "Connect with us",
    "give_head": "Support our ministry",
    "connect_body": "",
    "give_body": "",
}


def _qr_copy(brand):
    """Resolve accepted standard copy or complete church-supplied copy."""
    qr = brand.get("qr", {}) or {}
    custom = qr.get("copy", {}) if isinstance(qr.get("copy", {}), dict) else {}
    configured = [key for key in ("connect", "give") if _qr_asset(qr.get(key))[0]]
    if not configured:
        return None
    if qr.get("standard_copy_accepted") is True:
        # Onboarding scaffolds every copy field as an empty string. Empty
        # scaffold values must not erase the standard copy the church accepted.
        supplied = {
            key: value
            for key, value in custom.items()
            if key in QR_COPY and str(value).strip()
        }
        return {**QR_COPY, **supplied}
    required = {"heading"}
    for key in configured:
        required.add(f"{key}_head")
    if not required.issubset(custom) or any(not str(custom[key]).strip() for key in required):
        return None
    return {**QR_COPY, **{k: custom[k] for k in custom if k in QR_COPY}}


def _qr_asset(value):
    """Normalize a legacy image path or an image and URL QR object."""
    if isinstance(value, str):
        return value, ""
    if isinstance(value, dict):
        return value.get("image", ""), value.get("url", "")
    return "", ""


def qr_block(brand, repo_root):
    """Render only QR assets that exist, with accepted or custom copy."""
    qr = brand.get("qr", {}) or {}
    copy = _qr_copy(brand)
    if copy is None:
        return ""
    cells = []
    for key in ("connect", "give"):
        image, _url = _qr_asset(qr.get(key))
        if not image:
            continue
        path = Path(image)
        if not path.is_absolute():
            path = repo_root / path
        if not path.exists():
            continue
        body = str(copy.get(key + "_body", "") or "").strip()
        cells.append(
            f'<div class="cg-half qr-cell">'
            f'<img class="cg-qr qr-img" src="{file_uri(path)}" alt="">'
            f'<p class="cg-head qr-title">{esc(str(copy[key + "_head"]))}</p>'
            + (f'<p class="cg-body qr-note">{esc(body)}</p>' if body else "")
            + '</div>')
    if not cells:
        return ""
    return (f'<div class="section connect-give">'
            + keep(section_head(str(copy["heading"]))
                   + '<div class="cg-rule"></div>'
                   + '<div class="cg-grid">' + "".join(cells) + "</div>")
            + "</div>")


def _person_name(entry):
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("person") or "").strip()
    return ""


def _person_role(entry, default=""):
    if isinstance(entry, dict):
        return str(entry.get("role") or entry.get("title") or default).strip()
    return default


def _person_entries(value, default_role=""):
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [(_person_role(entry, default_role), _person_name(entry))
            for entry in value if _person_name(entry)]


def bulletin_footer(brand):
    """Resolve the explicit bulletin footer, with legacy church fallbacks."""
    church = brand.get("church", {}) or {}
    footer = brand.get("bulletin_footer", {}) or {}
    fallbacks = {
        "contact_name": church.get("name", ""),
        "address": church.get("address", ""),
        "phone": church.get("phone", ""),
        "email": church.get("email", ""),
        "website": church.get("website", ""),
    }
    return {key: (footer[key] if key in footer else value)
            for key, value in fallbacks.items()}


def footer_line(brand, escaped=False):
    values = bulletin_footer(brand)
    bits = [values[key] for key in ("contact_name", "address", "phone", "email", "website")
            if str(values[key] or "").strip()]
    return "  &middot;  ".join(esc(str(bit)) if escaped else str(bit) for bit in bits)


def leadership_roster(brand):
    """Return normalized leadership rows and the names they contain."""
    lead = brand.get("leadership", {}) or {}
    body = lead.get("governing_body", {}) or {}
    staff = _person_entries(lead.get("clergy_and_staff", lead.get("clergy_staff", [])))
    officers = _person_entries(body.get("officers", lead.get("governing_officers", [])))
    members = _person_entries(body.get("members", []), body.get("member_label", ""))
    seen = set()
    deduped_staff = []
    deduped_governing = []
    for target, entries in ((deduped_staff, staff),
                            (deduped_governing, officers + members)):
        for role, name in entries:
            key = name.casefold()
            if key not in seen:
                target.append((role, name))
                seen.add(key)
    return (deduped_staff, deduped_governing, seen,
            str(body.get("label") or "").strip())


def roster_names(brand):
    return leadership_roster(brand)[2]


def _leadership_rows(entries, per_row=3):
    out = []
    for i in range(0, len(entries), per_row):
        chunk = entries[i:i + per_row]
        name_cells = "".join(f'<td class="lead-name">{esc(name)}</td>'
                             for _role, name in chunk)
        role_cells = "".join(f'<td class="lead-role">{esc(role)}</td>'
                             for role, _name in chunk)
        pad = per_row - len(chunk)
        out.append(
            f'<table class="lead-row"><tr>{name_cells}'
            f'{"<td></td>" * pad}</tr><tr>{role_cells}'
            f'{"<td></td>" * pad}</tr></table>')
    return "".join(out)


def _leadership_groups(staff, governing, governing_label):
    groups = ""
    if staff:
        groups += f'<div class="lead-group">{_leadership_rows(staff)}</div>'
    if governing:
        groups += '<div class="lead-group">'
        if governing_label:
            groups += f'<p class="lead-group-label">{esc(governing_label)}</p>'
        groups += _leadership_rows(governing) + '</div>'
    return groups


def leadership_block(brand):
    """Render a church-neutral name-over-role leadership roster in the running footer.

    Renders only when the roster's resolved placement is ``footer`` (the
    default when a staged brand carries no placement, for legacy callers).
    A roster placed in the body directory instead is not duplicated here.
    """
    lead = brand.get("leadership", {}) or {}
    if lead.get("print_in_bulletin") is not True:
        return ""
    if lead.get("placement", "footer") != "footer":
        return ""
    staff, governing, _names, governing_label = leadership_roster(brand)
    if not (staff or governing):
        return ""
    groups = _leadership_groups(staff, governing, governing_label)
    return (f'<div class="section leadership-section">'
            f'{section_head("Parish Leadership")}<div class="leadership">'
            f'{groups}</div></div>')


def leadership_directory_block(brand):
    """Render the full leadership roster as a normal readable body section.

    Used when the resolved placement is ``body``: either the church asked
    for a directory explicitly, or the roster is too large for the running
    footer's fixed capacity. All names are retained, not truncated.
    """
    lead = brand.get("leadership", {}) or {}
    if lead.get("print_in_bulletin") is not True:
        return ""
    if lead.get("placement", "footer") != "body":
        return ""
    staff, governing, _names, governing_label = leadership_roster(brand)
    if not (staff or governing):
        return ""
    groups = _leadership_groups(staff, governing, governing_label)
    return (f'<div class="section leadership-directory">'
            f'{section_head("Parish Directory")}<div class="leadership">'
            f'{groups}</div></div>')


def parish_information_block(cfg, scope):
    """Render the church's standing parish-information sections for one
    placement, distinct from dated announcements.

    Simple ordered title-and-text sections: a recurring welcome,
    accessibility note, pastoral contact, or worship-book explanation.
    Reuses the same paragraph splitting and inline escaping as a reading or
    the collect of the day; no raw HTML, and no page-layout engine.
    """
    sections = (cfg.get("parish_information") or {}).get(scope)
    if not isinstance(sections, list) or not sections:
        return ""
    parts = []
    for entry in sections:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        paragraphs = "\n".join(
            f'<p class="prose">{inline_md(paragraph.strip())}</p>'
            for paragraph in re.split(r"\n\s*\n", text)
            if paragraph.strip()
        )
        head = section_head(title) if title else ""
        parts.append(f'<div class="section parish-info">{head}{paragraphs}</div>')
    return "".join(parts)


def _announcement_image_markup(entry, repo_root):
    """A supplied event poster or inline QR graphic attached to one
    announcement. Preserves aspect ratio, fits the printable width, and is
    never forced into the same unbreakable block as its title/text, so a
    near-full-page poster can flow to its own page instead of being cropped
    or squeezed. No raw HTML, no remote fetch, no generic layout builder."""
    images = entry.get("images") or ([entry["image"]] if entry.get("image") else [])
    parts = []
    for img in images:
        path = (repo_root / str(img)).resolve()
        if path.exists():
            parts.append(sized_img(path, "announcement-img", content_w=7.3, max_h=9.2))
    if not parts:
        return ""
    caption = str(entry.get("caption", "")).strip()
    if caption:
        parts.append(f'<p class="rubric">{inline_md(caption)}</p>')
    return "\n".join(parts)


def announcements_block(cfg, brand, repo_root, include_qr=False):
    items = cfg.get("announcements", [])
    lis_parts = []
    for a in items:
        title = f'<p class="ann-title">{inline_md(a["title"])}</p>' if str(a.get("title", "")).strip() else ""
        text = str(a.get("text", "")).strip()
        text_html = f'<p class="ann-text">{inline_md(text)}</p>' if text else ""
        images_html = _announcement_image_markup(a, repo_root)
        lis_parts.append(
            f'<div class="announcement"><div class="keep-together">{title}{text_html}</div>{images_html}</div>'
        )
    lis = "\n".join(lis_parts)
    svc = cfg["service"]
    options = cfg.get("options", {}) or {}
    serving_enabled = options.get("include_serving_today", True)
    allowed_roles = options.get("serving_roles") or []
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_roles = {str(role).casefold() for role in allowed_roles}

    def role_allowed(role):
        return not allowed_roles or role.casefold() in allowed_roles

    people = []
    if serving_enabled:
        if svc.get("celebrant") and role_allowed("Celebrant"):
            people.append(("Celebrant", svc["celebrant"]))
        if svc.get("preacher") and role_allowed("Preacher"):
            people.append(("Preacher", svc["preacher"]))
        serving = svc.get("serving", [])
        if isinstance(serving, dict):
            serving = [serving]
        if isinstance(serving, list):
            people.extend((_person_role(entry), _person_name(entry))
                          for entry in serving if _person_name(entry)
                          and role_allowed(_person_role(entry)))
        known = roster_names(brand)
        deduped = []
        seen = set()
        for role, name in people:
            key = name.casefold()
            if key not in known and key not in seen:
                deduped.append((role, name))
                seen.add(key)
        people = deduped
    ppl = "\n".join(f'<div class="dialogue"><span class="speaker">{esc(r)}</span>'
                    f'<span class="line">{esc(n)}</span></div>' for r, n in people)
    # Church name, address, and website render as a true page footer on
    # the back page (the @page back margin box), not as flowed content.
    # Each block is its own .section so rail-style themes can hang the
    # label beside it.
    sections = []
    if items:
        sections.append(f'<div class="section">{section_head("Announcements")}{lis}</div>')
    if ppl:
        sections.append(f'<div class="section">{keep(section_head("Serving Today"), ppl)}</div>')
    if include_qr:
        sections.append(qr_block(brand, repo_root))
    after_service = parish_information_block(cfg, "after_service")
    if after_service:
        sections.append(after_service)
    directory = leadership_directory_block(brand)
    if directory:
        sections.append(directory)
    roster = leadership_block(brand)
    footline = footer_line(brand, escaped=True)
    roster = (f'<div class="bp-running">{roster}'
              f'<p class="parish-footline">{footline}</p></div>')
    return '<div class="backpage">' + ''.join(sections) + roster + '</div>'


def _backpage_inner(markup):
    prefix = '<div class="backpage">'
    suffix = '</div>'
    if markup.startswith(prefix) and markup.endswith(suffix):
        return markup[len(prefix):-len(suffix)]
    return markup


CLOSING_HYMN_POSITIONS = ("before_dismissal", "after_dismissal")


def closing_hymn_position(cfg):
    """Resolve where the closing hymn prints relative to the spoken dismissal.

    ``after_dismissal`` is the documented, long-standing default: the hymn
    follows the dismissal words. A church may choose ``before_dismissal``
    instead. Any other or missing value keeps the default rather than
    guessing at the church's intent.
    """
    liturgy = cfg.get("liturgy")
    value = str(liturgy.get("closing_hymn_position", "")).strip() if isinstance(liturgy, dict) else ""
    return value if value in CLOSING_HYMN_POSITIONS else "after_dismissal"


def can_merge_back_page(cfg, closing_hymn, back_markup):
    """Permit a back-page merge only for safe closing content and no top matter."""
    if not (cfg.get("options", {}) or {}).get("merge_back_page", False):
        return False
    if not closing_hymn:
        return False
    images = closing_hymn.get("images") or (
        [closing_hymn["image"]] if closing_hymn.get("image") else [])
    has_printed_lyrics = bool(closing_hymn.get("lyrics"))
    title_only = not images and not has_printed_lyrics
    if not (has_printed_lyrics or title_only):
        return False
    top = _backpage_inner(back_markup)
    running_at = top.find('<div class="bp-running">')
    if running_at >= 0:
        top = top[:running_at]
    return not top.strip()


def _variant_unit(value):
    """Resolve a variant unit reference to a staged liturgy identifier."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("unit") or value.get("file") or value.get("id") or "").strip()
    return ""


EPISCOPAL_VARIANT_ANCHORS = frozenset({
    "opening-acclamation", "collect-for-purity", "collect-of-day", "nicene-creed",
    "prayers-of-the-people", "confession-of-sin", "peace", "doxology",
    "eucharistic-prayer", "lords-prayer", "breaking-of-bread",
    "post-communion-prayer", "dismissal",
})
LUTHERAN_VARIANT_ANCHORS = frozenset({
    "gathering", "word", "creed", "prayers", "peace", "meal",
    "communion", "sending",
})


def resolved_service_plan(cfg):
    """Require the worship resolver's plan and reject variant drift."""
    liturgy = cfg.get("liturgy", {}) or {}
    if not isinstance(liturgy, dict) or not liturgy.get("service_plan"):
        raise ValueError("liturgy.service_plan must be resolved before rendering")
    plan = str(liturgy["service_plan"])
    if plan not in {"episcopal-rite-ii", "lutheran-holy-communion"}:
        raise ValueError(f"unsupported resolved service plan: {plan}")
    variant = liturgy.get("service_variant")
    if isinstance(variant, dict) and variant.get("base_service_plan") \
            and variant["base_service_plan"] != plan:
        raise ValueError("service_variant.base_service_plan does not match liturgy.service_plan")
    return plan


def service_variant_order(cfg, service_plan=None):
    """Normalize the fully resolved weekly service variant contract.

    Variants are data in the private church input. The renderer only applies
    their stable logical unit operations after the worship resolver has
    selected the base service plan and staged its liturgy files.
    """
    liturgy = cfg.get("liturgy", {}) or {}
    service_plan = service_plan or resolved_service_plan(cfg)
    variant = liturgy.get("service_variant") if isinstance(liturgy, dict) else None
    if not isinstance(variant, dict):
        return {"id": None, "name": None, "base_service_plan": None,
                "replace": {}, "insert": {}}
    replace = {}
    for item in variant.get("replace", []) or []:
        if not isinstance(item, dict):
            continue
        unit = _variant_unit(item.get("unit"))
        replacement = item.get("with")
        if isinstance(replacement, list):
            values = [_variant_unit(value) for value in replacement]
        else:
            values = [_variant_unit(replacement)]
        if unit:
            replace[unit] = [value for value in values if value]
    insert = {}
    for item in variant.get("insert", []) or []:
        if not isinstance(item, dict):
            continue
        after = _variant_unit(item.get("after"))
        values = item.get("units", []) or []
        if not isinstance(values, list):
            values = [values]
        if after:
            insert.setdefault(after, []).extend(
                value for value in (_variant_unit(v) for v in values) if value)
    anchors = (LUTHERAN_VARIANT_ANCHORS if service_plan == "lutheran-holy-communion"
               else EPISCOPAL_VARIANT_ANCHORS)
    unknown = ((set(replace) | set(insert)) - anchors)
    if unknown:
        raise ValueError(
            f"service variant contains unknown {service_plan} anchor(s): "
            + ", ".join(sorted(unknown)))
    return {
        "id": variant.get("id"),
        "name": variant.get("name"),
        "base_service_plan": variant.get("base_service_plan"),
        "replace": replace,
        "insert": insert,
    }


def liturgy_steps(order, unit, ctx, renderer=None, default_unit=None, **kwargs):
    """Render one stable logical unit plus variant replacements and inserts."""
    render = renderer or liturgy_section
    replacement = order.get("replace", {}).get(unit, [default_unit or unit])
    out = []
    for index, identifier in enumerate(replacement):
        render_kwargs = kwargs if index == 0 else {}
        out.append(render(identifier, ctx, **render_kwargs))
    for identifier in order.get("insert", {}).get(unit, []):
        out.append(render(identifier, ctx))
    return "".join(out)


def doxology_block(cfg, ctx, order, config_dir):
    """Render the selected doxology or its configured service music."""
    liturgy = cfg.get("liturgy", {}) or {}
    mode = liturgy.get("doxology", "traditional")
    if mode == "omit":
        return ""
    music = cfg.get("service_music", {}) or {}
    if music.get("doxology"):
        return hymn_block("Doxology", music["doxology"], config_dir)
    if mode == "traditional":
        # A custom staged source applies only to the explicit custom mode.
        traditional_ctx = dict(ctx)
        files = dict(ctx.get("liturgy_files", {}) or {})
        files.pop("doxology", None)
        traditional_ctx["liturgy_files"] = files
        return liturgy_steps(order, "doxology", traditional_ctx)
    return liturgy_steps(order, "doxology", ctx)


def blessing_block(cfg, brand, ctx):
    """Render an explicitly resolved blessing, including staged Markdown ids."""
    liturgy = cfg.get("liturgy", {}) or {}
    if not isinstance(liturgy, dict):
        liturgy = {}
    value = liturgy.get("blessing") if isinstance(liturgy, dict) else None
    if value == "omit":
        return ""
    files = liturgy.get("files") if isinstance(liturgy.get("files"), dict) else {}
    shipped = LITURGY_DIR / f"{value}.md" if value else None
    if value and (value in files or (shipped is not None and shipped.is_file())):
        return liturgy_section(value, ctx, head="The Blessing")
    if not value:
        return ""
    return ('<div class="section">' + section_head("The Blessing")
            + f'<p class="prose">{inline_md(str(value))}</p>'
            + '<div class="dialogue response"><span class="speaker">Together</span>'
              '<span class="line">Amen.</span></div></div>')


def build_full_content(cfg, brand, repo_root, config_dir, template):
    liturgy_config = cfg.get("liturgy", {}) or {}
    service_plan = resolved_service_plan(cfg)
    variant = service_variant_order(cfg, service_plan)
    if service_plan == "lutheran-holy-communion":
        return build_lutheran_content(cfg, brand, repo_root, config_dir, template)

    svc = cfg["service"]
    hymns = cfg.get("hymns", {})
    music = cfg.get("service_music") or {}
    opts = cfg.get("options", {})
    liturgy = cfg.get("liturgy", {})
    if not isinstance(liturgy, dict):
        liturgy = {}
    ctx = {
        "proper_preface": cfg.get("proper_preface"),
        "communion_welcome": liturgy.get("communion_welcome") or brand.get("texts", {}).get("communion_welcome"),
        "liturgy_files": liturgy.get("files", {}),
        "prayer_presentation": liturgy.get("prayer_presentation", "continuous"),
        "rubric_style": liturgy.get("rubric_style", "concise"),
    }

    def sanctus_hook(subtitle):
        # Congregational music must be legible: the Sanctus gets near
        # full-page treatment even when that forces a page break. The short
        # heading and rubric join hymn_block's own first-system keep-together
        # as one unit, so the heading and the actual first music system land
        # on the same page; a long setting's later systems still flow,
        # rather than the whole thing being forced onto a fresh page (or the
        # heading being stranded ahead of the system that belongs with it).
        if subtitle.strip().lower() == "the sanctus" and music.get("sanctus"):
            return hymn_block("", music["sanctus"], config_dir,
                              full_page=False, max_h=7.5,
                              content_w=5.7 if template == "modern" else None,
                              lead_in='<h3 class="subhead">The Sanctus</h3>'
                                      '<p class="rubric">Sung by all.</p>')
        return None

    ep_ctx = dict(ctx)
    ep_ctx["subtitle_hook"] = sanctus_hook

    def render_collect(identifier, render_ctx, **kwargs):
        if identifier == "collect-of-day":
            return ('<div class="section">' + section_head("The Collect of the Day")
                    + dialogue_pair("Priest", "The Lord be with you.",
                                    "People", "And also with you.")
                    + '<div class="dialogue"><span class="speaker">Priest</span>'
                      '<span class="line">Let us pray.</span></div>'
                    + f'<p class="prose">{inline_md(cfg.get("collect_of_day", ""))}</p></div>')
        return liturgy_section(identifier, render_ctx, **kwargs)

    parts = [cover_page(cfg, brand, repo_root, template), parish_information_block(cfg, "before_service")]

    parts.append(hymn_block("Prelude", music.get("prelude"), config_dir))
    parts.append(hymn_block("Entrance Hymn", hymns.get("entrance"), config_dir))
    parts.append(service_title("The Word of God"))
    parts.append(liturgy_steps(variant, "opening-acclamation", ctx))
    parts.append(liturgy_steps(variant, "collect-for-purity", ctx))
    parts.append(hymn_block("Gloria", music.get("gloria"), config_dir))
    parts.append(liturgy_steps(variant, "collect-of-day", ctx,
                               renderer=render_collect, default_unit="collect-of-day"))

    readings = cfg.get("readings", {})
    include_first = liturgy.get("include_first_reading", True)
    include_second = liturgy.get("include_second_reading", True)
    if include_first and readings.get("first"):
        parts.append(reading_block("The Reading" if not include_second else "The First Reading", readings["first"]))
    if not include_first and include_second and readings.get("second"):
        parts.append(reading_block("The Reading", readings["second"]))
    parts.append(hymn_block("Psalm Antiphon", music.get("psalm_antiphon"), config_dir,
                            full_page=False))
    if readings.get("psalm"):
        parts.append(psalm_block(readings["psalm"]))
    if include_first and include_second and readings.get("second"):
        parts.append(reading_block("The Second Reading", readings["second"]))
    parts.append(hymn_block("Gradual Hymn", hymns.get("gradual"), config_dir))
    parts.append(hymn_block("Gospel Acclamation", hymns.get("gospel_acclamation"), config_dir))
    if readings.get("gospel"):
        parts.append(gospel_block(readings["gospel"], gospel_acclamation_choice(cfg)))

    preacher = svc.get("preacher", "")
    parts.append('<div class="section">'
                 + keep(section_head("The Sermon"),
                        f'<p class="service-person center">{esc(preacher)}</p>')
                 + '</div>')

    if liturgy.get("include_creed", opts.get("include_creed", True)):
        parts.append(liturgy_steps(variant, "nicene-creed", ctx))
    prayers_file = configured_liturgy_file(cfg, "prayers_of_the_people", "prayers_of_the_people")
    include_confession = liturgy.get("include_confession", opts.get("include_confession", True))
    standard_form_vi = (
        prayers_file == "prayers-of-the-people-vi"
        and not ctx["liturgy_files"].get(prayers_file)
        and "prayers-of-the-people" not in variant.get("replace", {})
    )
    ctx["omit_form_vi_confession"] = standard_form_vi and not include_confession
    parts.append(liturgy_steps(variant, "prayers-of-the-people", ctx,
                               default_unit=prayers_file))
    if include_confession:
        parts.append(liturgy_steps(variant, "confession-of-sin", ctx,
                                   default_unit="absolution" if standard_form_vi else "confession-of-sin"))
    parts.append(liturgy_steps(variant, "peace", ctx))
    parts.append(qr_block(brand, repo_root))

    parts.append(hymn_block("Offertory Anthem", music.get("offertory_anthem"), config_dir,
                            full_page=False))
    parts.append(hymn_block("Offertory Hymn", hymns.get("offertory"), config_dir))
    parts.append(doxology_block(cfg, ctx, variant, config_dir))

    parts.append(service_title("The Holy Communion"))
    ep_choice = configured_liturgy_file(cfg, "eucharistic_prayer", "eucharistic_prayer")
    ep_file = (f"{ep_choice}-full"
               if liturgy.get("print_full_eucharistic_prayer", opts.get("print_full_eucharistic_prayer"))
               and ep_choice in {f"eucharistic-prayer-{letter}" for letter in "abcd"} else ep_choice)
    # Keep the written Sursum Corda dialogue in the Great Thanksgiving. The
    # supplied notation is adjacent music, never a replacement.
    parts.append(hymn_block("Sursum Corda", music.get("sursum_corda"), config_dir,
                            full_page=False))
    parts.append(liturgy_steps(variant, "eucharistic-prayer", ep_ctx,
                               default_unit=ep_file,
                               head="The Great Thanksgiving"))
    lord_file = configured_liturgy_file(cfg, "lords_prayer", "lords_prayer")
    parts.append(liturgy_steps(variant, "lords-prayer", ctx,
                               default_unit=lord_file))

    # The fraction anthem sits between the fraction dialogue and the
    # communion-welcome rubrics, so the rubrics backfill the page when
    # the anthem's music forces a break. Variant units still use staged files.
    def render_breaking(identifier, render_ctx, **kwargs):
        if identifier != "breaking-of-bread":
            return liturgy_section(identifier, render_ctx, **kwargs)
        breaking_name = (liturgy.get("files", {}) or {}).get(identifier, identifier)
        fb = [b for b in parse_liturgy(LITURGY_DIR / f"{breaking_name}.md")
              if b[0] != "title"]
        split = next((i for i, (k, p) in enumerate(fb)
                      if k == "rubric" and str(p).startswith(("All are welcome", "[Communion welcome"))),
                     len(fb))
        return (keep_or_flow("The Breaking of the Bread",
                             render_blocks(fb[:split], render_ctx))
                + render_blocks(fb[split:], render_ctx))

    fraction = liturgy_steps(variant, "breaking-of-bread", ctx,
                             renderer=render_breaking)
    if music.get("fraction_anthem"):
        fraction += hymn_block("", music["fraction_anthem"], config_dir,
                               full_page=False, max_h=5.9)
    parts.append(fraction)

    parts.append(hymn_block("Communion Anthem", music.get("communion_anthem"), config_dir,
                            full_page=False))
    parts.append(hymn_block("Communion Hymn", hymns.get("communion"),
                            config_dir, full_page=False))
    parts.append(liturgy_steps(variant, "post-communion-prayer", ctx))

    parts.append(blessing_block(cfg, brand, ctx))

    closing_hymn = hymns.get("closing")
    closing_hymn_markup = hymn_block("Closing Hymn", closing_hymn, config_dir)
    postlude_markup = hymn_block("Postlude", music.get("postlude"), config_dir, full_page=False)
    dismissal_markup = liturgy_steps(variant, "dismissal", ctx)
    if closing_hymn_position(cfg) == "before_dismissal":
        parts.append(closing_hymn_markup)
        parts.append(dismissal_markup)
        closing = postlude_markup
    else:
        parts.append(dismissal_markup)
        closing = closing_hymn_markup + postlude_markup
    back = announcements_block(cfg, brand, repo_root)
    if can_merge_back_page(cfg, closing_hymn, back):
        parts.append(f'<div class="backpage">{closing}{_backpage_inner(back)}</div>')
    else:
        parts.append(closing)
        parts.append('<div class="page-break"></div>')
        parts.append(back)
    return "\n".join(p for p in parts if p)


def build_lutheran_content(cfg, brand, repo_root, config_dir, template):
    """Render a Lutheran service plan using church-supplied local sources."""
    svc = cfg["service"]
    hymns = cfg.get("hymns", {})
    music = cfg.get("service_music") or {}
    liturgy = cfg.get("liturgy", {})
    if not isinstance(liturgy, dict):
        liturgy = {}
    service_plan = resolved_service_plan(cfg)
    if service_plan != "lutheran-holy-communion":
        raise ValueError(f"unsupported Lutheran service plan: {service_plan}")
    variant = service_variant_order(cfg, service_plan)
    ctx = {
        "proper_preface": cfg.get("proper_preface"),
        "communion_welcome": liturgy.get("communion_welcome"),
        "liturgy_files": liturgy.get("files", {}),
        "prayer_presentation": liturgy.get("prayer_presentation", "continuous"),
        "rubric_style": liturgy.get("rubric_style", "concise"),
    }

    def section(identifier, label, logical=None):
        logical = logical or identifier
        if (identifier not in ctx["liturgy_files"]
                and logical not in variant.get("replace", {})):
            raise ValueError(f"Lutheran service plan is missing liturgy.files.{identifier}")
        return liturgy_steps(variant, logical, ctx, default_unit=identifier, head=label)

    parts = [cover_page(cfg, brand, repo_root, template), parish_information_block(cfg, "before_service")]
    parts.append(hymn_block("Prelude", music.get("prelude"), config_dir))
    parts.append(hymn_block("Entrance Hymn", hymns.get("entrance"), config_dir))
    parts.append(section("gathering", "Gathering"))
    parts.append(service_title("The Word of God"))
    readings = cfg.get("readings", {})
    include_first = liturgy.get("include_first_reading", True)
    include_second = liturgy.get("include_second_reading", True)
    if include_first and readings.get("first"):
        parts.append(reading_block("The Reading" if not include_second else "The First Reading", readings["first"]))
    if not include_first and include_second and readings.get("second"):
        parts.append(reading_block("The Reading", readings["second"]))
    parts.append(hymn_block("Psalm Antiphon", music.get("psalm_antiphon"), config_dir,
                            full_page=False))
    if readings.get("psalm"):
        parts.append(psalm_block(readings["psalm"]))
    if include_first and include_second and readings.get("second"):
        parts.append(reading_block("The Second Reading", readings["second"]))
    parts.append(hymn_block("Gospel Acclamation", hymns.get("gospel_acclamation"), config_dir))
    if readings.get("gospel"):
        parts.append(gospel_block(readings["gospel"], gospel_acclamation_choice(cfg)))
    parts.append('<div class="section">' + keep(section_head("The Sermon"),
                 f'<p class="service-person center">{esc(svc.get("preacher", ""))}</p>') + '</div>')
    parts.append(section("prayers", "Prayers of the Church"))
    parts.append(hymn_block("Offertory Anthem", music.get("offertory_anthem"), config_dir,
                            full_page=False))
    parts.append(hymn_block("Offertory Hymn", hymns.get("offertory"), config_dir))
    parts.append(service_title("Holy Communion"))
    parts.append(section("great-thanksgiving", "The Great Thanksgiving", logical="meal"))
    parts.append(section("lords-prayer", "The Lord's Prayer"))
    parts.append(section("communion", "The Holy Communion"))
    parts.append(hymn_block("Communion Anthem", music.get("communion_anthem"), config_dir,
                            full_page=False))
    parts.append(hymn_block("Communion Hymn", hymns.get("communion"), config_dir,
                            full_page=False))
    closing_hymn = hymns.get("closing")
    closing_hymn_markup = hymn_block("Closing Hymn", closing_hymn, config_dir)
    postlude_markup = hymn_block("Postlude", music.get("postlude"), config_dir, full_page=False)
    sending_markup = section("sending", "Sending")
    # The Lutheran plan's "sending" section already includes its own spoken
    # dismissal, so the hymn position choice only moves the hymn relative to
    # that section, mirroring the Episcopal plan's before/after dismissal.
    if closing_hymn_position(cfg) == "before_dismissal":
        parts.append(closing_hymn_markup)
        parts.append(sending_markup)
        closing = postlude_markup
    else:
        parts.append(sending_markup)
        closing = closing_hymn_markup + postlude_markup
    back = announcements_block(cfg, brand, repo_root)
    if can_merge_back_page(cfg, closing_hymn, back):
        parts.append(f'<div class="backpage">{closing}{_backpage_inner(back)}</div>')
    else:
        parts.append(closing)
        parts.append('<div class="page-break"></div>')
        parts.append(back)
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Compact template content
# ---------------------------------------------------------------------------

BCP_REFS = [
    ("The Opening Acclamation", "BCP 355"),
    ("The Collect for Purity", "BCP 355"),
    ("The Collect of the Day", "in this leaflet"),
    ("The Readings", "in this leaflet"),
    ("The Sermon", None),
    ("The Nicene Creed", "BCP 358"),
    ("The Prayers of the People, Form III", "BCP 387"),
    ("The Confession of Sin", "BCP 360"),
    ("The Peace", "BCP 360"),
    ("The Great Thanksgiving, Prayer A", "BCP 361"),
    ("The Lord's Prayer", "BCP 364"),
    ("The Breaking of the Bread", "BCP 364"),
    ("The Post-Communion Prayer", "BCP 365"),
    ("The Blessing and Dismissal", None),
]


def build_compact_content(cfg, brand, repo_root, config_dir):
    svc = cfg["service"]
    hymns = cfg.get("hymns", {})
    church = brand["church"]
    logo = brand.get("logo", {}).get("banner")
    logo_html = (f'<img class="compact-logo" src="{file_uri(repo_root / logo)}" alt="">'
                 if logo and (repo_root / logo).exists() else "")

    hymn_rows = []
    for label, key in (("Entrance Hymn", "entrance"), ("Gradual Hymn", "gradual"),
                       ("Offertory Hymn", "offertory"), ("Communion Hymn", "communion"),
                       ("Closing Hymn", "closing")):
        h = hymns.get(key)
        if not h:
            continue
        ref = (f"Hymn {h['number']}" if h.get("number")
               else (h.get("tune") or "see insert"))
        hymn_rows.append((label, f'{esc(ref)} &middot; {esc(h.get("title", ""))}'))

    def order_rows():
        out = []
        hymn_iter = {r[0]: r[1] for r in hymn_rows}
        sequence = (["Entrance Hymn"] + [b[0] for b in BCP_REFS[:4]]
                    + ["Gradual Hymn", "The Holy Gospel", "The Sermon",
                       "The Nicene Creed", "The Prayers of the People, Form III",
                       "The Confession of Sin", "The Peace", "Offertory Hymn",
                       "The Great Thanksgiving, Prayer A", "The Lord's Prayer",
                       "The Breaking of the Bread", "Communion Hymn",
                       "The Post-Communion Prayer", "The Blessing and Dismissal",
                       "Closing Hymn"])
        refs = dict(BCP_REFS)
        refs["The Holy Gospel"] = "in this leaflet"
        for item in sequence:
            if item in hymn_iter:
                out.append((item, hymn_iter[item]))
            elif item in refs:
                out.append((item, refs[item] or ""))
        return out

    order_html = "\n".join(
        f'<div class="order-row"><span class="order-item">{esc(i)}</span>'
        f'<span class="order-dots"></span>'
        f'<span class="order-ref">{r}</span></div>'
        for i, r in order_rows())

    readings = cfg.get("readings", {})
    readings_html = ""
    for label, key in (("The First Reading", "first"), ("The Second Reading", "second"),
                       ("The Holy Gospel", "gospel")):
        r = readings.get(key)
        if r:
            readings_html += (f'<div class="dialogue"><span class="speaker-wide">{label}</span>'
                              f'<span class="line">{esc(r.get("citation", ""))}</span></div>')

    psalm_html = psalm_block(readings["psalm"]) if readings.get("psalm") else ""

    date_line = fmt_date(svc["date"])
    parts = [f"""
<div class="compact-header">
  {logo_html}
  <h1 class="cover-occasion">{esc(svc["occasion"])}</h1>
  <p class="cover-date">{esc(svc.get("proper", ""))} &middot; {date_line}</p>
  <p class="cover-kicker">{esc(resolved_service_display(cfg, church))}</p>
</div>
<p class="rubric center">Page numbers refer to the red Book of Common Prayer.
Hymns are found in the blue Hymnal 1982.</p>
<div class="section">{section_head("The Order of Service")}{order_html}</div>
<div class="page-break"></div>
<div class="section">{section_head("The Collect of the Day")}
<p class="prose">{inline_md(cfg.get("collect_of_day", ""))}</p></div>
<div class="section">{section_head("The Readings")}{readings_html}</div>
{psalm_html}
<div class="page-break"></div>
{announcements_block(cfg, brand, repo_root, include_qr=True)}
"""]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS assembly
# ---------------------------------------------------------------------------

def font_faces():
    faces = []
    specs = [
        ("EB Garamond", "EBGaramond-Regular.ttf", 400, "normal"),
        ("EB Garamond", "EBGaramond-SemiBold.ttf", 600, "normal"),
        ("EB Garamond", "EBGaramond-Bold.ttf", 700, "normal"),
        ("EB Garamond", "EBGaramond-Italic.ttf", 400, "italic"),
        ("EB Garamond", "EBGaramond-SemiBoldItalic.ttf", 600, "italic"),
        ("Source Serif 4", "SourceSerif4-Regular.ttf", 400, "normal"),
        ("Source Serif 4", "SourceSerif4-SemiBold.ttf", 600, "normal"),
        ("Source Serif 4", "SourceSerif4-Bold.ttf", 700, "normal"),
        ("Source Serif 4", "SourceSerif4-Italic.ttf", 400, "italic"),
        ("Source Serif 4", "SourceSerif4-SemiBoldItalic.ttf", 600, "italic"),
        ("Source Sans 3", "SourceSans3-Regular.ttf", 400, "normal"),
        ("Source Sans 3", "SourceSans3-SemiBold.ttf", 600, "normal"),
        ("Source Sans 3", "SourceSans3-Bold.ttf", 700, "normal"),
        ("Source Sans 3", "SourceSans3-Italic.ttf", 400, "italic"),
    ]
    for family, fname, weight, style in specs:
        p = FONTS_DIR / fname
        if p.exists():
            faces.append(
                f'@font-face {{ font-family: "{family}"; src: url("{p.as_uri()}"); '
                f'font-weight: {weight}; font-style: {style}; }}')
    return "\n".join(faces)


def build_css(template, brand):
    colors = brand.get("colors", NEUTRAL_BRAND["colors"])
    resolved_footer = bulletin_footer(brand)
    footer_bits = [smart_quotes(str(resolved_footer[key]))
                   for key in ("contact_name", "address", "phone", "email", "website")
                   if str(resolved_footer[key] or "").strip()]
    resolved_footer_line = "  ·  ".join(footer_bits)
    tokens = {
        "ink": colors.get("ink", "#1a1a1a"),
        "accent": colors.get("accent", "#4a5d7e"),
        "accent_deep": colors.get("accent_deep", "#2e3a52"),
        "rubric": colors.get("rubric_red", "#8B3A3A"),
        "footer_line": resolved_footer_line.replace('"', '\\"'),
    }
    css = ""
    for name in ("base", template):
        sheet = (THEMES_DIR / f"{name}.css").read_text(encoding="utf-8")
        css += Template(sheet).substitute(tokens) + "\n"
    return font_faces() + "\n" + css


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bulletin log: one record per service date, updated on every render.
# Powers questions like "when did we last sing Hymn 376?" via
# bulletin_history.py.
# ---------------------------------------------------------------------------

def find_log_path(config_dir):
    for parent in [config_dir] + list(config_dir.parents):
        if parent.name in ("bulletins", "weekly-bulletins"):
            return parent / "bulletin-log.json"
    return config_dir / "bulletin-log.json"


def music_entry(slot, h):
    if not h:
        return None
    imgs = h.get("images") or ([h["image"]] if h.get("image") else [])
    hid = Path(imgs[0]).stem if imgs else None
    return {"slot": slot, "id": hid, "number": h.get("number"),
            "title": h.get("title"), "tune": h.get("tune")}


def build_log_entry(cfg):
    svc = cfg.get("service", {})
    readings = cfg.get("readings", {})
    hymns = [music_entry(s, cfg.get("hymns", {}).get(s))
             for s in ("entrance", "gradual", "offertory", "communion", "closing")]
    music = [music_entry(s, cfg.get("service_music", {}).get(s))
             for s in ("gloria", "sanctus", "fraction_anthem")]
    return {
        "date": svc.get("date"),
        "occasion": svc.get("occasion"),
        "proper": svc.get("proper"),
        "lectionary_track": svc.get("lectionary_track"),
        "liturgical_color": svc.get("liturgical_color"),
        "preacher": svc.get("preacher"),
        "celebrant": svc.get("celebrant"),
        "readings": {
            "first": (readings.get("first") or {}).get("citation"),
            "psalm": (readings.get("psalm") or {}).get("number"),
            "second": (readings.get("second") or {}).get("citation"),
            "gospel": (readings.get("gospel") or {}).get("citation"),
        },
        "hymns": [h for h in hymns if h],
        "service_music": [m for m in music if m],
        "announcements": [a.get("title") for a in cfg.get("announcements", [])],
        "options": cfg.get("options", {}),
        "liturgy": cfg.get("liturgy", {}),
    }


def update_bulletin_log(cfg, config_dir, template, pdf_path):
    log_path = find_log_path(config_dir)
    log = {}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            print(f"warning: could not parse {log_path}; leaving it untouched")
            return
    entry = build_log_entry(cfg)
    date = entry.get("date")
    if not date:
        return
    prior = log.get(date, {})
    templates = prior.get("templates", {})
    pages = None
    try:
        from pypdf import PdfReader
        pages = len(PdfReader(str(pdf_path)).pages)
    except Exception:
        pass
    templates[template] = {
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
        "pages": pages,
    }
    entry["templates"] = templates
    log[date] = entry
    ordered = {k: log[k] for k in sorted(log)}
    log_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Bulletin log updated: {log_path.name} [{date}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--template", default="classic",
                    choices=["classic", "modern"])
    ap.add_argument("--brand", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--liturgy-dir", default=None,
                    help="Use staged church-owned liturgy sources over the shipped set.")
    ap.add_argument(
        "--no-log",
        action="store_true",
        help="Do not update bulletin history. Used by approval-gated production.",
    )
    args = ap.parse_args()

    global LITURGY_DIR
    if args.liturgy_dir:
        LITURGY_DIR = Path(args.liturgy_dir).resolve()

    config_path = Path(args.config).resolve()
    config_dir = config_path.parent
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    # Brand: walk up from the config toward the church folder root,
    # accepting brand.json or shared/brand/brand.json at any level.
    brand_path = Path(args.brand) if args.brand else None
    repo_root = config_dir
    if brand_path is None:
        for parent in [config_dir] + list(config_dir.parents):
            cands = (parent / "brand.json", parent / "shared/brand/brand.json")
            hit = next((c for c in cands if c.exists()), None)
            if hit is not None:
                brand_path = hit
                repo_root = parent
                break
    else:
        repo_root = brand_path.resolve().parent
    if brand_path is not None and brand_path.exists():
        brand = json.loads(brand_path.read_text(encoding="utf-8"))
    else:
        print("note: no brand.json found above the config; using neutral defaults")
        brand = NEUTRAL_BRAND

    out_dir = Path(args.out) if args.out else config_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.template == "compact":
        content = build_compact_content(cfg, brand, repo_root, config_dir)
    else:
        content = build_full_content(cfg, brand, repo_root, config_dir,
                                     args.template)

    css = build_css(args.template, brand)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><style>
{css}
</style></head>
<body class="tpl-{args.template}">
{content}
</body></html>"""

    date = cfg["service"]["date"]
    stem = f"bulletin-{date}-{args.template}"
    html_path = out_dir / f"{stem}.html"
    pdf_path = out_dir / f"{stem}.pdf"
    html_path.write_text(html, encoding="utf-8")

    import weasyprint
    weasyprint.HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    print(f"Bulletin PDF: {pdf_path}")
    if not args.no_log:
        update_bulletin_log(cfg, config_dir, args.template, pdf_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
