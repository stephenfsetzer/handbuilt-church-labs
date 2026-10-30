#!/usr/bin/env python3
"""Build My Website: a church website from an approved brand kit, in stages.

    orient          where the website stands and what comes next (read-only)
    record          record a stage: what it wrote, its gate, its rounds and hours
    check-score     check a page score against the rules without recording it
    critique        record the critic's verdict on a page or a piece
    change-request  reopen an approved stage, saying what changes and why

Each stage reads what the stages before it froze, writes files under
website/, and ends at a gate: the pastor's approval, the critic's pass, or
the automated checks. An approved stage is frozen. Changing it takes a change
request, which marks every later stage stale. State and receipts live in
.handbuilt/build-my-website/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMPLEMENTATION_VERSION = "0.1.0"
STATE_SCHEMA_VERSION = 1
BRAND_SCHEMA_MINIMUM = 3
STATE_DIR = Path(".handbuilt") / "build-my-website"
WEBSITE_DIR = Path("website")
PHOTO_LEDGER_FILE = Path("brand") / "photo-ledger.json"

STAGES = ("sitemap", "harvest", "content", "scores", "design", "pages", "motion", "build", "handoff")
STAGE_TITLES = {
    "sitemap": "The site map",
    "harvest": "Your words, page by page",
    "content": "What each page says",
    "scores": "The page scores",
    "design": "Home and one inside page",
    "pages": "The rest of the site",
    "motion": "What moves",
    "build": "The built site",
    "handoff": "Keeping it up",
}
STAGE_SPEAKER = {
    "sitemap": "producer", "harvest": "writer", "content": "writer", "scores": "art director",
    "design": "senior designer", "pages": "senior designer", "motion": "interaction designer",
    "build": "engineer", "handoff": "producer",
}
# Rounds of reactions each gate is planned for: "1 + 1" is one round of
# reactions and one refinement. Going over is recorded and warned, never
# refused: the first churches are how the budgets get set.
ROUND_BUDGETS = {"sitemap": 2, "harvest": None, "content": 2, "scores": None, "design": 2, "pages": 1,
                 "motion": 1, "build": None, "handoff": 1}
PASTOR_GATES = {"sitemap", "content", "design", "pages", "motion", "handoff"}
CRITIC_GATES = {"scores", "design", "pages"}

SCORE_AXES = ("lead", "ground", "scale", "layout")
LEADS = ("photo", "type", "number", "art", "form")
BIG_SHIFTS_MINIMUM = 2
WIDTHS = (1440, 375)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
MOTION_MAXIMUM = 3


class Blocked(Exception):
    """Expected workflow failure with a stable code."""

    def __init__(self, code: str, message: str, *, field: str | None = None, detail: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _failure(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, Blocked):
        item: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.field:
            item["field"] = exc.field
        if exc.detail is not None:
            item["detail"] = exc.detail
        return {"status": "blocked", "errors": [item], "warnings": []}
    return {"status": "failed", "errors": [{"code": "unexpected_failure", "message": str(exc)}], "warnings": []}


def _church_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir() or not (root / "church.yaml").is_file():
        raise Blocked("uninitialized_church_folder", f"Church folder is not initialized: {root}")
    return root


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Blocked("unreadable_file", f"Could not read {path.name}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _load_state(root: Path) -> dict[str, Any]:
    state = _read_json(root / STATE_DIR / "state.json", None)
    if state is None:
        return {"schema_version": STATE_SCHEMA_VERSION, "stages": {}, "critiques": [], "change_requests": []}
    return state


def _save_state(root: Path, state: dict[str, Any]) -> None:
    state["implementation_version"] = IMPLEMENTATION_VERSION
    _write_json(root / STATE_DIR / "state.json", state)


def _receipt(root: Path, kind: str, payload: dict[str, Any]) -> Path:
    path = root / STATE_DIR / "receipts" / f"{kind}-{uuid.uuid4()}.json"
    record = {"workflow": "build-my-website", "implementation_version": IMPLEMENTATION_VERSION, "kind": kind, "created_at": _now()}
    record.update(payload)
    _write_json(path, record)
    return path


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Blocked("missing_field", f"{field} is required", field=field)
    return value.strip()


def _text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise Blocked("missing_field", f"{field} is a list of at least one line of text", field=field)
    return [v.strip() for v in value]


def _existing(root: Path, raw: Any, field: str, *, images: bool = False) -> str:
    rel = Path(_text(raw, field))
    path = (root / rel).resolve()
    if rel.is_absolute() or not path.is_relative_to(root):
        raise Blocked("outside_church_folder", f"{field} must be a path inside the church folder", field=field)
    if not path.is_file():
        raise Blocked("file_missing", f"{field} does not exist: {rel.as_posix()}", field=field)
    if images and path.suffix.casefold() not in IMAGE_SUFFIXES:
        raise Blocked("image_required", f"{field} must be an image or PDF", field=field)
    return rel.as_posix()


def _recorded(state: dict[str, Any], stage: str) -> bool:
    return stage in state["stages"]


# ---------------------------------------------------------------- the brand kit

def _brand_kit(root: Path) -> dict[str, Any]:
    """The approved brand kit with its web layer. The website starts nowhere else."""
    brand = _read_json(root / "brand.json", {})
    system = brand.get("brand_system") if isinstance(brand, dict) else None
    if not isinstance(system, dict) or not system.get("approved_on"):
        raise Blocked("brand_kit_required", "The website starts from an approved brand kit. Run Build My Brand to approval first")
    if int(system.get("schema_version") or 0) < BRAND_SCHEMA_MINIMUM or not isinstance(system.get("web"), dict):
        raise Blocked("web_layer_required", "This brand was approved before it had a web layer. Record Your photos and "
                      "How it looks everywhere with Build My Brand, restage, prove it on the homepage and approve it again")
    return system


def _photo_ledger(root: Path) -> dict[str, Any]:
    ledger = _read_json(root / PHOTO_LEDGER_FILE, {"photos": [], "gaps": []})
    ledger.setdefault("photos", [])
    return ledger


# ---------------------------------------------------------------- the page score

def score_problems(sections: list[dict[str, Any]]) -> list[str]:
    """What breaks the score rules: every section changes gear, and every page shifts hard at least twice."""
    problems: list[str] = []
    big = 0
    for index, section in enumerate(sections):
        for axis in SCORE_AXES:
            if not isinstance(section.get(axis), str) or not section[axis].strip():
                problems.append(f"Section {index + 1} names no {axis}")
        if section.get("lead") not in LEADS:
            problems.append(f"Section {index + 1} leads with {section.get('lead')!r}; a section leads with one of " + ", ".join(LEADS))
        if index == 0:
            continue
        before = sections[index - 1]
        changed = [axis for axis in SCORE_AXES if str(section.get(axis, "")).strip().casefold() != str(before.get(axis, "")).strip().casefold()]
        if not changed:
            problems.append(f"Section {index + 1} repeats section {index}: change at least one of lead, ground, scale or layout")
        if len(changed) >= 2:
            big += 1
    if len(sections) > 2 and big < BIG_SHIFTS_MINIMUM:
        problems.append(f"The page has {big} big shift{'s' if big != 1 else ''}; plan at least {BIG_SHIFTS_MINIMUM}, where two or more of lead, ground, scale and layout change at once")
    return problems


def _photo_problems(ledger: dict[str, Any], scores: dict[str, list[dict[str, Any]]]) -> list[str]:
    """No weak photo leads, no photo without consent, and no photo on two pages."""
    by_file = {p.get("file"): p for p in ledger.get("photos", [])}
    used: dict[str, str] = {}
    problems = []
    for page, sections in scores.items():
        for index, section in enumerate(sections):
            photo = section.get("photo")
            if section.get("lead") == "photo" and not photo:
                problems.append(f"{page} section {index + 1} leads with a photo but names none; with no A or B photo, follow the house style's plan without photos")
            if not photo:
                continue
            entry = by_file.get(photo)
            if entry is None:
                problems.append(f"{page} section {index + 1} uses {photo}, which is not in the photo ledger")
                continue
            if entry.get("rating") == "C" or (section.get("lead") == "photo" and entry.get("rating") != "A" and index == 0):
                problems.append(f"{page} section {index + 1}: {photo} is rated {entry.get('rating')}; a C photo is never used, and a page opens on an A photo")
            if entry.get("consent") != "yes" and entry.get("people"):
                problems.append(f"{page} section {index + 1}: {photo} shows people and its consent is {entry.get('consent')}")
            if photo in used and used[photo] != page:
                problems.append(f"{photo} is on {used[photo]} already; no photo appears on two pages")
            used.setdefault(photo, page)
    return problems


def check_score(church_folder: str | Path, scores: dict[str, Any]) -> dict[str, Any]:
    """The score rules, for the art director to iterate against before the critic sees it."""
    try:
        root = _church_root(church_folder)
        if not isinstance(scores, dict) or not scores:
            raise Blocked("scores_required", "scores maps each page to its sections in order")
        result = {page: score_problems(sections if isinstance(sections, list) else []) for page, sections in scores.items()}
        photos = _photo_problems(_photo_ledger(root), {p: s for p, s in scores.items() if isinstance(s, list)})
        ok = not photos and not any(result.values())
        return {"status": "pass" if ok else "fail", "pages": result, "photos": photos, "warnings": []}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


# ---------------------------------------------------------------- the stages

def _pages(state: dict[str, Any]) -> list[str]:
    return [p["slug"] for p in state["stages"]["sitemap"]["pages"]]


def _sections(state: dict[str, Any]) -> dict[str, list[str]]:
    return {slug: [s["id"] for s in sections] for slug, sections in state["stages"]["content"]["pages"].items()}


def _latest_verdict(state: dict[str, Any], stage: str, target: str) -> str | None:
    verdicts = [c for c in state["critiques"] if c["stage"] == stage and c["target"] == target and not c.get("superseded")]
    return verdicts[-1]["verdict"] if verdicts else None


def _require_critic(state: dict[str, Any], stage: str, targets: list[str]) -> None:
    missing = [t for t in targets if _latest_verdict(state, stage, t) != "pass"]
    if missing:
        raise Blocked("critic_required", "The critic passes each piece before the pastor sees it; no pass yet for: " + ", ".join(missing),
                      field="critic", detail={"missing": missing})


def _screens(root: Path, raw: Any, field: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise Blocked("screens_required", f"{field} holds a screenshot at each width: " + ", ".join(str(w) for w in WIDTHS), field=field)
    return {str(w): _existing(root, raw.get(str(w)), f"{field}.{w}", images=True) for w in WIDTHS}


def _validate(root: Path, state: dict[str, Any], kit: dict[str, Any], stage: str, meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if stage == "sitemap":
        pages = meta.get("pages")
        if not isinstance(pages, list) or not pages:
            raise Blocked("pages_required", "The site map lists every page: slug, title, job, audience, and what it must let a visitor do", field="pages")
        slugs = set()
        out["pages"] = []
        for i, page in enumerate(pages):
            if not isinstance(page, dict):
                raise Blocked("pages_required", f"pages[{i}] must be an object", field="pages")
            item = {k: _text(page.get(k), f"pages[{i}].{k}") for k in ("slug", "title", "job", "audience")}
            item["must_let_visitor"] = _text_list(page.get("must_let_visitor"), f"pages[{i}].must_let_visitor")
            if item["slug"] in slugs:
                raise Blocked("pages_required", f"Two pages are both {item['slug']}", field="pages")
            slugs.add(item["slug"])
            out["pages"].append(item)
        if "home" not in slugs:
            raise Blocked("pages_required", "The site map includes the home page (slug home)", field="pages")
        out["file"] = _existing(root, (WEBSITE_DIR / "sitemap.md").as_posix(), "sitemap")
    elif stage == "harvest":
        sheets = meta.get("sheets")
        if not isinstance(sheets, dict):
            raise Blocked("sheets_required", "sheets maps every page in the site map to its question sheet", field="sheets")
        missing = [p for p in _pages(state) if p not in sheets]
        extra = [p for p in sheets if p not in _pages(state)]
        if missing or extra:
            raise Blocked("sheets_required", "One sheet per approved page. " + (f"Missing: {', '.join(missing)}. " if missing else "") +
                          (f"Not in the site map: {', '.join(extra)}." if extra else ""), field="sheets")
        out["sheets"] = {}
        for page, sheet in sheets.items():
            if not isinstance(sheet, dict) or sheet.get("status") not in ("answered", "skipped"):
                raise Blocked("sheets_required", f"sheets.{page}.status is answered or skipped", field=f"sheets.{page}")
            item = {"status": sheet["status"], "file": _existing(root, sheet.get("file"), f"sheets.{page}.file")}
            if sheet["status"] == "skipped":
                item["reason"] = _text(sheet.get("reason"), f"sheets.{page}.reason")
            out["sheets"][page] = item
        mined = meta.get("mined", [])
        if not isinstance(mined, list) or any(not isinstance(m, dict) or not m.get("quote") or not m.get("source") for m in mined):
            raise Blocked("sources_required", "Every mined quote names its source", field="mined")
        out["mined"] = len(mined)
    elif stage == "content":
        for name in ("content.md", "site-data.yaml"):
            out[name] = _existing(root, (WEBSITE_DIR / name).as_posix(), name)
        _site_data(root / WEBSITE_DIR / "site-data.yaml")
        pages = meta.get("pages")
        if not isinstance(pages, dict) or sorted(pages) != sorted(_pages(state)):
            raise Blocked("pages_required", "content covers exactly the pages in the site map, each with its sections in order", field="pages")
        out["pages"] = {}
        for page, sections in pages.items():
            if not isinstance(sections, list) or not sections:
                raise Blocked("sections_required", f"pages.{page} lists its sections, each with id and message", field=f"pages.{page}")
            ids = [_text(s.get("id") if isinstance(s, dict) else None, f"pages.{page}.id") for s in sections]
            if len(set(ids)) != len(ids):
                raise Blocked("sections_required", f"pages.{page} names a section twice", field=f"pages.{page}")
            out["pages"][page] = [{"id": s["id"].strip(), "message": _text(s.get("message"), f"pages.{page}.{s['id']}.message")} for s in sections]
        out["preview"] = _existing(root, meta.get("preview"), "preview")
        out["placeholders"] = int(meta.get("placeholders") or 0)
    elif stage == "scores":
        out["file"] = _existing(root, (WEBSITE_DIR / "design-plan.md").as_posix(), "design-plan")
        scores = meta.get("scores")
        sections = _sections(state)
        if not isinstance(scores, dict) or sorted(scores) != sorted(sections):
            raise Blocked("scores_required", "scores covers every page in the content, each section in order", field="scores")
        problems: dict[str, list[str]] = {}
        for page, rows in scores.items():
            if not isinstance(rows, list) or [r.get("section") for r in rows if isinstance(r, dict)] != sections[page]:
                raise Blocked("sections_changed", f"The score for {page} must follow its approved sections in order: {', '.join(sections[page])}. "
                              "A design can't add or remove a section; file a change request against the content", field=f"scores.{page}")
            found = score_problems(rows)
            if found:
                problems[page] = found
        photos = _photo_problems(_photo_ledger(root), scores)
        if problems or photos:
            raise Blocked("score_failed", "The scores break the rules; run check-score while you work", field="scores",
                          detail={"pages": problems, "photos": photos})
        _require_critic(state, stage, list(scores))
        out["scores"] = scores
    elif stage in {"design", "pages"}:
        pages = meta.get("pages")
        expected = _expected_pages(state, stage)
        if not isinstance(pages, dict) or (not pages and (stage == "design" or expected)):
            raise Blocked("pages_required", "pages maps each designed page to its screens at both widths", field="pages")
        if stage == "design" and ("home" not in pages or len(pages) != 2):
            raise Blocked("pages_required", "The design round is Home and one inside page, at desktop and phone", field="pages")
        if stage == "pages" and sorted(pages) != sorted(expected):
            raise Blocked("pages_required", "The rest of the site: every page not designed in the first round. Expected: " + ", ".join(expected), field="pages")
        unknown = [p for p in pages if p not in _pages(state)]
        if unknown:
            raise Blocked("pages_required", "Not in the site map: " + ", ".join(unknown), field="pages")
        out["pages"] = {page: {"screens": _screens(root, (spec or {}).get("screens"), f"pages.{page}.screens"),
                               "patterns": _text_list((spec or {}).get("patterns"), f"pages.{page}.patterns")}
                        for page, spec in pages.items()}
        approved = {p["name"] for p in (state["stages"].get("design") or {}).get("patterns", [])}
        new = meta.get("patterns", [])
        if not isinstance(new, list):
            raise Blocked("patterns_required", "patterns lists each section pattern made in this round", field="patterns")
        out["patterns"] = []
        for i, pattern in enumerate(new):
            if not isinstance(pattern, dict):
                raise Blocked("patterns_required", f"patterns[{i}] must be an object", field="patterns")
            name = _text(pattern.get("name"), f"patterns[{i}].name")
            out["patterns"].append({"name": name, "holds": _text(pattern.get("holds"), f"patterns[{i}].holds"),
                                    "screens": _screens(root, pattern.get("screens"), f"patterns[{i}].screens")})
        known = approved | {p["name"] for p in out["patterns"]}
        loose = sorted({n for spec in out["pages"].values() for n in spec["patterns"] if n not in known})
        if loose:
            raise Blocked("pattern_unknown", "Every section is built from an approved pattern, or a new one named and documented in this round: " + ", ".join(loose), field="patterns")
        if stage == "design" and not out["patterns"]:
            raise Blocked("patterns_required", "Name and document the section patterns Home and the inside page use, so later pages and upkeep can follow them", field="patterns")
        # A page's pass covers the patterns it introduces in the design round;
        # a pattern added later is checked on its own.
        new_later = [f"pattern:{p['name']}" for p in out["patterns"]] if stage == "pages" else []
        _require_critic(state, stage, list(pages) + new_later)
        if stage == "pages" and meta.get("whole_site_shown") is not True:
            raise Blocked("whole_site_required", "The pastor sees the whole site once before it is built (whole_site_shown: true)", field="whole_site_shown")
    elif stage == "motion":
        out["file"] = _existing(root, (WEBSITE_DIR / "motion.md").as_posix(), "motion")
        moments = meta.get("moments")
        if not isinstance(moments, list) or not 1 <= len(moments) <= MOTION_MAXIMUM:
            raise Blocked("moments_required", f"Motion is one to {MOTION_MAXIMUM} signature moments, each with what it does when the visitor asks for reduced motion", field="moments")
        out["moments"] = []
        for i, moment in enumerate(moments):
            moment = moment if isinstance(moment, dict) else {}
            out["moments"].append({"name": _text(moment.get("name"), f"moments[{i}].name"),
                                   "reduced_motion": _text(moment.get("reduced_motion"), f"moments[{i}].reduced_motion")})
    elif stage == "build":
        checks = meta.get("checks")
        required = list(kit["web"].get("checks") or [])
        if not isinstance(checks, dict):
            raise Blocked("checks_required", "checks maps each of the brand kit's web checks to pass or fail at both widths", field="checks")
        failing = [c for c in required if not isinstance(checks.get(c), dict) or any(checks[c].get(str(w)) != "pass" for w in WIDTHS)]
        if failing:
            raise Blocked("checks_failed", "These checks have not passed at both widths: " + ", ".join(failing), field="checks", detail={"failing": failing})
        out["checks"] = {c: checks[c] for c in required}
        out["site"] = _text(meta.get("site"), "site")
        if meta.get("preview_url") is not None:
            out["preview_url"] = _text(meta.get("preview_url"), "preview_url")
    elif stage == "handoff":
        out["maintain"] = _existing(root, (WEBSITE_DIR / "maintain.md").as_posix(), "maintain")
        out["volunteer_card"] = _existing(root, meta.get("volunteer_card"), "volunteer_card")
        out["approver"] = _text(meta.get("approver"), "approver")
        calendar = meta.get("slot_calendar")
        slots = set((kit["web"].get("slots") or {}).keys())
        if not isinstance(calendar, dict) or set(calendar) != slots:
            raise Blocked("slot_calendar_required", "The slot calendar says when each of the house style's slots changes: " + ", ".join(sorted(slots)), field="slot_calendar")
        out["slot_calendar"] = {k: _text(v, f"slot_calendar.{k}") for k, v in calendar.items()}
        update = meta.get("first_update")
        if not isinstance(update, dict) or str(update.get("approved_by", "")).strip() != out["approver"]:
            raise Blocked("first_update_required", "Make one real update by asking the agent, and have the named approver approve its preview (first_update with request and approved_by)", field="first_update")
        out["first_update"] = {"request": _text(update.get("request"), "first_update.request"), "approved_by": out["approver"]}
    if stage in PASTOR_GATES:
        out["approved_by"] = _text(meta.get("approved_by"), "approved_by")
    return out


def _expected_pages(state: dict[str, Any], stage: str) -> list[str]:
    done = set((state["stages"].get("design") or {}).get("pages", {}))
    return [p for p in _pages(state) if p not in done] if stage == "pages" else _pages(state)


def _site_data(path: Path) -> None:
    try:
        import yaml
    except ImportError:  # the managed runtime has PyYAML; a bare interpreter only checks the file exists
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise Blocked("invalid_site_data", f"site-data.yaml could not be read: {exc}", field="site-data.yaml") from exc
    if not isinstance(data, dict) or not data:
        raise Blocked("invalid_site_data", "site-data.yaml holds the facts every page reads: service times, address, staff, links", field="site-data.yaml")


def _measures(meta: dict[str, Any], stage: str) -> tuple[dict[str, Any], list[str]]:
    rounds = meta.get("rounds")
    if not isinstance(rounds, int) or rounds < 0:
        raise Blocked("rounds_required", "Record how many rounds of the pastor's reactions this stage took (rounds, 0 for none)", field="rounds")
    hours = meta.get("hours")
    if not isinstance(hours, dict) or not all(isinstance(hours.get(k), (int, float)) and hours[k] >= 0 for k in ("agent", "pastor")):
        raise Blocked("hours_required", "Record rough hours of agent time and pastor time (hours: agent, pastor)", field="hours")
    budget = ROUND_BUDGETS[stage]
    warnings = [f"{STAGE_TITLES[stage]} took {rounds} rounds against a budget of {budget}; note what caused it in the retrospective"] if budget is not None and rounds > budget else []
    return {"rounds": rounds, "budget": budget, "hours": {"agent": float(hours["agent"]), "pastor": float(hours["pastor"])}}, warnings


def record(church_folder: str | Path, stage: str, metadata: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        kit = _brand_kit(root)
        state = _load_state(root)
        if stage not in STAGES:
            raise Blocked("unknown_stage", f"Unknown stage: {stage}", field="stage")
        for earlier in STAGES[: STAGES.index(stage)]:
            if not _recorded(state, earlier):
                raise Blocked("stage_out_of_order", f"Record {STAGE_TITLES[earlier]} before {STAGE_TITLES[stage]}", field="stage")
            if state["stages"][earlier].get("stale"):
                raise Blocked("stage_stale", f"{STAGE_TITLES[earlier]} changed after it was approved; bring it up to date before {STAGE_TITLES[stage]}", field="stage")
        open_request = next((c for c in state["change_requests"] if c["stage"] == stage and not c.get("closed_at")), None)
        if _recorded(state, stage) and not state["stages"][stage].get("stale"):
            if not replace:
                raise Blocked("already_recorded", f"{STAGE_TITLES[stage]} is approved and frozen. File a change request to reopen it", field="stage")
            if open_request is None:
                raise Blocked("change_request_required", f"{STAGE_TITLES[stage]} is approved and frozen. File a change request saying what changes and why, then record it again", field="stage")
        entry = _validate(root, state, kit, stage, metadata)
        measures, warnings = _measures(metadata, stage)
        entry.update(measures, speaker=STAGE_SPEAKER[stage], recorded_at=_now())
        if open_request is not None:
            open_request["closed_at"] = entry["recorded_at"]
            entry["change_request"] = open_request["id"]
        if stage == "scores":
            _assign_photos(root, entry["scores"])
        state["stages"][stage] = entry
        _save_state(root, state)
        receipt = _receipt(root, f"stage-{stage}", {"stage": stage, "record": entry})
        return {"status": "recorded", "stage": stage, "title": STAGE_TITLES[stage], "receipt": str(receipt),
                "next_stage": _next_stage(state), "warnings": warnings}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def _assign_photos(root: Path, scores: dict[str, list[dict[str, Any]]]) -> None:
    """Write each photo's page into the ledger, so the next page can't reuse it."""
    path = root / PHOTO_LEDGER_FILE
    if not path.is_file():
        return
    ledger = _read_json(path, {})
    for photo in ledger.get("photos", []):
        photo["used_in"] = sorted({page for page, rows in scores.items() for row in rows if row.get("photo") == photo.get("file")})
    _write_json(path, ledger)


def critique(church_folder: str | Path, stage: str, target: str, verdict: str, notes: str, *, instead: str | None = None) -> dict[str, Any]:
    """The critic's verdict, from screenshots, in fresh context. A redirect says what to try instead."""
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        if stage not in CRITIC_GATES:
            raise Blocked("unknown_stage", "The critic checks the scores, the design round, and the rest of the pages", field="stage")
        if verdict not in ("pass", "redirect"):
            raise Blocked("invalid_verdict", "The verdict is pass or redirect", field="verdict")
        item = {"id": f"critique-{uuid.uuid4().hex[:8]}", "stage": stage, "target": _text(target, "target"), "verdict": verdict,
                "notes": _text(notes, "notes"), "at": _now()}
        if verdict == "redirect":
            item["instead"] = _text(instead, "instead")
        state["critiques"].append(item)
        _save_state(root, state)
        receipt = _receipt(root, "critique", item)
        return {"status": "recorded", "critique": item, "receipt": str(receipt), "warnings": []}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def change_request(church_folder: str | Path, stage: str, reason: str, change: str) -> dict[str, Any]:
    """Reopen a frozen stage. Every later stage is marked stale, and the record says why."""
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        if stage not in STAGES or not _recorded(state, stage):
            raise Blocked("not_recorded", "Only an approved stage takes a change request", field="stage")
        item = {"id": f"change-{uuid.uuid4().hex[:8]}", "stage": stage, "reason": _text(reason, "reason"),
                "change": _text(change, "change"), "opened_at": _now()}
        stale = []
        for later in STAGES[STAGES.index(stage) + 1:]:
            if _recorded(state, later):
                state["stages"][later]["stale"] = True
                state["stages"][later]["stale_reason"] = f"{STAGE_TITLES[stage]} changed: {item['change']}"
                stale.append(later)
        for c in state["critiques"]:
            if c["stage"] in stale:
                c["superseded"] = True
        item["stale"] = stale
        state["change_requests"].append(item)
        _save_state(root, state)
        receipt = _receipt(root, "change-request", item)
        return {"status": "opened", "change_request": item, "receipt": str(receipt), "warnings": []}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def _next_stage(state: dict[str, Any]) -> str | None:
    reopened = {c["stage"] for c in state["change_requests"] if not c.get("closed_at")}
    for stage in STAGES:
        if stage in reopened or not _recorded(state, stage) or state["stages"][stage].get("stale"):
            return stage
    return None


NEXT_ACTIONS = {
    "sitemap": "Write website/sitemap.md from the brief and the research: each page, its job, its audience, and what it must let a visitor do. The pastor approves the page list.",
    "harvest": "Write one question sheet per approved page under website/harvest/, five to eight questions, each tied to a section. Take the pastor's answers verbatim and mine the church's own words, citing each source.",
    "content": "Write website/content.md and website/site-data.yaml from the harvest only; mark anything invented as a placeholder. Show a gray-box preview so the pastor approves what each page says, not how it looks.",
    "scores": "Write each page's score in website/design-plan.md. Run check-score until it passes, then have the critic pass each page.",
    "design": "Design Home and one inside page at 1440 and 375 wide from the scores, naming each section pattern. The critic passes them, then the pastor approves.",
    "pages": "Build the remaining pages from the approved patterns. The critic passes each page; the pastor sees the whole site once.",
    "motion": "Write website/motion.md: two or three signature moments, each with its reduced-motion behavior.",
    "build": "Build the site from content.md and site-data.yaml and run the brand kit's web checks at both widths, on a preview link.",
    "handoff": "Write website/maintain.md and the volunteer card, set the slot calendar and the named approver, and make one real update with them.",
}


def orient(church_folder: str | Path) -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        try:
            kit = _brand_kit(root)
            kit_status = {"ready": True, "approved_on": kit.get("approved_on"), "slots": sorted((kit["web"].get("slots") or {}).keys()),
                          "checks": kit["web"].get("checks") or []}
        except Blocked as exc:
            return {"status": "blocked", "errors": [{"code": exc.code, "message": exc.message}], "brand_kit": {"ready": False},
                    "next_action": exc.message, "warnings": []}
        nxt = _next_stage(state)
        stages = [{"stage": s, "title": STAGE_TITLES[s], "speaker": STAGE_SPEAKER[s], "recorded": _recorded(state, s),
                   "stale": bool((state["stages"].get(s) or {}).get("stale")),
                   "rounds": (state["stages"].get(s) or {}).get("rounds"), "budget": ROUND_BUDGETS[s],
                   "hours": (state["stages"].get(s) or {}).get("hours")} for s in STAGES]
        totals = {"agent": sum((s["hours"] or {}).get("agent", 0) for s in stages), "pastor": sum((s["hours"] or {}).get("pastor", 0) for s in stages)}
        ledger = _photo_ledger(root)
        return {"status": "ok", "brand_kit": kit_status, "stages": stages, "next_stage": nxt,
                "next_action": NEXT_ACTIONS[nxt] if nxt else "The site is built and handed off. Upkeep follows website/maintain.md.",
                "hours": totals, "redirects": sum(1 for c in state["critiques"] if c["verdict"] == "redirect"),
                "change_requests": len(state["change_requests"]),
                "photos": {"usable": sum(1 for p in ledger["photos"] if p.get("rating") in ("A", "B")), "gaps": ledger.get("gaps", [])},
                "warnings": []}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


# ---------------------------------------------------------------- command line

class _Parser(argparse.ArgumentParser):
    """Help and usage errors answer in JSON, so a launcher never mistakes help for a failed run."""

    def print_help(self, file=None):  # noqa: D401
        print(json.dumps({"status": "help", "usage": self.format_help()}, indent=2))

    def error(self, message):
        print(json.dumps({"status": "blocked", "errors": [{"code": "invalid_arguments", "message": message}]}, indent=2))
        raise SystemExit(2)


def _metadata_file(root: str, raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    path = Path(raw) if Path(raw).is_absolute() else Path(root) / raw
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise Blocked("invalid_metadata", "The metadata file holds one JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Inspect or advance a church's Build My Website workflow")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    item = sub.add_parser("orient")
    item.add_argument("--church-folder", required=True)
    item = sub.add_parser("record")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--stage", required=True, choices=STAGES)
    item.add_argument("--metadata-file", required=True)
    item.add_argument("--replace", action="store_true")
    item = sub.add_parser("check-score")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--metadata-file", required=True, help="A JSON file with scores: each page's sections in order")
    item = sub.add_parser("critique")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--stage", required=True, choices=sorted(CRITIC_GATES))
    item.add_argument("--target", required=True, help="The page slug, or pattern:<name>")
    item.add_argument("--verdict", required=True, choices=("pass", "redirect"))
    item.add_argument("--notes", required=True)
    item.add_argument("--instead", help="For a redirect: what to try instead")
    item = sub.add_parser("change-request")
    item.add_argument("--church-folder", required=True)
    item.add_argument("--stage", required=True, choices=STAGES)
    item.add_argument("--reason", required=True)
    item.add_argument("--change", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "orient":
            result = orient(args.church_folder)
        elif args.command == "record":
            result = record(args.church_folder, args.stage, _metadata_file(args.church_folder, args.metadata_file), replace=args.replace)
        elif args.command == "check-score":
            result = check_score(args.church_folder, _metadata_file(args.church_folder, args.metadata_file).get("scores"))
        elif args.command == "critique":
            result = critique(args.church_folder, args.stage, args.target, args.verdict, args.notes, instead=args.instead)
        else:
            result = change_request(args.church_folder, args.stage, args.reason, args.change)
    except Exception as exc:  # noqa: BLE001
        result = _failure(exc)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"ok", "recorded", "opened", "pass"} else 1


if __name__ == "__main__":
    sys.exit(main())
