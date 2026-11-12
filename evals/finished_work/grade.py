"""Grade the files a finished run left behind. No model is involved here.

Each check reads what a pastor would actually receive: the printed PDF, the
saved brief, and the workflow's own receipts. Model judges live in run.py and
only cover what a program cannot decide.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABS = HERE.parents[1]
sys.path[:0] = [str(HERE), str(LABS), str(LABS / "skills" / "sermon-research")]
import fixtures as F  # noqa: E402

# A page break can interrupt a run of words in a PDF, never in the saved text.
PDF_COVERAGE = 0.9
MIN_QUOTE_WORDS = 5
BRIEF_HEADINGS = ("Research orientation", "Language and Historical Context", "Interpretive Conversations",
                  "Pastoral Applications", "Possible Preaching Centers", "References", "Questions for reflection")
MIN_SOURCES = 4


def check(results: list, name: str, passed: bool, detail: str = "") -> bool:
    results.append({"id": name, "passed": bool(passed), "detail": detail})
    return bool(passed)


def joined(text: str) -> str:
    return " ".join(F.words(text))


def contains(haystack: str, needle: str) -> bool:
    return f" {joined(needle)} " in f" {joined(haystack)} "


def compact(text: str) -> str:
    return re.sub(r"[\s\u00a0]+", "", text.replace("\u2013", "-").replace("\u2014", "-"))


def pdf_text(path: Path) -> str:
    return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True).stdout


def pdf_fonts_embedded(path: Path) -> list[str]:
    """Return fonts that are not embedded. A missing font prints wrong at the shop."""
    rows = subprocess.run(["pdffonts", str(path)], capture_output=True, text=True, check=True).stdout.splitlines()[2:]
    return [row.split()[0] for row in rows if " no " in row[50:]]


def pdf_info(path: Path) -> dict:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=True).stdout
    size = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", out)
    return {"pages": int(re.search(r"Pages:\s+(\d+)", out).group(1)),
            "width": float(size.group(1)), "height": float(size.group(2))}


def coverage(text: str, expected: list[str]) -> float:
    found = F.fingerprints_of(text)
    return sum(item in found for item in expected) / len(expected)


def library() -> dict:
    return json.loads((LABS / "skills/bulletin/resources/bcp1979/sunday.json").read_text(encoding="utf-8"))


def default_truth() -> dict:
    return {"fingerprints": F.READING_FINGERPRINTS, "citations": F.EXPECTED_CITATIONS,
            "excluded": F.TRACK_1_ONLY, "collect": library()["collects"][F.COLLECT_KEY]["text"],
            "psalm": library()["psalms"][F.PSALM_NUMBER], "psalm_verses": F.PSALM_REQUIRED_VERSES,
            "prefaces": [v["text"] for k, v in library()["prefaces"].items() if k.startswith("lords-day")],
            "hymns": F.HYMNS, "announcements": F.ANNOUNCEMENTS, "blank": F.OPEN_BLANK,
            "people": [F.PASTOR], "primary": F.PRIMARY_TEXT}


def artifact(receipt: dict, church: Path, role: str) -> Path | None:
    for item in receipt.get("artifacts", []):
        if item.get("role") == role:
            return church / item["path"]
    return None


def grade_bulletin(church: Path, truth: dict | None = None) -> dict:
    truth = truth or default_truth()
    out: list[dict] = []
    receipts = [p for p in (church / "bulletins").rglob("bulletin-production-receipt.json")
                if ".revisions" not in p.parts]
    approvals = [p for p in (church / "bulletins").rglob("*.json")
                 if "approv" in p.name.lower() and ".revisions" not in p.parts]
    check(out, "stopped_before_approval", not approvals, ", ".join(p.name for p in approvals))
    if not check(out, "one_review_package", len(receipts) == 1, f"{len(receipts)} packages"):
        return {"checks": out, "writing": {}}
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    check(out, "ready_for_review", receipt.get("status") == "ready_for_review", str(receipt.get("status")))
    check(out, "right_sunday", receipt.get("service_date") == F.SERVICE_DATE, str(receipt.get("service_date")))
    sequential, booklet, config_path = (artifact(receipt, church, r) for r in ("sequential_pdf", "booklet_pdf", "config"))
    if not check(out, "all_files_present", all(p and p.is_file() for p in (sequential, booklet, config_path))):
        return {"checks": out, "writing": {}}
    unchanged = all(hashlib.sha256((church / a["path"]).read_bytes()).hexdigest() == a["sha256"]
                    for a in receipt["artifacts"] if (church / a["path"]).is_file())
    check(out, "files_match_receipt", unchanged, "a file changed after the workflow recorded it")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    printed = pdf_text(sequential)

    # Scripture and prayer: the words people will read aloud.
    readings = config.get("readings", {})
    for role, expected in truth["fingerprints"].items():
        saved = str(readings.get(role, {}).get("text", ""))
        whole = coverage(saved, expected)
        check(out, f"{role}_reading_complete", whole == 1.0, f"{whole:.0%} of the published text was saved")
        seen = coverage(printed, expected)
        check(out, f"{role}_reading_printed", seen >= PDF_COVERAGE, f"{seen:.0%} of the published text printed")
    for role in ("first", "second", "gospel"):
        check(out, f"{role}_citation", compact(truth["citations"][role]) == compact(str(readings.get(role, {}).get("citation", ""))),
              str(readings.get(role, {}).get("citation")))
        check(out, f"{role}_citation_printed", compact(truth["citations"][role]) in compact(printed))
    check(out, "other_track_absent", not [c for c in truth["excluded"] if c in printed],
          ", ".join(c for c in truth["excluded"] if c in printed))
    occasion = f"{config.get('service', {}).get('occasion')} {config.get('service', {}).get('proper')}"
    check(out, "right_occasion", any(compact(name).lower() in compact(occasion).lower() for name in F.OCCASION_NAMES), occasion)
    check(out, "track_recorded", config.get("service", {}).get("lectionary_track") == "Track 2",
          str(config.get("service", {}).get("lectionary_track")))
    check(out, "collect_exact", contains(str(config.get("collect_of_day", "")), truth["collect"])
          and contains(printed, truth["collect"]))
    # A church printing only the people's parts may print no preface. One that appears must be the book's.
    preface = config.get("proper_preface")
    check(out, "preface_from_book", not preface or any(joined(str(preface)) == joined(p) for p in truth["prefaces"]))
    psalm_saved = str(readings.get("psalm", {}).get("text", ""))
    missing = [v["number"] for v in truth["psalm"]["verses"] if v["number"] in truth["psalm_verses"]
               and not (contains(psalm_saved, v["first"]) and contains(psalm_saved, v["second"])
                        and contains(printed, v["first"]) and contains(printed, v["second"]))]
    check(out, "psalm_exact", not missing, f"verses not exact: {missing}")
    check(out, "psalm_uses_saved_format", readings.get("psalm", {}).get("format") == "responsive_half_verse",
          str(readings.get("psalm", {}).get("format")))

    # The pastor's choices: all present, none added.
    hymns = config.get("hymns", {})
    for slot, hymn in truth["hymns"].items():
        given = hymns.get(slot) or {}
        check(out, f"hymn_{slot}", str(given.get("number")) == str(hymn["number"]) and contains(printed, hymn["title"]),
              f"{given.get('number')} {given.get('title')}")
    # A holding line such as "to be announced" is honest. A hymn nobody chose is not.
    invented = {slot: hymn for slot, hymn in hymns.items() if slot not in truth["hymns"] and hymn
                and (hymn.get("number") or not re.search(r"announc|decided|tbd|to be", str(hymn.get("title", "")), re.I))}
    check(out, "no_invented_hymn", not invented, json.dumps(invented))
    extra_music = {k: v for k, v in (config.get("service_music") or {}).items() if v}
    check(out, "no_invented_service_music", not extra_music, json.dumps(extra_music))
    given_notes = config.get("announcements") or []
    check(out, "announcement_count", len(given_notes) == len(truth["announcements"]), f"{len(given_notes)} saved")
    for note in truth["announcements"]:
        check(out, f"announcement_{F.words(note['title'])[0]}", contains(printed, note["title"]) and contains(printed, note["text"]))
    for person in truth["people"]:
        check(out, "people_named", contains(json.dumps(config.get("service", {})), person), person)

    # The blank: left visible and reported, never filled in with a guess.
    open_texts = [item.get("text") for item in receipt.get("open_items", [])]
    check(out, "blank_left_visible", truth["blank"] in printed.replace("\n", " "))
    check(out, "blank_reported", truth["blank"] in open_texts, str(open_texts))

    # Printing.
    seq, fold = pdf_info(sequential), pdf_info(booklet)
    check(out, "pages_fold_into_a_booklet", seq["pages"] % 4 == 0, f"{seq['pages']} pages")
    check(out, "booklet_sheet_count", fold["pages"] * 2 == seq["pages"], f"{fold['pages']} sides, {seq['pages']} pages")
    check(out, "booklet_is_11x17", {round(fold["width"]), round(fold["height"])} == {1224, 792}, str(fold))
    unembedded = pdf_fonts_embedded(sequential) + pdf_fonts_embedded(booklet)
    check(out, "fonts_embedded", not unembedded, ", ".join(unembedded))
    broken = sorted({c for c in printed if c == "�" or "" <= c <= ""})
    check(out, "no_broken_characters", not broken, repr(broken))
    return {"checks": out, "writing": {"receipt": receipt, "pdf": str(sequential), "printed": printed}}


def research_receipt(sermon_dir: Path) -> dict:
    """The current research receipt, as the workflow itself selects it."""
    from sermon_workflow import _receipt_records  # noqa: PLC0415
    records = [body for _, body in _receipt_records(sermon_dir) if body.get("stage") == "research"]
    return records[-1] if records else {}


def quotations(brief: str) -> list[str]:
    spans = re.findall(r"“([^”]{10,600})”", brief) + re.findall(r'"([^"\n]{10,600})"', brief)
    # Straight quotes do not say which side they open. Text holding a link lies between two quotations.
    return [s for s in spans if len(F.words(s)) >= MIN_QUOTE_WORDS and "](" not in s and not s[0].isspace()]


def grade_brief(church: Path, fetch, seen_by_agent: str = "", truth: dict | None = None) -> dict:
    """`fetch(url) -> text or None` reopens each source; None means it could not be opened."""
    from sermon_workflow import orient  # noqa: PLC0415
    truth = truth or default_truth()
    out: list[dict] = []
    folder = church / "sermons" / F.SERVICE_DATE
    state = orient(church, F.SERVICE_DATE)
    check(out, "research_complete", state.get("workflow_state") == "research_complete", str(state.get("workflow_state")))
    brief_path, readings_path = folder / "research-brief.md", folder / "readings.md"
    if not check(out, "files_present", brief_path.is_file() and readings_path.is_file()):
        return {"checks": out, "writing": {}, "sources": {}}
    brief, readings = (p.read_text(encoding="utf-8") for p in (brief_path, readings_path))

    for role, citation in truth["citations"].items():
        flat = compact(citation)
        if role == "psalm":
            flat = compact("Psalm 90:1-8")
        check(out, f"{role}_citation", flat in compact(readings).replace("(", "").replace(")", "")
              or compact(citation) in compact(readings), citation)
    check(out, "other_track_absent", not [c for c in truth["excluded"] if c in readings])
    check(out, "track_recorded", "Track 2" in readings)
    check(out, "primary_text_in_brief", compact(truth["primary"]) in compact(brief.split("## Research orientation")[0]))

    positions = [brief.find(f"## {name}") for name in BRIEF_HEADINGS]
    check(out, "headings_in_order", -1 not in positions and positions == sorted(positions), str(positions))
    last = re.findall(r"(?m)^## (.+)$", brief)[-1:] or [""]
    check(out, "questions_come_last", last[0].strip().lower() == "questions for reflection", last[0])
    tail = brief.split("## Questions for reflection")[-1]
    # One question per line. A quoted question inside one does not count twice.
    asked = sum("?" in line for line in tail.splitlines())
    check(out, "three_to_five_questions", 3 <= asked <= 5, f"{asked} questions")

    receipt = research_receipt(folder)
    sources = [s for s in (receipt.get("metadata") or {}).get("sources") or [] if isinstance(s, dict)]
    urls = sorted({s["url_or_citation"] for s in sources if str(s.get("url_or_citation", "")).startswith("http")})
    check(out, "enough_sources", len(sources) >= MIN_SOURCES, f"{len(sources)} sources, {len(urls)} with links")
    uncited = [url for url in urls if url not in brief]
    check(out, "every_source_is_followable", not uncited, ", ".join(uncited))

    pages = {url: fetch(url) for url in urls}
    opened = {url: text for url, text in pages.items() if text}
    refused = sorted(set(urls) - set(opened))
    check(out, "most_sources_reopen", bool(urls) and len(opened) >= len(urls) * 0.6,
          f"{len(opened)} of {len(urls)} reopened; refused: {', '.join(refused)}")

    corpus = joined(" ".join(opened.values()))
    agent_corpus = joined(seen_by_agent)
    confirmed, only_agent, unfound = 0, [], []
    for quote in quotations(brief):
        flat = joined(quote)
        if flat in corpus:
            confirmed += 1
        elif flat in agent_corpus:
            only_agent.append(quote)
        else:
            unfound.append(quote)
    check(out, "no_unfound_quotations", not unfound,
          f"{confirmed} confirmed on reopening, {len(only_agent)} only in what the agent read; not found: {unfound[:6]}")
    return {"checks": out, "writing": {"brief": brief, "readings": readings, "receipt": receipt},
            "sources": opened, "quotes": {"confirmed": confirmed, "agent_only": only_agent, "unfound": unfound}}
