#!/usr/bin/env python3
"""Sermon reflection: the pastor writes, the agent edits.

    orient        where this sermon stands and what comes next (read-only)
    open          open the pastor's reflection page and record where they write
    done          record that the pastor has finished writing
    record        save the agent's light edit as sermon.md
    speaker-copy  render sermon.md as a large-type PDF for the pulpit

The pastor owns reflections.md. This script never changes it after the
pastor starts writing, except to bring in writing the pastor did elsewhere,
which it adds to the end. State lives in
sermons/<date>/.receipts/reflection/state.json.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
RESEARCH_DIR = SKILL_DIR.parent / "sermon-research"

PAGE = "reflections.md"
SERMON = "sermon.md"
SPEAKER_COPY = "sermon-speaker-copy.pdf"
WHERE = ("in_app", "elsewhere")


class Blocked(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _church_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir() or not (root / "church.yaml").is_file():
        raise Blocked("uninitialized_church_folder", f"Church folder is not initialized: {root}")
    return root


def _sermon_dir(root: Path, service_date: str) -> Path:
    try:
        date.fromisoformat(service_date)
    except ValueError as exc:
        raise Blocked("invalid_date", str(exc)) from exc
    return root / "sermons" / service_date


def _state_path(sermon_dir: Path) -> Path:
    return sermon_dir / ".receipts" / "reflection" / "state.json"


def _load(sermon_dir: Path) -> dict:
    path = _state_path(sermon_dir)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"where": None, "place": None, "opened_at": None, "done": None, "edit": None, "log": []}


def _save(sermon_dir: Path, state: dict) -> None:
    path = _state_path(sermon_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _log(state: dict, message: str) -> None:
    state["log"].append({"at": _now(), "event": message})


def _read_text(path: str) -> str:
    text = Path(path).expanduser().read_text(encoding="utf-8")
    if not text.strip():
        raise Blocked("empty_content", f"{path} is empty.")
    return text


def _research_state(root: Path, service_date: str) -> str:
    """Report the research workflow's state without depending on it."""
    try:
        sys.path.insert(0, str(RESEARCH_DIR))
        from sermon_workflow import orient as research_orient  # noqa: E402
        result = research_orient(root, service_date)
        return result.get("workflow_state") or "unknown"
    except Exception:  # research is helpful context, never a requirement
        return "unknown"


# How much of the edited sermon is still in the pastor's own words: the share
# of its words that sit in a run of three or more words also found on the
# pastor's page. Word runs survive reordering, trimming, and light rewording;
# a rewrite in someone else's words shares few of them. Calibrated on a
# preached sermon: its light edit scored 0.54 against the pastor's raw draft,
# and an agent's rewrite of the same draft scored 0.13. It is reported, never
# enforced.
RUN = 3
LIGHT_EDIT_FLOOR = 0.30


def _words(text: str) -> list[str]:
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    return re.findall(r"[a-z0-9']+", text.lower().replace("\u2019", "'"))


def kept_from_pastor(page_text: str, sermon_text: str) -> dict:
    page, sermon = _words(page_text), _words(sermon_text)
    runs = {tuple(page[i:i + RUN]) for i in range(len(page) - RUN + 1)}
    kept = [False] * len(sermon)
    for i in range(len(sermon) - RUN + 1):
        if tuple(sermon[i:i + RUN]) in runs:
            kept[i:i + RUN] = [True] * RUN
    share = round(sum(kept) / len(sermon), 2) if sermon else 0.0
    return {"words": len(sermon), "kept": sum(kept), "share": share}


def _workflow_state(sermon_dir: Path, state: dict) -> tuple[str, list[str], list[dict]]:
    page = sermon_dir / PAGE
    sermon = sermon_dir / SERMON
    warnings: list[dict] = []
    if not page.is_file() and not state["opened_at"]:
        return "draw_out", ["draw_out", "open_page"], warnings
    if not page.is_file():
        if state["where"] == "elsewhere":
            return "pastor_writing", [], warnings
        warnings.append({"code": "page_missing", "message": f"{PAGE} was opened but is no longer in the sermon folder."})
        return "draw_out", ["open_page"], warnings
    done = state["done"]
    if not done:
        return "pastor_writing", [], warnings
    if _sha256(page) != done["sha256"]:
        warnings.append({"code": "page_changed_after_done",
                         "message": "The pastor changed the page after saying done. Ask whether they are finished, then record done again."})
        return "pastor_writing", [], warnings
    edit = state["edit"]
    if not edit or edit["based_on"] != done["sha256"] or not sermon.is_file():
        return "ready_to_edit", ["edit"], warnings
    if _sha256(sermon) != edit["sha256"]:
        warnings.append({"code": "pastor_edited_sermon",
                         "message": f"The pastor has changed {SERMON} since the edit. Their changes stand."})
    return "edited", ["speaker_copy"], warnings


def orient(root: Path, service_date: str) -> dict:
    sermon_dir = _sermon_dir(root, service_date)
    state = _load(sermon_dir)
    workflow_state, next_actions, warnings = _workflow_state(sermon_dir, state)
    research = _research_state(root, service_date)
    if research != "research_complete":
        warnings.append({"code": "research_not_complete",
                         "message": "There is no finished research brief for this date. Reflection can go ahead if the pastor wants it."})
    files = {name: (sermon_dir / name).is_file() for name in ("research-brief.md", PAGE, SERMON, SPEAKER_COPY)}
    return {"status": "ok", "service_date": service_date, "workflow_state": workflow_state,
            "next_actions": next_actions, "research_state": research, "where": state["where"],
            "place": state["place"], "purpose": (state["done"] or {}).get("purpose"),
            "kept_from_pastor": (state["edit"] or {}).get("kept_from_pastor"),
            "files": files, "warnings": warnings}


def open_page(root: Path, service_date: str, where: str, place: str | None, seed_file: str | None) -> dict:
    sermon_dir = _sermon_dir(root, service_date)
    if where == "elsewhere" and not place:
        raise Blocked("place_missing", "Say where the pastor will write, for example their notes app.")
    state = _load(sermon_dir)
    page = sermon_dir / PAGE
    created = False
    if where == "in_app" and not page.is_file():
        sermon_dir.mkdir(parents=True, exist_ok=True)
        seed = _read_text(seed_file) if seed_file else f"# Reflections for {service_date}\n\n"
        page.write_text(seed if seed.endswith("\n") else seed + "\n", encoding="utf-8")
        created = True
    state.update(where=where, place=place, opened_at=state["opened_at"] or _now())
    _log(state, f"Page opened ({where}{': ' + place if place else ''}).")
    _save(sermon_dir, state)
    return {"status": "ok", "page": str(page), "created": created, "where": where, "place": place,
            "message": ("The pastor's page is ready. It belongs to the pastor; do not change it."
                        if created else "The pastor's page already exists and was left as it is.")}


def done(root: Path, service_date: str, from_file: str | None, purpose: str | None) -> dict:
    sermon_dir = _sermon_dir(root, service_date)
    state = _load(sermon_dir)
    page = sermon_dir / PAGE
    if from_file:
        writing = _read_text(from_file).strip() + "\n"
        sermon_dir.mkdir(parents=True, exist_ok=True)
        if page.is_file() and page.read_text(encoding="utf-8").strip():
            existing = page.read_text(encoding="utf-8").rstrip("\n")
            page.write_text(existing + "\n\n---\n\n" + writing, encoding="utf-8")
        else:
            page.write_text(writing, encoding="utf-8")
        _log(state, "Brought in the pastor's writing from elsewhere.")
    if not page.is_file() or not page.read_text(encoding="utf-8").strip():
        raise Blocked("page_empty", f"There is nothing on the pastor's page yet ({PAGE}).")
    state["opened_at"] = state["opened_at"] or _now()
    state["done"] = {"at": _now(), "sha256": _sha256(page),
                     "purpose": purpose or (state["done"] or {}).get("purpose")}
    _log(state, "Pastor said done.")
    _save(sermon_dir, state)
    return {"status": "ok", "workflow_state": "ready_to_edit", "page": str(page),
            "purpose": state["done"]["purpose"]}


def record(root: Path, service_date: str, content_file: str, replace: bool) -> dict:
    sermon_dir = _sermon_dir(root, service_date)
    state = _load(sermon_dir)
    workflow_state, _, warnings = _workflow_state(sermon_dir, state)
    if workflow_state not in {"ready_to_edit", "edited"}:
        if any(w["code"] == "page_changed_after_done" for w in warnings):
            raise Blocked("page_changed_after_done", warnings[0]["message"])
        raise Blocked("pastor_not_done", "Edit only after the pastor says they are done writing.")
    content = _read_text(content_file)
    sermon = sermon_dir / SERMON
    previous = None
    if sermon.is_file():
        edit = state["edit"]
        pastor_changed = not edit or _sha256(sermon) != edit["sha256"]
        if pastor_changed and not replace:
            raise Blocked("sermon_changed_by_pastor",
                          f"{SERMON} has changes the pastor made. Ask before replacing it, then pass --replace.")
        versions = sermon_dir / ".versions"
        versions.mkdir(exist_ok=True)
        previous = versions / f"sermon-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        previous.write_bytes(sermon.read_bytes())
    sermon.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    page_text = (sermon_dir / PAGE).read_text(encoding="utf-8")
    kept = kept_from_pastor(page_text, content)
    state["edit"] = {"at": _now(), "sha256": _sha256(sermon), "based_on": state["done"]["sha256"],
                     "kept_from_pastor": kept}
    _log(state, f"Edit saved; {kept['share']:.0%} of its words are the pastor's own.")
    _save(sermon_dir, state)
    result = {"status": "ok", "workflow_state": "edited", "sermon": str(sermon), "kept_from_pastor": kept}
    if previous:
        result["previous_version"] = str(previous)
    if kept["words"] and kept["share"] < LIGHT_EDIT_FLOOR:
        result["warnings"] = [{"code": "mostly_rewritten",
                               "message": "Little of the sermon is still in the pastor's own words. Check that the edit stayed light."}]
    return result


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)


def speaker_copy_html(markdown: str, service_date: str, size: int = 16) -> str:
    markdown = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.S).strip()
    title, blocks = "Sermon", []
    for block in re.split(r"\n\s*\n", markdown):
        block = block.strip()
        if not block:
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", block)
        if heading and len(heading.group(1)) == 1 and title == "Sermon" and not blocks:
            title = heading.group(2).strip()
        elif heading:
            blocks.append(f"<h2>{_inline(heading.group(2).strip())}</h2>")
        elif block.startswith(">"):
            quote = " ".join(line.lstrip("> ").strip() for line in block.splitlines())
            blocks.append(f"<blockquote>{_inline(quote)}</blockquote>")
        elif re.match(r"^\*\*Text:\*\*", block) and len(blocks) < 2:
            blocks.append(f'<p class="meta">{_inline(block)}</p>')
        else:
            blocks.append(f"<p>{_inline(' '.join(block.splitlines()))}</p>")
    day = date.fromisoformat(service_date)
    when = f"{day:%B} {day.day}, {day.year}"
    body = "\n".join(blocks)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: letter; margin: 0.9in 1in 0.9in 1.2in;
  @bottom-left {{ content: "{html.escape(title)}"; font: italic 11pt Charter, 'Iowan Old Style', Georgia, serif; color: #555; }}
  @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font: 11pt Charter, 'Iowan Old Style', Georgia, serif; color: #555; }} }}
body {{ font-family: Charter, 'Iowan Old Style', Georgia, 'Times New Roman', serif; font-size: {size}pt; line-height: 1.55; color: #000; }}
h1 {{ font-size: {size + 8}pt; margin: 0 0 4pt; }}
.date {{ font-size: 12pt; color: #444; margin: 0 0 20pt; padding-bottom: 10pt; border-bottom: 1px solid #999; }}
h2 {{ font-size: {size + 2}pt; margin: 18pt 0 8pt; break-after: avoid; }}
p {{ margin: 0 0 14pt; orphans: 3; widows: 3; }}
p.meta {{ font-size: 12pt; color: #444; }}
blockquote {{ margin: 0 0 14pt 0.4in; font-style: italic; }}
p:last-child {{ break-before: avoid; }}
</style></head><body><h1>{_inline(title)}</h1><div class="date">{when}</div>
{body}
</body></html>"""


def speaker_copy(root: Path, service_date: str, size: int) -> dict:
    sermon_dir = _sermon_dir(root, service_date)
    sermon = sermon_dir / SERMON
    if not sermon.is_file():
        raise Blocked("sermon_missing", f"There is no {SERMON} for {service_date} yet.")
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise Blocked("pdf_runtime_missing",
                      "The PDF tools are not installed on this computer yet. The sermon is ready as sermon.md; "
                      "set up the PDF tools the way the bulletin setup does, then try again.") from exc
    out = sermon_dir / SPEAKER_COPY
    document = HTML(string=speaker_copy_html(sermon.read_text(encoding="utf-8"), service_date, size)).render()
    document.write_pdf(out)
    return {"status": "ok", "speaker_copy": str(out), "pages": len(document.pages),
            "message": "Print it one-sided so the pages slide at the pulpit."}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("orient", "open", "done", "record", "speaker-copy"):
        command = sub.add_parser(name)
        command.add_argument("--church-folder", required=True)
        command.add_argument("--date", required=True)
        if name == "open":
            command.add_argument("--where", choices=WHERE, default="in_app")
            command.add_argument("--place")
            command.add_argument("--seed-file")
        if name == "done":
            command.add_argument("--from-file")
            command.add_argument("--purpose")
        if name == "record":
            command.add_argument("--content-file", required=True)
            command.add_argument("--replace", action="store_true")
        if name == "speaker-copy":
            command.add_argument("--size", type=int, default=16, choices=range(12, 25))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _church_root(args.church_folder)
        if args.command == "orient":
            result = orient(root, args.date)
        elif args.command == "open":
            result = open_page(root, args.date, args.where, args.place, args.seed_file)
        elif args.command == "done":
            result = done(root, args.date, args.from_file, args.purpose)
        elif args.command == "record":
            result = record(root, args.date, args.content_file, args.replace)
        else:
            result = speaker_copy(root, args.date, args.size)
    except Blocked as exc:
        result = {"status": "blocked", "code": exc.code, "message": exc.message}
    except OSError as exc:
        result = {"status": "failed", "code": "file_error", "message": str(exc)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
