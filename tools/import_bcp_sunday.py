#!/usr/bin/env python3
"""Build the public-domain BCP 1979 Sunday text library from the source PDF.

The importer deliberately extracts only the variable Sunday material needed by
the bulletin workflow.  It never checks in the intermediate full-book text
dump.  ``pdftotext -layout`` is run for each build so page provenance remains
explicit and reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, NamedTuple


SOURCE_URL = "https://www.episcopalchurch.org/wp-content/uploads/2021/02/book-of-common-prayer-2006.pdf"
KNOWN_PDF_SHA256 = "d4552eb39fcc26c7f2bb83ccd8e15fae4801521ac0e76df12b60bbd1525a0a57"
VERIFIED_ON = "2026-09-08"
SOURCE_TITLE = "The Book of Common Prayer"
EDITION = "1979 Book of Common Prayer, 2006 PDF"


class Record(NamedTuple):
    line: str
    page: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pages(pdf: Path) -> list[list[str]]:
    """Return layout-preserving PDF pages without retaining a full-book file."""

    with tempfile.TemporaryDirectory(prefix="bcp-sunday-") as temporary:
        text_path = Path(temporary) / "bcp-layout.txt"
        subprocess.run(
            ["pdftotext", "-layout", str(pdf), str(text_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        text = text_path.read_text(encoding="utf-8")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return [page.splitlines() for page in pages]


def records_for_pages(pages: list[list[str]], start: int, end: int) -> list[Record]:
    records: list[Record] = []
    for page_number in range(start, end + 1):
        for line in pages[page_number - 1]:
            records.append(Record(line, page_number))
        records.append(Record("", page_number))
    return records


def folded(lines: Iterable[str]) -> str:
    """Fold layout line wraps while retaining every source word and mark."""

    return " ".join(" ".join(line.strip().split()) for line in lines if line.strip()).strip()


def is_footer(line: str) -> bool:
    value = line.strip()
    return bool(
        re.search(r"(?:Collects: Contemporary|Collects: Traditional|Holy Eucharist II|Psalter)\s+\d+\s*$", value)
        or re.search(r"^\d+\s+(?:Collects: Contemporary|Collects: Traditional|Holy Eucharist II|Psalter)\s*$", value)
        or re.search(r"^\d+\s+Psalms?\s+\d", value)
    )


COLLECT_SPECS = [
    ("first-sunday-advent", "First Sunday of Advent"),
    ("second-sunday-advent", "Second Sunday of Advent"),
    ("third-sunday-advent", "Third Sunday of Advent"),
    ("fourth-sunday-advent", "Fourth Sunday of Advent"),
    ("christmas-day", "The Nativity of Our Lord: Christmas Day"),
    ("first-sunday-after-christmas", "First Sunday after Christmas Day"),
    ("holy-name", "The Holy Name"),
    ("second-sunday-after-christmas", "Second Sunday after Christmas Day"),
    ("epiphany", "The Epiphany"),
    ("baptism-of-our-lord", "First Sunday after the Epiphany: The Baptism of our Lord"),
    ("second-sunday-after-epiphany", "Second Sunday after the Epiphany"),
    ("third-sunday-after-epiphany", "Third Sunday after the Epiphany"),
    ("fourth-sunday-after-epiphany", "Fourth Sunday after the Epiphany"),
    ("fifth-sunday-after-epiphany", "Fifth Sunday after the Epiphany"),
    ("sixth-sunday-after-epiphany", "Sixth Sunday after the Epiphany"),
    ("seventh-sunday-after-epiphany", "Seventh Sunday after the Epiphany"),
    ("eighth-sunday-after-epiphany", "Eighth Sunday after the Epiphany"),
    ("last-sunday-after-epiphany", "Last Sunday after the Epiphany"),
    ("first-sunday-lent", "First Sunday in Lent"),
    ("second-sunday-lent", "Second Sunday in Lent"),
    ("third-sunday-lent", "Third Sunday in Lent"),
    ("fourth-sunday-lent", "Fourth Sunday in Lent"),
    ("fifth-sunday-lent", "Fifth Sunday in Lent"),
    ("palm-sunday", "Sunday of the Passion: Palm Sunday"),
    ("easter-day", "Easter Day"),
    ("second-sunday-easter", "Second Sunday of Easter"),
    ("third-sunday-easter", "Third Sunday of Easter"),
    ("fourth-sunday-easter", "Fourth Sunday of Easter"),
    ("fifth-sunday-easter", "Fifth Sunday of Easter"),
    ("sixth-sunday-easter", "Sixth Sunday of Easter"),
    ("ascension-day", "Ascension Day"),
    ("seventh-sunday-easter", "Seventh Sunday of Easter: The Sunday after Ascension Day"),
    ("pentecost", "The Day of Pentecost: Whitsunday"),
    ("trinity-sunday", "First Sunday after Pentecost: Trinity Sunday"),
]
COLLECT_SPECS.extend((f"proper-{number}", f"Proper {number}") for number in range(1, 30))
COLLECT_SPECS.append(("all-saints-day", "All Saints’ Day"))


_COLLECT_HEADING_NAMES = {label for _, label in COLLECT_SPECS}
_WEEKDAY_HEADINGS = {
    "Ash Wednesday",
    "Monday in Holy Week",
    "Tuesday in Holy Week",
    "Wednesday in Holy Week",
    "Maundy Thursday",
    "Good Friday",
    "Holy Saturday",
    "Monday in Easter Week",
    "Tuesday in Easter Week",
    "Wednesday in Easter Week",
    "Thursday in Easter Week",
    "Friday in Easter Week",
    "Saturday in Easter Week",
}


def collect_heading(line: str) -> bool:
    value = line.strip()
    if value in _COLLECT_HEADING_NAMES or value in _WEEKDAY_HEADINGS:
        return True
    if any(value.startswith(label + " ") for label in _COLLECT_HEADING_NAMES):
        return True
    return bool(re.match(r"^Proper\s+\d+\b", value))


_RUBRIC_PREFIXES = (
    "This Proper ",
    "This Sunday ",
    "The Proper Liturgy ",
    "The Liturgy of the Easter Vigil",
    "When a Vigil of Pentecost",
    "Either of the preceding Collects",
    "On the weekdays which follow",
    "Wednesday, Friday, and Saturday",
    "Monday, Tuesday, and Wednesday",
)


def paragraph_groups(records: list[Record]) -> list[list[Record]]:
    groups: list[list[Record]] = []
    current: list[Record] = []
    for record in records:
        if not record.line.strip() or is_footer(record.line):
            if current:
                groups.append(current)
                current = []
            continue
        current.append(record)
    if current:
        groups.append(current)
    return groups


def is_rubric_group(group: list[Record]) -> bool:
    values = [record.line.strip() for record in group]
    return bool(values) and values[0].startswith(_RUBRIC_PREFIXES)


def extract_collect_alternatives(span: list[Record]) -> list[tuple[str, list[int]]]:
    alternatives: list[list[Record]] = [[]]
    for record in span:
        value = record.line.strip()
        if value in {"or this", "or the following"}:
            alternatives.append([])
        else:
            alternatives[-1].append(record)

    extracted: list[tuple[str, list[int]]] = []
    for alternative in alternatives:
        groups = paragraph_groups(alternative)
        while groups and is_rubric_group(groups[0]):
            groups.pop(0)
        if not groups:
            continue
        selected: list[Record] = []
        for group in groups:
            for record in group:
                selected.append(record)
                if record.line.strip().endswith("Amen."):
                    break
            if selected and selected[-1].line.strip().endswith("Amen."):
                break
        if not selected or not any(record.line.strip().endswith("Amen.") for record in selected):
            raise ValueError("collect alternative has no terminating Amen.")
        extracted.append((folded(record.line for record in selected), sorted({record.page for record in selected})))
    return extracted


def build_collects(pages: list[list[str]]) -> dict[str, dict[str, object]]:
    records = records_for_pages(pages, 211, 245)
    heading_positions = [index for index, record in enumerate(records) if collect_heading(record.line)]
    output: dict[str, dict[str, object]] = {}
    for base_id, label in COLLECT_SPECS:
        matches = [
            index
            for index in heading_positions
            if records[index].line.strip() == label
            or records[index].line.strip().startswith(label + " ")
            or (label.startswith("Proper ") and records[index].line.strip().startswith(label + " "))
        ]
        if len(matches) != 1:
            raise ValueError(f"expected one heading for {label!r}, found {len(matches)}")
        start = matches[0]
        end = next((position for position in heading_positions if position > start), len(records))
        alternatives = extract_collect_alternatives(records[start + 1 : end])
        if not alternatives:
            raise ValueError(f"no collect text for {label!r}")
        preface_lines = [
            record.line.strip()
            for record in records[start + 1 : end]
            if record.line.strip().startswith("Preface of ") or record.line.strip() == "No Proper Preface is used."
        ]
        preface_hint = preface_lines[0] if preface_lines else None
        title = folded([records[start].line])
        for offset, (text, source_pages) in enumerate(alternatives, start=1):
            key = base_id if offset == 1 else f"{base_id}-{offset}"
            item: dict[str, object] = {
                "title": title,
                "text": text,
                "source_pages": source_pages,
            }
            if preface_hint:
                item["preface_hint"] = preface_hint
            output[key] = item
    return output


PREFACE_SPECS = [
    ("lords-day", "1. Of God the Father"),
    ("lords-day", "2. Of God the Son"),
    ("lords-day", "3. Of God the Holy Spirit"),
    ("advent", "Advent"),
    ("incarnation", "Incarnation"),
    ("epiphany", "Epiphany"),
    ("lent", "Lent"),
    ("holy-week", "Holy Week"),
    ("easter", "Easter"),
    ("ascension", "Ascension"),
    ("pentecost", "Pentecost"),
    ("trinity-sunday", "Trinity Sunday"),
    ("all-saints", "All Saints"),
    ("a-saint", "A Saint"),
    ("apostles-and-ordinations", "Apostles and Ordinations"),
    ("dedication-of-a-church", "Dedication of a Church"),
    ("baptism", "Baptism"),
    ("marriage", "Marriage"),
    ("commemoration-of-the-dead", "Commemoration of the Dead"),
]
_PREFACE_HEADINGS = {label for _, label in PREFACE_SPECS}
_PREFACE_BOUNDARY_HEADINGS = _PREFACE_HEADINGS | {"Prefaces for Seasons", "Prefaces for Other Occasions"}


def extract_preface_alternatives(span: list[Record]) -> list[tuple[str, list[int]]]:
    alternatives: list[list[Record]] = [[]]
    for record in span:
        if record.line.strip() in {"or this", "or the following"}:
            alternatives.append([])
        else:
            alternatives[-1].append(record)
    extracted: list[tuple[str, list[int]]] = []
    for alternative in alternatives:
        groups = paragraph_groups(alternative)
        if not groups:
            continue
        # The first record is the text for an entry.  A page footer can make
        # one paragraph appear as two groups, so retain all groups in this
        # alternative and fold their line wraps into one text value.
        text = folded(record.line for group in groups for record in group)
        if text:
            extracted.append((text, sorted({record.page for group in groups for record in group})))
    return extracted


def build_prefaces(pages: list[list[str]]) -> dict[str, dict[str, object]]:
    records = records_for_pages(pages, 377, 382)
    heading_positions = [index for index, record in enumerate(records) if record.line.strip() in _PREFACE_BOUNDARY_HEADINGS]
    output: dict[str, dict[str, object]] = {}
    counters: dict[str, int] = {}
    for base_id, label in PREFACE_SPECS:
        matches = [index for index in heading_positions if records[index].line.strip() == label]
        if len(matches) != 1:
            raise ValueError(f"expected one heading for preface {label!r}, found {len(matches)}")
        start = matches[0]
        end = next((position for position in heading_positions if position > start), len(records))
        alternatives = extract_preface_alternatives(records[start + 1 : end])
        if not alternatives:
            raise ValueError(f"no preface text for {label!r}")
        for offset, (text, source_pages) in enumerate(alternatives, start=1):
            ordinal = counters.get(base_id, 0) + offset
            key = base_id if ordinal == 1 else f"{base_id}-{ordinal}"
            output[key] = {"title": label, "text": text, "source_pages": source_pages}
        counters[base_id] = counters.get(base_id, 0) + len(alternatives)
    return output


PSALM_HEADING_RE = re.compile(r"^\s*(\d{1,3})(?:\s+(.*)|\s*)$")
VERSE_RE = re.compile(r"^\s*(\d{1,3})\s+(.*)$")
SECTION_HEADING_RE = re.compile(
    r"^(?:Aleph|Beth|Gimel|Daleth|He|Waw|Zayin|Heth|Teth|Yodh|Kaph|Lamed|Mem|Nun|Samekh|Ayin|Pe|Tsade|Qoph|Resh|Shin|Tav)\b"
)
DAY_HEADING_RE = re.compile(
    r"^(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth|Sixteenth|Seventeenth|Eighteenth|Nineteenth|Twentieth|Twenty-\w+|Thirtieth) Day:"
)


def nonempty_after(records: list[Record], index: int, count: int = 4) -> list[Record]:
    values: list[Record] = []
    for record in records[index + 1 :]:
        if is_footer(record.line):
            continue
        if record.line.strip():
            values.append(record)
            if len(values) >= count:
                break
    return values


def psalm_heading(records: list[Record], index: int) -> tuple[int, str] | None:
    match = PSALM_HEADING_RE.match(records[index].line)
    if not match:
        return None
    number = int(match.group(1))
    if not 1 <= number <= 150:
        return None
    remainder = (match.group(2) or "").strip()
    lookahead = nonempty_after(records, index, 5)
    if not lookahead:
        return None
    first = lookahead[0].line.strip()
    first_is_verse = bool(VERSE_RE.match(lookahead[0].line) and int(VERSE_RE.match(lookahead[0].line).group(1)) == 1)
    if first_is_verse:
        return number, remainder
    if first.startswith("Part ") and len(lookahead) > 1:
        second_match = VERSE_RE.match(lookahead[1].line)
        if second_match and int(second_match.group(1)) == 1:
            return number, first.split("Part", 1)[1].strip().split(maxsplit=1)[-1]
    if number == 119 and SECTION_HEADING_RE.match(first) and len(lookahead) > 1:
        second_match = VERSE_RE.match(lookahead[1].line)
        if second_match and int(second_match.group(1)) == 1:
            return number, first.split(maxsplit=1)[1] if len(first.split(maxsplit=1)) > 1 else first
    return None


def is_psalm_nontext(line: str) -> bool:
    value = line.strip()
    if not value or is_footer(line):
        return True
    if value.startswith("Psalm ") or value.startswith("Psalms "):
        return True
    if value.startswith("Part I") or value.startswith("Part II"):
        return True
    if DAY_HEADING_RE.match(value) or value in {"Morning Prayer", "Evening Prayer"}:
        return True
    if SECTION_HEADING_RE.match(value):
        return True
    return False


def build_psalms(pages: list[list[str]]) -> dict[str, dict[str, object]]:
    records = records_for_pages(pages, 585, 808)
    starts: list[tuple[int, int, str]] = []
    for index in range(len(records)):
        candidate = psalm_heading(records, index)
        if candidate:
            starts.append((index, candidate[0], candidate[1]))
    starts.sort()
    if len(starts) != 150 or [number for _, number, _ in starts] != list(range(1, 151)):
        raise ValueError(
            "Psalter heading inventory is not exactly Psalms 1 to 150: "
            f"{[number for _, number, _ in starts]}"
        )

    output: dict[str, dict[str, object]] = {}
    for start_offset, (start, number, latin_title) in enumerate(starts):
        end = starts[start_offset + 1][0] if start_offset + 1 < len(starts) else len(records)
        expected = 1
        verses: list[dict[str, object]] = []
        current: list[Record] = []
        current_number: int | None = None
        source_pages: set[int] = set()

        def finish() -> None:
            nonlocal current, current_number
            if current_number is None:
                return
            text_lines: list[str] = []
            for offset, record in enumerate(current):
                if is_psalm_nontext(record.line):
                    continue
                if offset == 0:
                    verse_match = VERSE_RE.match(record.line)
                    if not verse_match:
                        raise ValueError(f"Psalm {number} verse {current_number} lost its numeric marker")
                    text_lines.append(verse_match.group(2))
                else:
                    text_lines.append(record.line)
            joined = folded(text_lines)
            if "*" in joined:
                first, second = joined.split("*", 1)
                asterisk: str | None = "*"
            else:
                # A small number of BCP verses intentionally have no printed
                # asterisk.  Keep the complete verse in ``first`` and expose
                # the missing marker instead of manufacturing a half-verse.
                first, second = joined, ""
                asterisk = None
            verses.append(
                {
                    "number": current_number,
                    "first": first.strip(),
                    "second": second.strip(),
                    "asterisk": asterisk,
                }
            )
            current = []
            current_number = None

        for record in records[start + 1 : end]:
            match = VERSE_RE.match(record.line)
            if match and int(match.group(1)) == expected:
                finish()
                current_number = expected
                expected += 1
                current = [record]
                source_pages.add(record.page)
            elif current_number is not None:
                current.append(record)
                if not is_psalm_nontext(record.line):
                    source_pages.add(record.page)
        finish()
        actual_numbers = [verse["number"] for verse in verses]
        if actual_numbers != list(range(1, expected)):
            raise ValueError(f"Psalm {number} verse sequence is not contiguous: {actual_numbers}")
        if not verses:
            raise ValueError(f"Psalm {number} has no verses")
        output[str(number)] = {
            "number": number,
            "latin_title": latin_title,
            "verses": verses,
            "source_pages": sorted(source_pages),
        }
    return output


def build_library(pdf: Path) -> dict[str, object]:
    digest = sha256(pdf)
    if digest != KNOWN_PDF_SHA256:
        raise ValueError(
            f"unrecognized BCP PDF SHA-256 {digest}; expected the verified official source {KNOWN_PDF_SHA256}"
        )
    pages = extract_pages(pdf)
    if len(pages) < 808:
        raise ValueError(f"source PDF yielded only {len(pages)} pages")
    return {
        "schema_version": 1,
        "source": {
            "title": SOURCE_TITLE,
            "url": SOURCE_URL,
            "pdf_sha256": digest,
            "edition": EDITION,
            "verified_on": VERIFIED_ON,
        },
        "collects": build_collects(pages),
        "prefaces": build_prefaces(pages),
        "psalms": build_psalms(pages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True, help="verified 1979 BCP PDF")
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for bcp1979/sunday.json")
    args = parser.parse_args()
    library = build_library(args.pdf)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "sunday.json"
    output_path.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path), "sha256": sha256(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
