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


def _matches_release(path: Path, expected: str) -> bool:
    """Whether a shipped text file is the released one.

    Git on Windows can rewrite line endings when it downloads the plugin. That
    changes the bytes and not the words, so the text is also checked with
    Windows line endings turned back.
    """
    data = path.read_bytes()
    return expected in (hashlib.sha256(data).hexdigest(),
                        hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest())


# The library ships in parts so no file reaches the plugin directory's 256 KiB
# limit. Each part has the same shape as the whole library with some entries;
# merged in manifest order they give back the whole library.
PART_LIMIT_BYTES = 256 * 1024
_CATEGORIES = ("collects", "prefaces", "psalms")
_PARTS = (
    ("sunday-collects-prefaces.json", lambda key, number: key in ("collects", "prefaces")),
    ("sunday-psalms-1-75.json", lambda key, number: key == "psalms" and number <= 75),
    ("sunday-psalms-76-150.json", lambda key, number: key == "psalms" and number > 75),
)


def split_library(data: dict) -> list[tuple[str, dict]]:
    """Divide the whole library into the parts the plugin ships."""
    parts = []
    for name, belongs in _PARTS:
        part: dict = {"schema_version": data["schema_version"]}
        if name == _PARTS[0][0]:
            part["source"] = data["source"]
        for category in _CATEGORIES:
            entries = {key: value for key, value in data[category].items()
                       if belongs(category, int(key) if category == "psalms" else 0)}
            if entries:
                part[category] = entries
        parts.append((name, part))
    placed = sum(len(part.get(category, {})) for _, part in parts for category in _CATEGORIES)
    if placed != sum(len(data[category]) for category in _CATEGORIES):
        raise ValueError("Every Sunday library entry must belong to exactly one part")
    return parts


def merge_parts(parts: list[dict]) -> dict:
    """Join library parts, in order, back into the whole library."""
    data: dict = {}
    for part in parts:
        if not isinstance(part, dict) or part.get("schema_version") != 1:
            raise ValueError("A Sunday library part has an unsupported format")
        for key, value in part.items():
            if key == "schema_version":
                data[key] = value
            elif key in _CATEGORIES:
                merged = data.setdefault(key, {})
                if not isinstance(value, dict) or set(merged) & set(value):
                    raise ValueError("Sunday library parts overlap")
                merged.update(value)
            elif key == "source" and key not in data:
                data[key] = value
            else:
                raise ValueError(f"Unexpected Sunday library entry {key!r}")
    if set(data) != {"schema_version", "source", *_CATEGORIES}:
        raise ValueError("The Sunday library parts are incomplete")
    return {key: data[key] for key in ("schema_version", "source", *_CATEGORIES)}


def part_paths(resource_dir: Path = RESOURCE_DIR) -> list[tuple[Path, str]]:
    """The shipped part files with the fingerprint the manifest records for each."""
    manifest = json.loads((resource_dir / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["data"]["parts"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("The manifest lists no Sunday library parts")
    found = []
    for entry in entries:
        name = entry["file"]
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".json"):
            raise ValueError("A Sunday library part must be a JSON file in its own folder")
        found.append((resource_dir / name, entry["sha256"]))
    return found


def read_library(resource_dir: Path = RESOURCE_DIR) -> dict:
    """The whole verified Sunday library, each part checked against the manifest."""
    try:
        parts = []
        for path, expected in part_paths(resource_dir):
            if not _matches_release(path, expected):
                raise ValueError("Bundled Sunday text differs from its verified release")
            parts.append(json.loads(path.read_text(encoding="utf-8")))
        return merge_parts(parts)
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
        if not _matches_release(path, entry["sha256"]):
            raise ValueError("Changed standard worship text")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SundayLibraryError(f"The bundled {identifier} source is missing or changed. Restore the verified plugin release; the pastor does not need to locate a replacement source.") from exc


def catalog(category: str) -> dict:
    if category not in ("collects", "prefaces", "psalms"):
        raise SundayLibraryError("Choose collects, prefaces, or psalms")
    data = read_library()
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
    data = read_library()
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
