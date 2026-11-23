"""Standing choices and carry-forward: a church answers a bulletin question once, and next week starts from
last week's approved bulletin.

- `worship/standing-choices.json` holds the church's kept answers: {"choices": [{key, question, answer,
  until, kept_on}]}. `until` is null for "from now on", or the last day of the season the answer was kept
  for. `keep` writes one; `applicable` lists the ones that still apply on a Sunday.
- `carry_forward` writes the new week's draft input from the last approved bulletin for the same service:
  the date decides occasion, collect, readings and psalm; everything else carries; a notice carries only
  while its `until` date has not passed; who preaches is always asked unless a kept answer names them.
- `adopt` records a bulletin the pastor approved outside the skill (finished by hand) into approved history
  once, from that week's own config, so history and carry-forward include it.

Standard library only. Never touches the network.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

CHOICES_PATH = Path("worship/standing-choices.json")
KEEPS = ("sunday", "season", "always")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")

# What the date decides afresh. Everything else in last week's input carries.
DATE_DECIDES = ("readings", "collect_of_day", "proper_preface", "selected_parts", "service_context", "choice_origins")
SERVICE_DATE_DECIDES = ("date", "occasion", "proper", "lectionary_track", "liturgical_color", "preacher", "preacher_note")


class StandingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# --- the church year -------------------------------------------------------------------------------------

def easter(year: int) -> date:
    """Western Easter Sunday (the anonymous Gregorian computus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def advent_sunday(year: int) -> date:
    christmas = date(year, 12, 25)
    return christmas - timedelta(days=(christmas.isoweekday() % 7 or 7) + 21)


def season_end(sunday: date) -> date:
    """The last day of the church season containing `sunday`."""
    year = sunday.year
    if advent_sunday(year) <= sunday <= date(year, 12, 24):
        return date(year, 12, 24)
    if sunday >= date(year, 12, 25):
        return date(year + 1, 1, 5)
    if sunday <= date(year, 1, 5):
        return date(year, 1, 5)
    pascha = easter(year)
    ash_wednesday, pentecost = pascha - timedelta(days=46), pascha + timedelta(days=49)
    if sunday < ash_wednesday:
        return ash_wednesday - timedelta(days=1)
    if sunday < pascha:
        return pascha - timedelta(days=1)
    if sunday <= pentecost:
        return pentecost
    return advent_sunday(year) - timedelta(days=1)


# --- standing choices ------------------------------------------------------------------------------------

def _read_choices(root: Path) -> list[dict[str, Any]]:
    path = root / CHOICES_PATH
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise StandingError("standing_choices_unreadable", f"{CHOICES_PATH} is not valid JSON: {exc}") from exc
    items = data.get("choices") if isinstance(data, dict) else None
    return [item for item in items or [] if isinstance(item, dict) and isinstance(item.get("key"), str)]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def applicable(root: Path, sunday: date) -> list[dict[str, Any]]:
    """The kept answers that apply on this Sunday: from now on, or kept for a season that has not ended."""
    found = []
    for item in _read_choices(root):
        until = item.get("until")
        if until is None or (isinstance(until, str) and date.fromisoformat(until) >= sunday):
            found.append({key: item.get(key) for key in ("key", "question", "answer", "until")})
    return sorted(found, key=lambda item: item["key"])


def keep(root: Path, *, key: str, question: str, answer: str, keep: str, sunday: date) -> dict[str, Any]:
    """Keep one answer for this season or from now on. A this-Sunday answer is never kept, so it is a no-op."""
    if keep not in KEEPS:
        raise StandingError("invalid_keep", "Keep is sunday, season or always.")
    if not KEY.match(key or ""):
        raise StandingError("invalid_key", "A choice key is lower-case words joined by hyphens.")
    if not (question or "").strip() or not (answer or "").strip():
        raise StandingError("invalid_choice", "A kept choice needs its question and its answer.")
    if keep == "sunday":
        return {"status": "ok", "kept": False}
    until = season_end(sunday).isoformat() if keep == "season" else None
    choices = [item for item in _read_choices(root) if item.get("key") != key]
    entry = {"key": key, "question": question.strip()[:500], "answer": answer.strip()[:1000], "until": until,
             "kept_on": sunday.isoformat()}
    choices.append(entry)
    _write_json(root / CHOICES_PATH, {"choices": sorted(choices, key=lambda item: item["key"])})
    return {"status": "ok", "kept": True, "choice": entry}


# --- carry-forward ---------------------------------------------------------------------------------------

def _approved_entries(root: Path) -> dict[str, dict[str, Any]]:
    log = root / "bulletins" / "bulletin-log.json"
    if not log.is_file():
        return {}
    data = json.loads(log.read_text(encoding="utf-8"))
    return {key: entry for key, entry in data.items() if isinstance(entry, dict)} if isinstance(data, dict) else {}


def _package_of(root: Path, entry: dict[str, Any]) -> Path | None:
    """The week folder that holds an approved entry's own bulletin-config.json."""
    named = entry.get("package")
    if isinstance(named, str):
        folder = (root / named).resolve()
        if folder.is_relative_to(root.resolve()) and (folder / "bulletin-config.json").is_file():
            return folder
    runs = {value.get("production_run_id") for value in (entry.get("templates") or {}).values() if isinstance(value, dict)}
    for receipt in sorted((root / "bulletins").glob("**/bulletin-approval-receipt.json")):
        if ".revisions" in receipt.parts:
            continue
        try:
            approval = json.loads(receipt.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if approval.get("production_run_id") in runs and (receipt.parent / "bulletin-config.json").is_file():
            return receipt.parent
    return None


def last_approved(root: Path, sunday: date, service_id: str | None = None,
                  occurrence_id: str | None = None) -> tuple[dict[str, Any], Path] | None:
    """The most recent approved bulletin before this Sunday for the same service, and its week folder."""
    candidates = []
    for entry in _approved_entries(root).values():
        when = entry.get("date")
        if not isinstance(when, str) or date.fromisoformat(when) >= sunday:
            continue
        if service_id and entry.get("service_id") not in (None, service_id):
            continue
        if occurrence_id and (entry.get("occurrence_id") or "main") != occurrence_id:
            continue
        candidates.append(entry)
    for entry in sorted(candidates, key=lambda item: item["date"], reverse=True):
        folder = _package_of(root, entry)
        if folder:
            return entry, folder
    return None


def carry_forward(root: Path, sunday: date, *, service_id: str | None = None, occurrence_id: str | None = None,
                  write: bool = True) -> dict[str, Any]:
    """Next week's draft input: last approved bulletin's input with the date's parts cleared."""
    root = root.resolve()
    found = last_approved(root, sunday, service_id, occurrence_id)
    if not found:
        return {"status": "ok", "carried_from": None, "asks": [], "message": "No approved bulletin to start from."}
    entry, folder = found
    config = json.loads((folder / "bulletin-config.json").read_text(encoding="utf-8"))
    draft = {key: copy.deepcopy(value) for key, value in config.items() if key not in DATE_DECIDES}
    service = {key: value for key, value in (config.get("service") or {}).items() if key not in SERVICE_DATE_DECIDES}
    service["date"] = sunday.isoformat()
    draft["service"] = service
    asks: list[dict[str, Any]] = []
    kept = {item["key"]: item for item in applicable(root, sunday)}
    if "preacher" in kept:
        service["preacher"] = kept["preacher"]["answer"]
        last = config.get("service") or {}
        if last.get("preacher_note") and last.get("preacher") == service["preacher"]:
            service["preacher_note"] = last["preacher_note"]   # the line under a name travels with that person
    else:
        asks.append({"id": "preacher", "question": f"Who preaches on {sunday:%B} {sunday.day}?",
                     "options": [name for name in [(config.get("service") or {}).get("preacher")] if name], "weekly": True})
    carried, dropped, unsure = [], [], []
    for notice in config.get("announcements") or []:
        if not isinstance(notice, dict):
            continue
        until = notice.get("until")
        if isinstance(until, str):
            (carried if date.fromisoformat(until) >= sunday else dropped).append(notice)
        else:
            unsure.append(notice)
    draft["announcements"] = carried
    _advance_each_week(root, draft, config, entry, sunday, asks)
    if unsure:
        titles = [str(notice.get("title") or "").strip() for notice in unsure]
        asks.append({"id": "notices", "question": "Which of last week's notices print again this Sunday?",
                     "options": [title for title in titles if title] + ["None of them"], "carried": unsure})
    draft["carried_from"] = {"date": entry.get("date"), "package": folder.relative_to(root).as_posix()}
    result = {"status": "ok", "carried_from": draft["carried_from"], "asks": asks,
              "dropped_notices": [notice.get("title") for notice in dropped], "standing_choices": list(kept.values())}
    if write:
        svc = service_id or service.get("service_id") or "main"
        occ = occurrence_id or service.get("occurrence_id") or "main"
        path = root / "bulletins" / "drafts" / sunday.isoformat() / svc / occ / "input.json"
        _write_json(path, draft)
        result["draft_input"] = path.relative_to(root).as_posix()
    else:
        result["draft"] = draft
    return result


def _advance_each_week(root: Path, draft: dict[str, Any], config: dict[str, Any], entry: dict[str, Any],
                       sunday: date, asks: list[dict[str, Any]]) -> None:
    """A hymn sung one stanza a week (an Advent acclamation, say) moves on a stanza for each week since.

    The hymn says so itself: `each_week: {"stanza": 1, "images": "music/.../H56-stanza-{stanza}.png"}`.
    When the next stanza's picture is missing, the pastor is asked rather than last week's stanza reprinted.
    """
    try:
        weeks = (sunday - date.fromisoformat(str(entry.get("date") or (config.get("service") or {}).get("date")))).days // 7
    except ValueError:
        return
    for group in ("hymns", "service_music"):
        for slot, hymn in (draft.get(group) or {}).items():
            rule = hymn.get("each_week") if isinstance(hymn, dict) else None
            if not isinstance(rule, dict) or not isinstance(rule.get("stanza"), int) or weeks < 1:
                continue
            stanza = rule["stanza"] + weeks
            template = rule.get("images")
            image = template.format(stanza=stanza) if isinstance(template, str) else None
            if image and ((root / image).is_file() or (root / "music" / image).is_file()):
                hymn["images"] = [image]
                hymn.pop("image", None)
                hymn["each_week"] = {**rule, "stanza": stanza}
            else:
                hymn.pop("each_week", None)   # the pastor's answer decides this week's picture, not the guard
                asks.append({"id": f"{slot.replace('_', '-')}-stanza",
                             "question": f"Which stanza of {hymn.get('title') or 'the ' + slot.replace('_', ' ')} "
                                         f"is sung on {sunday:%B} {sunday.day}? Stanza {stanza} has no music picture yet.",
                             "options": [f"Stanza {stanza}"], "weekly": True})


CREDIT_FIELDS = ("tune", "composer", "custom_text", "label")


def check_carried(root: Path, bulletin: dict[str, Any]) -> None:
    """Refuse a bulletin that silently drops what carry-forward carried for its Sunday.

    When `carry-forward` wrote a draft for this Sunday, the input must keep every part the draft carried
    (the refrain, the dismissal, the notices still in date ...) or name it in `dropped_from_last_week`, so
    dropping last week's practice is always a decision, never an accident.
    """
    service = bulletin.get("service") if isinstance(bulletin.get("service"), dict) else {}
    when = service.get("date")
    if not isinstance(when, str):
        return
    # Recomputed from approved history every time: the draft file on disk is the agent's to edit, so it is
    # never the measure of what last week carried.
    draft_path = Path("bulletins/drafts") / when / (service.get("service_id") or "main") / (service.get("occurrence_id") or "main") / "input.json"
    if not (root / draft_path).is_file() and not bulletin.get("carried_from"):
        return   # this week did not start from last week (a first bulletin, or one built fresh)
    carried = carry_forward(root, date.fromisoformat(when), service_id=service.get("service_id"),
                            occurrence_id=service.get("occurrence_id"), write=False)
    draft = carried.get("draft")
    if not draft:
        return
    dropped = set(bulletin.get("dropped_from_last_week") or [])
    missing = [key for key in draft if key not in ("carried_from",) and key not in bulletin and key not in dropped]
    missing += [f"liturgy.{key}" for key in (draft.get("liturgy") or {})
                if key not in (bulletin.get("liturgy") or {}) and f"liturgy.{key}" not in dropped]
    missing += [f"options.{key}" for key in (draft.get("options") or {})
                if key not in (bulletin.get("options") or {}) and f"options.{key}" not in dropped]
    for group in ("hymns", "service_music"):
        missing += [f"{group}.{slot}" for slot in (draft.get(group) or {})
                    if slot not in (bulletin.get(group) or {}) and f"{group}.{slot}" not in dropped]
    for group in ("hymns", "service_music"):
        for slot, hymn in (draft.get(group) or {}).items():
            mine = (bulletin.get(group) or {}).get(slot)
            # The same hymn again keeps the words the church printed under it (Day by Day's "from the Broadway
            # musical Godspell, by Stephen Schwartz" was rewritten once into a new credit).
            if (isinstance(hymn, dict) and isinstance(mine, dict) and hymn.get("title")
                    and str(hymn.get("title")).strip() == str(mine.get("title") or "").strip()):
                for field in CREDIT_FIELDS:
                    if (hymn.get(field) or None) != (mine.get(field) or None) and f"{group}.{slot}.{field}" not in dropped:
                        missing.append(f"{group}.{slot}.{field} (as last week printed it)")
            if (isinstance(hymn, dict) and hymn.get("each_week") and isinstance(mine, dict)
                    and mine.get("images") != hymn.get("images") and f"{group}.{slot}.images" not in dropped):
                missing.append(f"{group}.{slot}.images (stanza {hymn['each_week'].get('stanza')} this Sunday)")
    missing += [f"service.{key}" for key in (draft.get("service") or {})
                if key not in service and f"service.{key}" not in dropped]
    if missing:
        raise StandingError(
            "carried_part_dropped",
            "This Sunday's input leaves out what last week's approved bulletin carried: " + ", ".join(sorted(missing))
            + f". Build the input on {draft_path.as_posix()} as carry-forward wrote it, or list each part you mean to drop "
            "in dropped_from_last_week. Drop a part only when the pastor's note or files say so; a part you only think "
            "belonged to last week is a question for the pastor, never your call.")


# --- adopting an approval made outside the skill ---------------------------------------------------------

def adopt(root: Path, folder: Path, *, approved_by: str, note: str = "") -> dict[str, Any]:
    """Record a bulletin approved outside the skill into approved history, once, from its own config."""
    from .interface import _history_entry, _now   # the same entry finalize writes

    root, folder = root.resolve(), folder.resolve()
    if not folder.is_relative_to(root):
        raise StandingError("unsafe_path", "The bulletin folder must be inside the church folder.")
    config_path, receipt_path = folder / "bulletin-config.json", folder / "bulletin-production-receipt.json"
    if not (config_path.is_file() and receipt_path.is_file()):
        raise StandingError("not_a_bulletin", "That folder has no bulletin-config.json and production receipt.")
    if (folder / "bulletin-approval-receipt.json").is_file():
        raise StandingError("already_approved", "That bulletin was approved through the skill already.")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    log = root / "bulletins" / "bulletin-log.json"
    history = _approved_entries(root)
    entry = _history_entry(config, receipt, f"adopted-{config['service']['date']}")
    if entry["occurrence_key"] in history:
        raise StandingError("approved_history_conflict", "History already has an approved bulletin for that service.")
    entry.update(evidence_label="adopted_approval", package=folder.relative_to(root).as_posix(),
                 adopted={"approved_by": approved_by, "note": note[:500], "recorded_at": _now()})
    entry["announcements"] = [item.get("title") for item in config.get("announcements", []) if isinstance(item, dict)]
    history[entry["occurrence_key"]] = entry
    _write_json(log, {key: history[key] for key in sorted(history)})
    return {"status": "ok", "adopted": entry["occurrence_key"], "history_path": log.relative_to(root).as_posix()}
