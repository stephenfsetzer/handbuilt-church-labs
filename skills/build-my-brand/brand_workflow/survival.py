"""Survival checks, mark rendering, and exploration contact sheets.

A mark is designed inside the developed system by the senior designer. These
scripts never drive the design. They run at the system stage as pass/fail
checks (sign distance, 64 px footer, 16 px favicon on the derived small
variant, one color, reversal, embroidery minimums), they render a mark to
pixels so a person can look at it, and they lay a round of internal
exploration out on one contact sheet so the creative director can judge it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SIZES = {"sign": 512, "footer": 64, "favicon": 16}
# Street distance: a 60 cm sign seen from 20 m covers about the same field of
# view as a 24 px mark held at reading distance.
DISTANCE_PX = 24
CHECKS = {
    "sign": "Reads at street distance: shrunk to what a sign looks like from across the street, the mark keeps its shape",
    "footer": "Holds at 64 px, the bulletin footer: no part drops out and no gap fills in",
    "favicon": "The derived small variant holds at 16 px, the favicon",
    "one_color": "Prints in one color: a single paint, no second color, no gradient, no tone",
    "reversal": "Reverses white on the dark brand color, with the white actually present",
    "embroidery": "Embroiders at 25 mm tall: no stroke thinner than 1 mm and no gap narrower than 1 mm",
}
PRIMARY_CHECKS = ("sign", "footer", "one_color", "reversal", "embroidery")
SMALL_CHECKS = ("favicon", "one_color", "reversal")
# A creative director may accept a fit-for-purpose failure on these with a
# recorded reason. One color and reversal are correctness and cannot be waived.
WAIVABLE = {"sign", "footer", "favicon", "embroidery"}
ALLOWED_PAINT = {"currentcolor", "none", "black", "white", "#000", "#000000", "#fff", "#ffffff", "inherit"}
PAINT_ATTRS = {"fill", "stroke", "color", "stop-color", "flood-color", "lighting-color"}
FORBIDDEN_TAGS = {"image", "foreignobject", "script", "style", "text", "use"}
TONE_TAGS = {"lineargradient", "radialgradient", "pattern", "filter", "mask"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".pdf"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CURRENT_COLOR = re.compile(r"currentcolor", re.I)
MIN_COVERAGE = 0.03
MIN_RETAINED = 0.2
DEFAULT_DARK = "#1a1a1a"


class SurvivalFailure(Exception):
    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code, self.message, self.field = code, message, field


def slug(value: str, *, field: str = "round") -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    if not out:
        raise SurvivalFailure("invalid_round", f"A {field} name is required", field=field)
    return out


# ---------------------------------------------------------------- the SVG itself

def validate_mark_svg(path: Path, *, one_color: bool = False) -> str:
    """A self-contained vector with a viewBox. With one_color, a single paint only. Returns the text."""
    text = path.read_text(encoding="utf-8")
    lowered = text.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered or "url(" in lowered or re.search(r"href\s*=\s*[\"']\s*(?:https?:|//|data:)", lowered):
        raise SurvivalFailure("unsafe_svg", f"{path.name}: marks must be self-contained SVG with no external references")
    try:
        element = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SurvivalFailure("invalid_svg", f"{path.name}: not valid SVG ({exc})") from exc
    if element.tag.rsplit("}", 1)[-1].casefold() != "svg":
        raise SurvivalFailure("invalid_svg", f"{path.name}: root element must be <svg>")
    if not element.get("viewBox"):
        raise SurvivalFailure("invalid_svg", f"{path.name}: the <svg> needs a viewBox so it scales")
    for node in element.iter():
        tag = node.tag.rsplit("}", 1)[-1].casefold()
        if tag in FORBIDDEN_TAGS:
            raise SurvivalFailure("invalid_svg", f"{path.name}: <{tag}> is not allowed in a mark; draw shapes, not text or images")
        if one_color:
            if tag in TONE_TAGS:
                raise SurvivalFailure("not_one_color", f"{path.name}: <{tag}> adds tone; a mark prints in one flat color")
            for key, value in node.attrib.items():
                name = key.rsplit("}", 1)[-1].casefold()
                if name in PAINT_ATTRS and value.strip().casefold() not in ALLOWED_PAINT:
                    raise SurvivalFailure("not_one_color", f"{path.name}: paint with currentColor, none, black, or white so the mark survives one color and reverses; found {value}")
                if name == "style" and re.search(r"(fill|stroke|color)\s*:\s*(?!currentcolor|none|black|white|#000|#fff|inherit)", value, re.I):
                    raise SurvivalFailure("not_one_color", f"{path.name}: remove colors from style attributes; paint with currentColor")
    return text


def _paint(svg_text: str, color: str) -> str:
    """WeasyPrint does not carry CSS color into currentColor inside inline SVG, so paint it literally."""
    return CURRENT_COLOR.sub(color, svg_text)


def _inline(svg_text: str, size_px: int, background: str) -> str:
    return (f'<div style="width:{size_px}px;height:{size_px}px;background:{background};'
            f'display:flex;align-items:center;justify-content:center;overflow:hidden">'
            f'<div style="width:{int(size_px * 0.84)}px;height:{int(size_px * 0.84)}px">{svg_text}</div></div>')


def render_mark(root: Path, svg_path: Path, out_dir: Path, dark: str = DEFAULT_DARK) -> dict[str, str]:
    """Render sign (black on white) and reversed (white on dark) at 512 px, plus footer and favicon at true size.

    Uses WeasyPrint and pdftoppm, which the plugin already needs. Small sizes
    are also saved enlarged pixel for pixel so a person can see them.
    """
    try:
        from weasyprint import HTML  # noqa: WPS433
    except ImportError as exc:
        raise SurvivalFailure("renderer_unavailable", "WeasyPrint is unavailable in this runtime; run the runtime doctor") from exc
    from PIL import Image  # noqa: WPS433
    if not HEX.fullmatch(dark or ""):
        raise SurvivalFailure("invalid_dark", "The dark color must be a six-digit hex value", field="dark")
    svg_text = svg_path.read_text(encoding="utf-8")
    svg_text = re.sub(r"<svg\b", '<svg style="width:100%;height:100%;display:block"', svg_text, count=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    views = {"sign": ("#000000", "#ffffff"), "reversed": ("#ffffff", dark)}
    outputs: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as temp:
        for view, (color, background) in views.items():
            doc = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>@page{size:512px 512px;margin:0}body{margin:0}</style></head><body>'
                   + _inline(_paint(svg_text, color), 512, background) + "</body></html>")
            pdf = Path(temp) / f"{view}.pdf"
            HTML(string=doc, base_url=str(root)).write_pdf(str(pdf))
            subprocess.run(["pdftoppm", "-png", "-r", "96", "-singlefile", str(pdf), str(Path(temp) / view)], check=True, capture_output=True)
            image = Image.open(Path(temp) / f"{view}.png").convert("RGB")
            if image.size != (512, 512):
                image = image.resize((512, 512), Image.LANCZOS)
            target = out_dir / f"{svg_path.stem}-{view}.png"
            image.save(target)
            outputs[view] = target.relative_to(root).as_posix()
            if view == "sign":
                for name, px in (("footer", SIZES["footer"]), ("favicon", SIZES["favicon"])):
                    small = image.resize((px, px), Image.LANCZOS)
                    path_small = out_dir / f"{svg_path.stem}-{name}.png"
                    small.save(path_small)
                    outputs[name] = path_small.relative_to(root).as_posix()
                    preview = small.resize((256, 256), Image.NEAREST)
                    path_preview = out_dir / f"{svg_path.stem}-{name}-preview.png"
                    preview.save(path_preview)
                    outputs[f"{name}_preview"] = path_preview.relative_to(root).as_posix()
    return outputs


# ---------------------------------------------------------------- measurements

def _ink(image) -> Any:
    """Ink as a 1-bit image: dark pixels on a white ground."""
    return image.convert("L").point(lambda v: 255 if v < 128 else 0)


def _coverage(image) -> float:
    ink = _ink(image)
    histogram = ink.histogram()
    return histogram[255] / (ink.width * ink.height)


def _bbox(image):
    return _ink(image).getbbox()


def _ratio_check(name: str, base: float, small: float, low: float, high: float, detail: str) -> dict[str, Any]:
    if base < MIN_COVERAGE:
        return {"check": name, "passed": False, "detail": f"The mark covers only {base:.1%} of its frame at 512 px; there is too little to read"}
    ratio = small / base if base else 0.0
    passed = low <= ratio <= high
    return {"check": name, "passed": passed, "detail": f"{detail}: ink {small:.1%} against {base:.1%} at 512 px (ratio {ratio:.2f}; pass is {low:.2f} to {high:.2f})"}


def check_sign(sign_image) -> dict[str, Any]:
    from PIL import Image  # noqa: WPS433
    base = _coverage(sign_image)
    far = sign_image.resize((DISTANCE_PX, DISTANCE_PX), Image.LANCZOS)
    return _ratio_check("sign", base, _coverage(far), 0.6, 1.5, f"Seen from across the street ({DISTANCE_PX} px)")


def check_footer(sign_image, footer_image) -> dict[str, Any]:
    return _ratio_check("footer", _coverage(sign_image), _coverage(footer_image), 0.6, 1.5, "At 64 px")


def check_favicon(sign_image, favicon_image) -> dict[str, Any]:
    return _ratio_check("favicon", _coverage(sign_image), _coverage(favicon_image), 0.5, 1.6, "At 16 px")


def check_one_color(svg_path: Path, sign_image) -> dict[str, Any]:
    try:
        validate_mark_svg(svg_path, one_color=True)
    except SurvivalFailure as exc:
        return {"check": "one_color", "passed": False, "detail": exc.message}
    gray = sign_image.convert("L")
    histogram = gray.histogram()
    total = gray.width * gray.height
    tone = sum(histogram[40:216]) / total
    passed = tone <= 0.05
    return {"check": "one_color", "passed": passed, "detail": f"{tone:.1%} of pixels are a tone between black and white (edges only is under 5%)"}


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def check_reversal(reversed_image, dark: str) -> dict[str, Any]:
    from PIL import ImageChops  # noqa: WPS433
    rgb = reversed_image.convert("RGB")
    total = rgb.width * rgb.height
    red, green, blue = rgb.split()
    lightest_channel = ImageChops.darker(ImageChops.darker(red, green), blue)
    white = lightest_channel.point(lambda v: 255 if v > 225 else 0).histogram()[255]
    floor = _luminance(dark) - 8
    darker = rgb.convert("L").point(lambda v: 255 if v < floor else 0).histogram()[255]
    if white < total * 0.01:
        return {"check": "reversal", "passed": False, "detail": "Reversed on the dark color, no white is present; paint the mark with currentColor so it can reverse"}
    if darker:
        return {"check": "reversal", "passed": False, "detail": f"Reversed on the dark color, {darker} pixels are darker than the ground; part of the mark is painting black"}
    return {"check": "reversal", "passed": True, "detail": f"White present ({white / total:.1%} of the frame) and nothing darker than the ground"}


def check_embroidery(sign_image) -> dict[str, Any]:
    from PIL import ImageFilter  # noqa: WPS433
    ink = _ink(sign_image)
    box = ink.getbbox()
    if not box:
        return {"check": "embroidery", "passed": False, "detail": "No ink to measure"}
    height = box[3] - box[1]
    # The mark is embroidered 25 mm tall; half a millimetre is the erosion radius.
    radius = max(1, round(height / 50))
    size = radius * 2 + 1
    ink_area = ink.histogram()[255]
    eroded = ink.filter(ImageFilter.MinFilter(size)).histogram()[255]
    stroke_kept = eroded / ink_area if ink_area else 0.0
    paper = ink.crop(box).point(lambda v: 255 - v)
    paper_area = paper.histogram()[255]
    closed = paper.filter(ImageFilter.MinFilter(size)).histogram()[255]
    gap_kept = closed / paper_area if paper_area else 1.0
    passed = stroke_kept >= MIN_RETAINED and gap_kept >= MIN_RETAINED
    return {"check": "embroidery", "passed": passed,
            "detail": f"At 25 mm tall, strokes thinner than 1 mm lose {1 - stroke_kept:.0%} of the ink and gaps narrower than 1 mm close {1 - gap_kept:.0%} of the paper inside the mark (each must keep {MIN_RETAINED:.0%})"}


def run_checks(root: Path, svg_path: Path, out_dir: Path, *, which: tuple[str, ...], dark: str = DEFAULT_DARK) -> dict[str, Any]:
    """Render one mark and run the named checks. Pass or fail, never a score."""
    from PIL import Image  # noqa: WPS433
    validate_mark_svg(svg_path)
    renders = render_mark(root, svg_path, out_dir, dark=dark)

    def load(view: str):
        with Image.open(root / renders[view]) as image:
            return image.convert("RGB")

    sign = load("sign")
    results = []
    for name in which:
        if name == "sign":
            results.append(check_sign(sign))
        elif name == "footer":
            results.append(check_footer(sign, load("footer")))
        elif name == "favicon":
            results.append(check_favicon(sign, load("favicon")))
        elif name == "one_color":
            results.append(check_one_color(svg_path, sign))
        elif name == "reversal":
            results.append(check_reversal(load("reversed"), dark))
        elif name == "embroidery":
            results.append(check_embroidery(sign))
    return {"mark": svg_path.relative_to(root).as_posix(), "renders": renders, "checks": results,
            "passed": all(r["passed"] for r in results)}


# ---------------------------------------------------------------- exploration contact sheets

def contact_sheet(root: Path, items: list[dict[str, Any]], out: Path) -> str:
    """One image for a round of internal exploration, so it can be judged at a glance."""
    from PIL import Image, ImageDraw  # noqa: WPS433
    cell, pad, cols = 180, 12, 4
    rows = max(1, (len(items) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (cell * 2 + pad) + pad, rows * (cell + 40 + pad) + pad), "#f4f4f2")
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(items):
        x = pad + (index % cols) * (cell * 2 + pad)
        y = pad + (index // cols) * (cell + 40 + pad)
        renders = item.get("renders") or {}

        def load(path: str):
            with Image.open(root / path) as image:
                return image.convert("RGB")

        if renders:
            sheet.paste(load(renders["sign"]).resize((cell, cell)), (x, y))
            sheet.paste(load(renders["favicon_preview"]).resize((cell // 2, cell // 2)), (x + cell, y))
            sheet.paste(load(renders["reversed"]).resize((cell // 2, cell // 2)), (x + cell, y + cell // 2))
        else:
            image = load(item["file"])
            image.thumbnail((cell * 2, cell))
            sheet.paste(image, (x, y))
        draw.text((x + 4, y + cell + 8), item["id"], fill="#222222")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out.relative_to(root).as_posix()


def copy_in(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
