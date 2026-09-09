"""Small offline lookup for verified BCP Sunday worship text.

The library supplies text for an already selected occasion or passage. It
never decides the calendar, lectionary track, or parish's worship choices.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path


RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "bcp1979"


class SundayLibraryError(ValueError):
    pass


def _read_data() -> dict:
    path = RESOURCE_DIR / "sunday.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = json.loads((RESOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
        expected = manifest["data"]["sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Bundled Sunday text differs from its verified release")
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SundayLibraryError("The bundled Sunday library is missing or changed. Restore the verified plugin release before using its text.") from exc


def verify_shipped_liturgy(identifier: str, *, plugin_root: Path | None = None) -> None:
    """Check release integrity for registered standard worship text."""
    root = plugin_root or Path(__file__).resolve().parents[2]
    resource = root / "skills/bulletin/resources/bcp1979/manifest.json"
    try:
        manifest = json.loads(resource.read_text(encoding="utf-8"))
        entry = manifest["liturgy"].get(identifier)
        if entry is None:
            return  # Other public or church-owned units retain their own checks.
        path = root / "skills/bulletin/renderer/liturgy" / f"{identifier}.md"
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Changed standard worship text")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SundayLibraryError(f"The bundled {identifier} source is missing or changed. Restore the verified plugin release; the pastor does not need to locate a replacement source.") from exc


def catalog(category: str) -> dict:
    if category not in ("collects", "prefaces", "psalms"):
        raise SundayLibraryError("Choose collects, prefaces, or psalms")
    data = _read_data()
    return {key: {"title": item.get("title", item.get("latin_title", f"Psalm {key}")),
                  "source_pages": item["source_pages"]}
            for key, item in data[category].items()}


def _verse_numbers(expression: str, available: list[int]) -> list[int]:
    selected = []
    for part in expression.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not match:
            raise SundayLibraryError("Use verse numbers such as 1-6 or 1-4,8-10")
        start, end = int(match[1]), int(match[2] or match[1])
        if start > end or end - start > 176:
            raise SundayLibraryError("Use ascending verse ranges within the selected psalm")
        selected.extend(range(start, end + 1))
    if not selected or len(set(selected)) != len(selected) or selected != sorted(selected) or any(n not in available for n in selected):
        raise SundayLibraryError("The verse selection must be ordered, unique, and present in this psalm")
    return selected


def lookup(category: str, identifier: str, *, verses: str | None = None,
           psalm_format: str = "responsive_half_verse", response_start: str = "second") -> dict:
    if category not in ("collects", "prefaces", "psalms"):
        raise SundayLibraryError("Choose collects, prefaces, or psalms")
    data = _read_data()
    if str(identifier) not in data[category]:
        raise SundayLibraryError(f"No bundled {category} entry named {identifier}. List the available entries first.")
    item = copy.deepcopy(data[category][str(identifier)])
    source = data["source"]
    pages = item["source_pages"]
    item["source"] = {
        "label": f"{source['title']}, pp. {', '.join(str(p) for p in pages)}",
        "location": f"{source['url']}#page={pages[0]}",
        "verified_on": source["verified_on"],
        "library_id": f"bcp1979/{category}/{identifier}",
    }
    if category != "psalms":
        if verses is not None:
            raise SundayLibraryError("Verse selection applies only to psalms")
        return item
    if psalm_format not in ("responsive_half_verse", "responsive_whole_verse", "unison", "plain") or response_start not in ("first", "second"):
        raise SundayLibraryError("Choose a supported psalm response pattern")
    available = [int(v["number"]) for v in item["verses"]]
    selected = _verse_numbers(verses, available) if verses else available
    shaped = [v for v in item["verses"] if int(v["number"]) in selected]
    if psalm_format != "responsive_half_verse":
        shaped = [{"number": v["number"], "text": (v["first"] + (" * " + v["second"] if v["second"] else ""))} for v in shaped]
    item.update(format=psalm_format, response_start=response_start, verses=shaped)
    item["text"] = "\n\n".join(f"{v['number']} " +
                               ((v["first"] + (" * " + v["second"] if v["second"] else "")) if psalm_format == "responsive_half_verse" else v["text"])
                               for v in shaped)
    return item
