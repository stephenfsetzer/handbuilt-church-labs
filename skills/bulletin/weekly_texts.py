"""Put verified texts into a weekly bulletin file without anyone retyping them.

The agent names what the Sunday needs: a citation for each lesson, a psalm
number, and the collect and preface by their library names. This module copies
the words from their sources into the file. The lessons come from the published
lectionary page. The psalm, collect and preface come from the bundled Sunday
library. Nothing here prints a passage, so the words go from the source to the
page untouched.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from skills.bulletin.sunday_library import SundayLibraryError, lookup

LESSON_SLOTS = ("first", "second", "gospel")
ALLOWED_HOSTS = {"lectionarypage.net", "www.lectionarypage.net"}
PAGE_LIMIT = 2_000_000
CLIENT = "HandbuiltChurchLabs (+https://gethandbuilt.com)"
SOURCE_LABEL = "The Lectionary Page"


class WeeklyTextsError(ValueError):
    """A plain-language reason the texts could not be filled in."""


def fetch_page(url: str) -> str:
    """Download one lectionary page, naming this program honestly."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise WeeklyTextsError("Give the page's address on https://lectionarypage.net/.")
    request = urllib.request.Request(url, headers={"User-Agent": CLIENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urllib.parse.urlparse(response.url)
            if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                raise WeeklyTextsError("The lectionary page sent this download somewhere unexpected.")
            data = response.read(PAGE_LIMIT + 1)
    except OSError as exc:
        raise WeeklyTextsError(f"The lectionary page could not be downloaded: {exc}") from exc
    if len(data) > PAGE_LIMIT:
        raise WeeklyTextsError("The lectionary page was larger than expected.")
    return data.decode("utf-8", errors="replace")


class _Lessons(HTMLParser):
    """Collect each lesson on a lectionary page: its heading, citation and paragraphs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lessons: list[dict] = []
        self._lesson: dict | None = None
        self._field: str | None = None
        self._buffer: list[str] = []
        self._spans: list[bool] = []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "span":
            self._spans.append("lordSmallCaps" in classes)
        if tag == "article":
            self._lesson = {"heading": "", "citation": "", "paragraphs": []}
        elif self._lesson is None:
            return
        elif tag == "h2" and "lessonHeading" in classes:
            self._start("heading")
        elif tag == "h3" and "lessonCitation" in classes:
            self._start("citation")
        elif tag == "p" and {"lessonText", "poetryText"} & set(classes):
            self._start("poetry" if "poetryText" in classes else "prose")
        elif tag == "br" and self._field in ("poetry", "prose"):
            self._buffer.append("\n")

    def _start(self, field):
        self._field, self._buffer = field, []

    def handle_data(self, data):
        if self._field:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        divine_name = self._spans.pop() if tag == "span" and self._spans else False
        if self._lesson is None:
            return
        if tag == "article":
            if self._lesson["citation"] and self._lesson["paragraphs"]:
                self.lessons.append(self._lesson)
            self._lesson = self._field = None
        elif divine_name and self._field in ("poetry", "prose"):
            self._buffer.append("\x00")  # the page sometimes drops the space after this word; see _join
        elif self._field and tag in ("h2", "h3", "p"):
            text = _join(self._buffer)
            if self._field in ("heading", "citation"):
                self._lesson[self._field] = " ".join(text.split())
            elif text:
                self._lesson["paragraphs"].append((self._field, text))
            self._field = None


def _join(pieces: list[str]) -> str:
    """Join a paragraph's pieces, keeping line breaks and repairing a space the page dropped after the divine name."""
    text = re.sub(r"\x00(?=[A-Za-z])", " ", "".join(pieces)).replace("\x00", "")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_lessons(html: str) -> list[dict]:
    parser = _Lessons()
    parser.feed(html)
    return parser.lessons


def _key(citation: str) -> str:
    """A citation with spacing, dash style and optional-verse marks removed."""
    plain = citation.replace("\N{EN DASH}", "-").replace("\N{EM DASH}", "-")
    return re.sub(r"[\s()\[\]]", "", plain).lower()


def _apply_optional(text: str, optional: str | None, citation: str) -> str:
    """Keep or drop the parts a lectionary page sets off in square brackets."""
    if "[" not in text:
        return text
    if optional == "include":
        return text.replace("[", "").replace("]", "")
    if optional == "omit":
        kept = re.sub(r"\[[^\]]*\]", "", text)
        lines = [" ".join(line.split()) for line in kept.split("\n")]
        return "\n".join(lines).strip()
    raise WeeklyTextsError(
        f"{citation} has optional verses. Ask the pastor, then run this again with "
        "--optional-verses include or --optional-verses omit.")


def _lesson_text(lesson: dict, optional: str | None) -> tuple[str, bool]:
    """The reading as the bulletin stores it, and whether any of it is poetry."""
    poetry = any(kind == "poetry" for kind, _ in lesson["paragraphs"])
    blocks: list[str] = []
    previous = None
    for kind, text in lesson["paragraphs"]:
        if not poetry:
            text = " ".join(text.split())
        if kind == "poetry" and previous == "poetry":
            blocks[-1] += "\n" + text  # one poem stays together; the page splits it by couplet
        else:
            blocks.append(text)
        previous = kind
    return _apply_optional("\n\n".join(blocks), optional, lesson["citation"]), poetry


def _psalm_request(number) -> tuple[str, str | None]:
    """Split a psalm request such as "90:1-8,12" into the psalm and its verses."""
    match = re.fullmatch(r"\s*(\d+)\s*(?::\s*([\d,\s\-\u2013()]+))?\s*", str(number))
    if not match:
        raise WeeklyTextsError(f"The psalm should look like 90 or 90:1-8,12, not {number!r}.")
    verses = match.group(2)
    if verses:
        verses = re.sub(r"[\s()]", "", verses.replace("\N{EN DASH}", "-")).strip(",")
    return match.group(1), verses or None


def _blank(value) -> bool:
    return not str(value or "").strip()


def fill(bulletin: dict, *, page_html: str | None = None, page_url: str | None = None,
         optional: str | None = None, today: str | None = None) -> dict:
    """Fill the missing texts in a weekly bulletin. Returns a summary without any passage text."""
    today = today or datetime.date.today().isoformat()
    filled: list[dict] = []
    readings = bulletin.setdefault("readings", {})

    wanted = [slot for slot in LESSON_SLOTS
              if isinstance(readings.get(slot), dict) and _blank(readings[slot].get("text"))]
    if wanted:
        if page_html is None:
            raise WeeklyTextsError("Give the lectionary page for this Sunday with --lectionary-page.")
        lessons = {_key(lesson["citation"]): lesson for lesson in parse_lessons(page_html)}
        for slot in wanted:
            reading = readings[slot]
            citation = str(reading.get("citation") or "").strip()
            lesson = lessons.get(_key(citation))
            if not lesson:
                on_page = ", ".join(item["citation"] for item in lessons.values()) or "no lessons"
                raise WeeklyTextsError(
                    f"The page does not have {citation or 'a citation for the ' + slot + ' reading'}. It has: {on_page}.")
            text, poetry = _lesson_text(lesson, optional)
            reading["text"] = text
            if poetry:
                reading["format"] = "poetry"
            reading["source"] = {"label": SOURCE_LABEL, "location": page_url or "", "verified_on": today}
            filled.append({"part": f"{slot} reading", "citation": lesson["citation"], "words": len(text.split())})

    psalm = readings.get("psalm")
    if isinstance(psalm, dict) and _blank(psalm.get("text")) and not _blank(psalm.get("number")):
        number, verses = _psalm_request(psalm["number"])
        liturgy = bulletin.get("liturgy") if isinstance(bulletin.get("liturgy"), dict) else {}
        try:
            entry = lookup("psalms", number, verses=verses,
                           psalm_format=liturgy.get("psalm_format") or "responsive_half_verse",
                           response_start=liturgy.get("psalm_response_start") or "second")
        except SundayLibraryError as exc:
            raise WeeklyTextsError(str(exc)) from exc
        entry.pop("number", None)
        psalm.update(entry)
        filled.append({"part": "psalm", "citation": f"Psalm {psalm['number']}", "words": len(entry["text"].split())})

    for field, category in (("collect_of_day", "collects"), ("proper_preface", "prefaces")):
        value = bulletin.get(field)
        if isinstance(value, dict) and not _blank(value.get("library")):
            try:
                entry = lookup(category, str(value["library"]))
            except SundayLibraryError as exc:
                raise WeeklyTextsError(str(exc)) from exc
            bulletin[field] = entry["text"]
            bulletin[f"{field.replace('_of_day', '')}_source"] = entry["source"]
            filled.append({"part": field.replace("_", " "), "citation": entry.get("title", value["library"]),
                           "words": len(entry["text"].split())})

    return {"status": "filled" if filled else "nothing_to_fill", "filled": filled}


def fill_file(path: str | os.PathLike, *, page_url: str | None = None, optional: str | None = None) -> dict:
    """Fill a weekly bulletin file in place. The file changes only when every text was found."""
    target = Path(path)
    bulletin = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(bulletin, dict):
        raise WeeklyTextsError("The weekly bulletin file should hold one JSON object.")
    readings = bulletin.get("readings") if isinstance(bulletin.get("readings"), dict) else {}
    needs_page = any(isinstance(readings.get(slot), dict) and _blank(readings[slot].get("text"))
                     for slot in LESSON_SLOTS)
    page_html = fetch_page(page_url) if needs_page and page_url else None
    summary = fill(bulletin, page_html=page_html, page_url=page_url, optional=optional)
    if summary["filled"]:
        handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".weekly-texts-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(bulletin, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
    summary["file"] = str(target)
    return summary
