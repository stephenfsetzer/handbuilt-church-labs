"""Build My Brand: a staged, receipt-governed brand workflow for a church folder.

The agent designs and teaches. This module keeps the record honest: the plan
is shown before any work, every stage is recorded in order and opens with
where the pastor is, every decision carries its rationale into the brand
guide, every presentation after the direction shows at least what the pastor
saw last time (fidelity only rises), the new brand is staged until the pastor
approves a real proof, and the previous brand is archived rather than deleted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import survival

IMPLEMENTATION_VERSION = "0.2.0"
RECEIPT_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 2
BRAND_SYSTEM_SCHEMA_VERSION = 2

# Stage order is the workflow. A stage can be recorded only after every
# earlier stage. Approval happens after "prove"; "connect" and "handoff"
# follow approval.
STAGES = (
    "roadmap", "fork", "discover", "interview", "identity", "direction",
    "develop", "refine-1", "refine-2", "color", "type", "voice",
    "build", "prove", "connect", "handoff",
)
STAGE_TITLES = {
    "roadmap": "The plan",
    "fork": "Refresh or start new",
    "discover": "How you look today",
    "interview": "What you told me",
    "identity": "One identity, many uses",
    "direction": "Your direction",
    "develop": "Your direction, developed",
    "refine-1": "First refinement",
    "refine-2": "Second refinement and your mark",
    "color": "Your colors",
    "type": "Your type",
    "voice": "Your voice",
    "build": "What was built",
    "prove": "The proof",
    "connect": "How your brand travels",
    "handoff": "Keeping your brand",
}
# What the pastor decides at each stage, in the "you are here" line.
STAGE_DECIDES = {
    "roadmap": "Nothing yet. Read the plan and ask anything about it.",
    "fork": "Keep your current mark and redesign around it, or start new.",
    "discover": "Nothing yet. This is what a designer sees today.",
    "interview": "Your answers to seven questions only you can answer.",
    "identity": "Whether programs and ministries live inside one identity.",
    "direction": "Which of two or three directions is the church you are trying to be.",
    "develop": "Which developed version of your direction to carry forward.",
    "refine-1": "Your reactions to the tightened system.",
    "refine-2": "Your reactions, and the mark that goes on everything.",
    "color": "The final palette, each color with a job.",
    "type": "The type pairing, with its license.",
    "voice": "The voice rules.",
    "build": "Nothing yet. The system is being written into staging.",
    "prove": "Whether the new brand replaces the old one.",
    "connect": "Nothing. This shows where the brand travels.",
    "handoff": "Nothing. This is how to keep it.",
}
# Stages that put a choice to the pastor. Each needs a decision and a why.
DECISION_STAGES = {"fork", "identity", "direction", "develop", "refine-1", "refine-2", "color", "type", "voice"}
# Stages where the pastor picks from shown options, which the guide records.
OPTION_STAGES = {"direction", "develop", "color", "type", "voice"}
# Stages that present the system in context. Each must show at least what
# the previous one showed: fidelity only rises.
PRESENTATION_STAGES = ("direction", "develop", "refine-1", "refine-2")
# Stage names from the first scheme that no longer exist.
LEGACY_STAGES = {
    "mark": "The mark round was replaced by direction development and two refinements; the chosen mark is recorded with refine-2",
}
FORK_CHOICES = ("refresh", "new")
INTERVIEW_KEYS = (
    "prompt", "audience", "success", "name", "preserve", "operator", "constraints",
)
INTERVIEW_LABELS = {
    "prompt": "What prompted this now",
    "audience": "Who you are trying to reach",
    "success": "What would tell you it worked",
    "name": "The name on the wordmark",
    "preserve": "What must be preserved",
    "operator": "Who runs it week to week",
    "constraints": "Constraints",
}
ROADMAP_PHASE_KEYS = ("title", "stages", "you_see", "you_decide", "time")

# Applications: the real pieces a presentation is shown on. The direction
# boards set the floor; development raises it; nothing after may lower it.
APPLICATION_LABELS = {
    "bulletin_cover": "the bulletin cover",
    "test_announcement": "the church's own test announcement",
    "website_screen": "the website's first screen",
    "sign": "the sign at street distance",
    "social_avatar": "the social avatar at real size",
    "poster": "a poster",
    "partner_pairing": "the mark beside a stand-in partner mark",
    "letterhead": "the letterhead",
    "newsletter": "the newsletter header",
    "lockup_example": "one program lockup",
    "favicon": "the favicon",
}
DIRECTION_APPLICATIONS = ("bulletin_cover", "test_announcement", "website_screen")
DEVELOP_APPLICATIONS = DIRECTION_APPLICATIONS + ("sign", "social_avatar")
APPLICATION_KEY = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

APPROVAL_STAGE = "prove"
STATE_DIR = Path(".handbuilt") / "build-my-brand"
SCRATCH_DIR = STATE_DIR / "scratch"
GUIDE_FILE = Path("brand") / "guide.md"
BRIEF_FILE = Path("brand") / "brief.md"
STAGING_DIR = Path("brand") / "staging"
EXPLORATIONS_DIR = STAGING_DIR / "explorations"
CHECKS_DIR = STAGING_DIR / "checks"
ARCHIVE_DIR = Path("brand") / "archive"
STAGED_SYSTEM_FILE = STAGING_DIR / "brand-system.json"
ARCHIVED_LIVE_ITEMS = ("marks", "type", "templates", "voice.md")
FONT_SUFFIXES = {".ttf", ".otf", ".woff", ".woff2"}
MARK_SUFFIXES = {".svg", ".png"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
RENDERER_COLORS = ("ink", "accent", "accent_deep", "paper", "rubric_red")
SKILL_DIR = Path(__file__).resolve().parents[1]


class WorkflowFailure(Exception):
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
    if isinstance(exc, (WorkflowFailure, survival.SurvivalFailure)):
        item: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.field:
            item["field"] = exc.field
        if getattr(exc, "detail", None) is not None:
            item["detail"] = exc.detail
        return {"status": "blocked", "errors": [item], "warnings": []}
    return {"status": "failed", "errors": [{"code": "unexpected_failure", "message": str(exc)}], "warnings": []}


def _brand_setup():
    """The onboarding brand writer owns brand.json validation; reuse it."""
    path = SKILL_DIR.parent / "onboarding" / "scripts" / "brand_setup.py"
    spec = importlib.util.spec_from_file_location("handbuilt_brand_setup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _church_root(church_folder: str | Path) -> Path:
    try:
        root = _brand_setup()._root(church_folder)
    except ValueError as exc:
        raise WorkflowFailure("invalid_church_folder", str(exc)) from exc
    if not (root / "church.yaml").is_file():
        raise WorkflowFailure("uninitialized_church_folder", f"Church folder is not initialized: {root}")
    if not (root / "brand.json").is_file():
        raise WorkflowFailure("brand_file_missing", "Finish onboarding first so brand.json exists")
    return root


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(root.resolve()))) == str(root.resolve())
    except ValueError:
        return False


def _relative(root: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise WorkflowFailure("invalid_path", f"{field} must be a relative path inside the church folder", field=field)
    candidate = Path(raw.strip())
    if candidate.is_absolute() or ".." in candidate.parts or "://" in raw:
        raise WorkflowFailure("invalid_path", f"{field} must be a relative path inside the church folder", field=field)
    path = root / candidate
    if path.is_symlink() or not _inside(path, root):
        raise WorkflowFailure("invalid_path", f"{field} must stay inside the church folder", field=field)
    return candidate


def _existing(root: Path, raw: Any, field: str, *, under: Path | None = None) -> Path:
    rel = _relative(root, raw, field)
    if under is not None and not _inside(root / rel, root / under):
        raise WorkflowFailure("outside_staging", f"{field} must live under {under.as_posix()}/", field=field)
    if not (root / rel).is_file():
        raise WorkflowFailure("missing_file", f"{field} does not exist yet: {rel.as_posix()}", field=field)
    return rel


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowFailure("unreadable_file", f"Could not read {path.name}: {exc}") from exc


def _church_identity(root: Path) -> dict[str, str]:
    try:
        data = yaml.safe_load((root / "church.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    church = data.get("church") if isinstance(data.get("church"), dict) else {}
    name = str(church.get("name") or "").strip()
    return {"name": name or "Your church", "short_name": str(church.get("short_name") or name or "Your church").strip()}


def _label(application: str) -> str:
    return APPLICATION_LABELS.get(application, application.replace("_", " "))


# ---------------------------------------------------------------- state

def _state_path(root: Path) -> Path:
    return root / STATE_DIR / "state.json"


def _migrate(state: dict[str, Any]) -> dict[str, Any]:
    """Bring a run recorded under the first scheme up to the current one.

    The first scheme had no plan stage, a symbol-only mark round, and color,
    type, and voice decided on a mark alone. A migrated run keeps every
    decision the pastor made. The mark round, if it was recorded, is kept as
    evidence but is no longer a stage. Color, type, and voice recorded before
    the system was developed are marked stale so they are confirmed on the
    developed system before approval. The direction record gains the
    applications its boards showed, because later presentations are measured
    against it. The plan is owed and is recorded first when the run resumes.
    """
    version = state.get("schema_version") or 1
    if version >= STATE_SCHEMA_VERSION:
        return state
    stages = state.setdefault("stages", {})
    legacy: dict[str, Any] = {}
    for name in list(stages):
        if name in LEGACY_STAGES or name not in STAGES:
            legacy[name] = stages.pop(name)
    if legacy:
        state["legacy_stages"] = legacy
    for name in ("color", "type", "voice"):
        entry = stages.get(name)
        if isinstance(entry, dict) and entry.get("recorded_at"):
            entry["stale"] = True
            entry["stale_reason"] = "Decided on a mark alone under the first scheme; confirm it on the developed system"
    direction = stages.get("direction")
    if isinstance(direction, dict) and direction.get("recorded_at") and not direction.get("applications"):
        direction["applications"] = list(DIRECTION_APPLICATIONS)
        direction["applications_source"] = "Migration baseline: the direction boards showed a bulletin cover, the test announcement, and a website screen"
    state["migrated_from"] = version
    state["migrated_at"] = _now()
    state["schema_version"] = STATE_SCHEMA_VERSION
    return state


def _load_state(root: Path) -> dict[str, Any]:
    state = _read_json(_state_path(root), {})
    state.setdefault("schema_version", STATE_SCHEMA_VERSION if not state else state.get("schema_version", 1))
    state.setdefault("stages", {})
    state.setdefault("fork", None)
    state.setdefault("approved", None)
    state.setdefault("explorations", {})
    state.setdefault("redirects", [])
    return _migrate(state)


def _save_state(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    state["implementation_version"] = IMPLEMENTATION_VERSION
    _write_json(_state_path(root), state)


def _recorded(state: dict[str, Any], stage: str) -> bool:
    return isinstance(state["stages"].get(stage), dict) and bool(state["stages"][stage].get("recorded_at"))


def _stale_stages(state: dict[str, Any]) -> list[str]:
    return [s for s in STAGES if _recorded(state, s) and state["stages"][s].get("stale")]


def _owed_stages(state: dict[str, Any]) -> list[str]:
    """Stages a migrated run skipped and must still record: only the plan so far."""
    if not _recorded(state, "roadmap") and any(_recorded(state, s) for s in STAGES[1:]):
        return ["roadmap"]
    return []


def _next_stage(state: dict[str, Any]) -> str | None:
    owed = set(_owed_stages(state))
    for stage in STAGES:
        if stage in owed:
            continue
        if not _recorded(state, stage):
            return stage
    return None


def _fidelity_floor(state: dict[str, Any], stage: str) -> tuple[list[str], str | None]:
    """The applications a presentation must show: everything the previous one showed, plus the stage's own minimum."""
    if stage == "direction":
        return list(DIRECTION_APPLICATIONS), None
    previous = PRESENTATION_STAGES[PRESENTATION_STAGES.index(stage) - 1]
    shown = list((state["stages"].get(previous) or {}).get("applications") or DIRECTION_APPLICATIONS)
    minimum = DEVELOP_APPLICATIONS if stage != "direction" else DIRECTION_APPLICATIONS
    floor = list(shown)
    for key in minimum:
        if key not in floor:
            floor.append(key)
    return floor, previous


def _receipt(root: Path, kind: str, payload: dict[str, Any]) -> Path:
    directory = root / STATE_DIR / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}-{uuid.uuid4()}.json"
    record = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "workflow": "build-my-brand",
        "implementation_version": IMPLEMENTATION_VERSION,
        "kind": kind,
        "created_at": _now(),
    }
    record.update(payload)
    _write_json(path, record)
    return path


# ---------------------------------------------------------------- guide

def _guide_header(root: Path) -> str:
    identity = _church_identity(root)
    return (
        f"# {identity['name']} Brand Guide\n\n"
        "<!-- Handbuilt Build My Brand keeps this guide. Each section records a lesson,\n"
        "the options considered, the decision, and the reason. Edit freely; the\n"
        "workflow replaces only the section between a stage's markers. -->\n\n"
        "This guide grew as the brand was decided. Read it to understand why the brand\n"
        "looks and sounds the way it does, and to keep it that way.\n"
    )


def _phase_for(state: dict[str, Any], stage: str) -> str | None:
    phases = (state["stages"].get("roadmap") or {}).get("phases") or []
    for phase in phases:
        if stage in (phase.get("stages") or []):
            return phase.get("title")
    return None


def _wayfinding(state: dict[str, Any], stage: str) -> list[str]:
    """The 'you are here' lines every section opens with."""
    index = STAGES.index(stage)
    if stage == "roadmap" and _owed_stages(state):
        here = _next_stage(state) or "handoff"
        here_index = STAGES.index(here)
        where = (f"**Where you are:** this plan arrives with the work already under way. "
                 f"You are at step {here_index + 1} of {len(STAGES)}, {STAGE_TITLES[here]}.")
        nxt = STAGE_TITLES[here]
    else:
        phase = _phase_for(state, stage)
        where = f"**Where you are:** step {index + 1} of {len(STAGES)}, {STAGE_TITLES[stage]}"
        where += f", in the phase \"{phase}\"." if phase else "."
        nxt = STAGE_TITLES[STAGES[index + 1]] if index + 1 < len(STAGES) else "nothing more; the guide is complete"
    return [where, f"**You decide today:** {STAGE_DECIDES[stage]}", f"**Next you will see:** {nxt}."]


def _roadmap_table(phases: list[dict[str, Any]]) -> list[str]:
    lines = ["| Phase | What you will see | What you decide | About how long |", "|---|---|---|---|"]
    for phase in phases:
        cells = [str(phase.get(k, "")).replace("|", "/").replace("\n", " ") for k in ("title", "you_see", "you_decide", "time")]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _section(state: dict[str, Any], stage: str, body: str, metadata: dict[str, Any]) -> str:
    lines = [f"<!-- stage:{stage} -->", f"## {STAGE_TITLES[stage]}", "", *_wayfinding(state, stage), "", body.strip(), ""]
    if stage == "roadmap":
        lines.extend(_roadmap_table(metadata.get("phases") or []))
        lines.append("")
    if stage in DECISION_STAGES:
        options = metadata.get("options") or []
        if options:
            lines.append("**Options considered:** " + "; ".join(str(o) for o in options))
            lines.append("")
        applications = metadata.get("applications") or []
        if applications:
            lines.append("**Shown on:** " + "; ".join(_label(a) for a in applications))
            lines.append("")
        if metadata.get("recommendation"):
            lines.append(f"**Recommended:** {metadata['recommendation']}")
            lines.append("")
        lines.append(f"**Decision:** {metadata['decision']}")
        lines.append("")
        lines.append(f"**Why:** {metadata['rationale']}")
        lines.append("")
    lines.append(f"<!-- /stage:{stage} -->")
    return "\n".join(lines) + "\n"


def _upsert_section(root: Path, stage: str, section: str) -> Path:
    path = root / GUIDE_FILE
    text = path.read_text(encoding="utf-8") if path.is_file() else _guide_header(root)
    pattern = re.compile(rf"<!-- stage:{re.escape(stage)} -->[\s\S]*?<!-- /stage:{re.escape(stage)} -->\n?")
    if pattern.search(text):
        text = pattern.sub(lambda _m: section, text, count=1)
    elif stage == "roadmap" and "<!-- stage:" in text:
        # A plan recorded late still reads first in the guide.
        head, rest = text.split("<!-- stage:", 1)
        text = head.rstrip("\n") + "\n\n" + section + "\n<!-- stage:" + rest
    else:
        text = text.rstrip("\n") + "\n\n" + section
    _write_text(path, text)
    return path


def _interview_summary(answers: dict[str, str]) -> str:
    lines = ["The interview asked only for what the pastor alone knows. The full record is",
             "in `brand/brief.md`, which wins over any design file when they disagree.", ""]
    for key in INTERVIEW_KEYS:
        lines.append(f"- **{INTERVIEW_LABELS[key]}:** {answers[key].strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------- validation per stage

def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowFailure("missing_value", f"{field} is required and must be text", field=field)
    return value.strip()


def _validate_roadmap(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    phases = metadata.get("phases")
    if not isinstance(phases, list) or len(phases) < 2:
        raise WorkflowFailure("phases_required", "The plan lists its phases: each with a title, the stages it covers, what the pastor will see, what they decide, and about how long it takes", field="phases")
    covered: dict[str, str] = {}
    cleaned = []
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise WorkflowFailure("phases_required", f"phases[{index}] must be an object", field="phases")
        entry = {k: _require_text(phase.get(k), f"phases[{index}].{k}") for k in ROADMAP_PHASE_KEYS if k != "stages"}
        stages = phase.get("stages")
        if not isinstance(stages, list) or not stages or not all(isinstance(s, str) for s in stages):
            raise WorkflowFailure("phases_required", f"phases[{index}].stages lists the workflow stages this phase covers", field="phases")
        for stage in stages:
            if stage not in STAGES or stage == "roadmap":
                raise WorkflowFailure("phases_required", f"phases[{index}].stages names an unknown stage: {stage}", field="phases")
            if stage in covered:
                raise WorkflowFailure("phases_required", f"Stage {stage} appears in two phases", field="phases")
            covered[stage] = entry["title"]
        entry["stages"] = list(stages)
        cleaned.append(entry)
    missing = [s for s in STAGES[1:] if s not in covered]
    if missing:
        raise WorkflowFailure("phases_required", "The plan must cover the whole engagement; no phase covers: " + ", ".join(missing), field="phases")
    return cleaned


def _validate_applications(root: Path, state: dict[str, Any], stage: str, metadata: dict[str, Any], record: dict[str, Any]) -> None:
    floor, previous = _fidelity_floor(state, stage)
    applications = metadata.get("applications")
    if not isinstance(applications, list) or not applications or not all(isinstance(a, str) and APPLICATION_KEY.fullmatch(a) for a in applications):
        raise WorkflowFailure("applications_required", f"The {STAGE_TITLES[stage]} record lists the applications the pastor was shown, as keys such as " + ", ".join(DEVELOP_APPLICATIONS), field="applications")
    shown = list(dict.fromkeys(applications))
    missing = [a for a in floor if a not in shown]
    if missing:
        seen = f"what the pastor saw at {STAGE_TITLES[previous]}" if previous else "the direction's minimum"
        raise WorkflowFailure("fidelity_dropped", f"Fidelity only rises. {STAGE_TITLES[stage]} must show at least {seen}, and it is missing: " + ", ".join(_label(a) for a in missing), field="applications", detail={"missing": missing, "floor": floor})
    record["applications"] = shown
    boards = metadata.get("boards")
    if stage != "direction" or boards is not None:
        if not isinstance(boards, list) or not boards:
            raise WorkflowFailure("boards_required", f"The {STAGE_TITLES[stage]} record names the board images the pastor saw (under brand/)", field="boards")
        record["boards"] = []
        for index, raw in enumerate(boards):
            rel = _existing(root, raw, f"boards[{index}]", under=Path("brand"))
            if rel.suffix.casefold() not in survival.IMAGE_SUFFIXES:
                raise WorkflowFailure("boards_required", f"boards[{index}] must be an image or PDF", field="boards")
            record["boards"].append(rel.as_posix())
    references = metadata.get("references")
    if references is not None:
        if not isinstance(references, list) or not references:
            raise WorkflowFailure("invalid_references", "references is a list of named real work: each with name and learn, and a url where there is one", field="references")
        record["references"] = []
        for index, item in enumerate(references):
            if not isinstance(item, dict):
                raise WorkflowFailure("invalid_references", f"references[{index}] must be an object with name and learn", field="references")
            entry = {"name": _require_text(item.get("name"), f"references[{index}].name"), "learn": _require_text(item.get("learn"), f"references[{index}].learn")}
            if item.get("url") is not None:
                entry["url"] = _require_text(item.get("url"), f"references[{index}].url")
            record["references"].append(entry)


def _validate_mark(root: Path, raw: Any, field: str) -> str:
    rel = _existing(root, raw, field, under=STAGING_DIR)
    if rel.suffix.casefold() != ".svg":
        raise WorkflowFailure("invalid_mark", f"{field} must be an editable SVG; exports come later", field=field)
    try:
        _brand_setup()._asset(root, rel.as_posix(), field)
        survival.validate_mark_svg(root / rel)
    except (ValueError, survival.SurvivalFailure) as exc:
        raise WorkflowFailure("invalid_mark", str(getattr(exc, "message", exc)), field=field) from exc
    return rel.as_posix()


def _validate_stage(root: Path, state: dict[str, Any], stage: str, content: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if stage not in STAGES:
        raise WorkflowFailure("unknown_stage", f"Unknown stage: {stage}", field="stage")
    if not isinstance(metadata, dict):
        raise WorkflowFailure("invalid_metadata", "Stage metadata must be an object")
    if not content.strip():
        raise WorkflowFailure("empty_content", "A stage needs content for the guide", field="content")
    record: dict[str, Any] = {}
    if stage == "roadmap":
        record["phases"] = _validate_roadmap(metadata)
    if stage in DECISION_STAGES:
        record["decision"] = _require_text(metadata.get("decision"), "decision")
        record["rationale"] = _require_text(metadata.get("rationale"), "rationale")
        options = metadata.get("options")
        if stage in OPTION_STAGES:
            if not isinstance(options, list) or len(options) < 2 or not all(isinstance(o, str) and o.strip() for o in options):
                raise WorkflowFailure("options_required", f"The {stage} round shows the pastor at least two options; record them", field="options")
        if options is not None:
            record["options"] = [str(o).strip() for o in options]
    if stage == "fork":
        if record["decision"] not in FORK_CHOICES:
            raise WorkflowFailure("invalid_fork", "The fork decision must be refresh or new", field="decision")
    if stage == "discover":
        sources = metadata.get("sources")
        if not isinstance(sources, list) or not sources:
            raise WorkflowFailure("sources_required", "Discovery records what it inspected: at least one source with a label and kind", field="sources")
        for item in sources:
            if not isinstance(item, dict) or not item.get("label") or not item.get("kind"):
                raise WorkflowFailure("sources_required", "Each discovery source needs a label and a kind", field="sources")
        record["sources"] = sources
    if stage == "interview":
        answers = metadata.get("answers")
        if not isinstance(answers, dict):
            raise WorkflowFailure("answers_required", "The interview records an answer for each of its questions", field="answers")
        missing = [k for k in INTERVIEW_KEYS if not isinstance(answers.get(k), str) or not answers[k].strip()]
        if missing:
            raise WorkflowFailure("answers_required", "Unanswered interview question: " + ", ".join(missing), field="answers")
        record["answers"] = {k: answers[k].strip() for k in INTERVIEW_KEYS}
    if stage in PRESENTATION_STAGES:
        _validate_applications(root, state, stage, metadata, record)
    if stage == "develop":
        record["recommendation"] = _require_text(metadata.get("recommendation"), "recommendation")
    if stage == "refine-2":
        mark = metadata.get("mark")
        if isinstance(mark, str):
            mark = {"primary": mark}
        if not isinstance(mark, dict) or not mark.get("primary"):
            raise WorkflowFailure("mark_required", "The second refinement records the chosen mark: mark.primary, the editable SVG under brand/staging/", field="mark")
        record["mark"] = {k: _validate_mark(root, v, f"mark.{k}") for k, v in mark.items()}
    if stage == "build":
        staged = metadata.get("staged_files")
        if not isinstance(staged, list) or not staged:
            raise WorkflowFailure("staged_files_required", "Build lists the files it staged under brand/staging/", field="staged_files")
        record["staged_files"] = [_existing(root, f, "staged_files", under=STAGING_DIR).as_posix() for f in staged]
        if not (root / STAGED_SYSTEM_FILE).is_file():
            raise WorkflowFailure("brand_system_not_staged", "Stage the brand system (stage-brand) before recording build")
    if stage == "prove":
        record["before"] = _existing(root, metadata.get("before"), "before").as_posix()
        record["after"] = _existing(root, metadata.get("after"), "after").as_posix()
        record["announcement"] = _existing(root, metadata.get("announcement"), "announcement").as_posix()
    if stage == "handoff":
        record["volunteer_card"] = _existing(root, metadata.get("volunteer_card"), "volunteer_card").as_posix()
    if stage in {"connect", "handoff"} and not state.get("approved"):
        raise WorkflowFailure("approval_required", "Approve the proof before recording how the brand travels or handing it off")
    return record


# ---------------------------------------------------------------- operations

def _next_action(state: dict[str, Any], nxt: str | None, approved: Any) -> str:
    owed = _owed_stages(state)
    if nxt is None:
        return "The brand workflow is complete. Use it for small operations: lockups, posters, an announcement image, seasonal color, on-brand checks."
    if nxt == APPROVAL_STAGE and not approved:
        return "Render the most recent bulletin and the test announcement with the staged brand, record the proof, then ask the pastor to approve it."
    if nxt in {"connect", "handoff"} and not approved:
        return "Ask the pastor to approve the proof. Approval replaces the live brand and archives the old one."
    if nxt == "roadmap":
        return "Write the one-page plan and record it. The pastor sees the whole engagement before any work."
    lead = ""
    if owed:
        lead = f"This run began before the plan stage existed. Present and record the plan first, with the pastor at {STAGE_TITLES[nxt]}. Then: "
    if nxt in PRESENTATION_STAGES and nxt != "direction":
        floor, _previous = _fidelity_floor(state, nxt)
        shown = "; ".join(_label(a) for a in floor)
        direction = (state["stages"].get("direction") or {}).get("decision") or "the chosen direction"
        if nxt == "develop":
            return lead + f"Develop the direction ({direction}) as a whole system, by the designer who made the boards. Show two or three versions, each on at least: {shown}. Recommend one."
        extra = " Record the chosen mark's SVG." if nxt == "refine-2" else ""
        return lead + f"Tighten the chosen version and show it on at least: {shown}. Ask for reactions, not adjectives.{extra}"
    if nxt == "build":
        return lead + "Build the system into staging: the mark family with a small variant, palette, type, image language, voice, templates. Run check-marks, then stage-brand, then record build."
    return lead + f"Next round: {STAGE_TITLES[nxt]}. Teach first, then ask."


def orient(church_folder: str | Path) -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        setup = _brand_setup()
        live = setup.status(root)
        stages = []
        for stage in STAGES:
            entry = state["stages"].get(stage) or {}
            stages.append({
                "stage": stage, "title": STAGE_TITLES[stage],
                "recorded": bool(entry.get("recorded_at")),
                "recorded_at": entry.get("recorded_at"),
                "stale": bool(entry.get("stale")),
                "decision": entry.get("decision"),
                "applications": entry.get("applications"),
            })
        nxt = _next_stage(state)
        owed = _owed_stages(state)
        staged = _read_json(root / STAGED_SYSTEM_FILE, None)
        approved = state.get("approved")
        stale = _stale_stages(state)
        warnings = []
        if owed:
            warnings.append("This run began before the plan stage existed; record the plan before the next stage: " + ", ".join(STAGE_TITLES[s] for s in owed))
        if stale:
            warnings.append("Earlier decisions changed after these stages were recorded; revisit them: " + ", ".join(stale))
        roadmap = state["stages"].get("roadmap") or {}
        here = nxt or "handoff"
        floor = None
        if nxt in PRESENTATION_STAGES:
            keys, _previous = _fidelity_floor(state, nxt)
            floor = {"stage": nxt, "applications": keys, "labels": [_label(a) for a in keys]}
        refine = state["stages"].get("refine-2") or {}
        return {
            "status": "ok", "church_folder": str(root), "church": _church_identity(root),
            "fork": state.get("fork"), "stages": stages, "next_stage": nxt, "owed_stages": owed,
            "roadmap": {"recorded": bool(roadmap.get("recorded_at")), "phases": roadmap.get("phases") or [],
                        "you_are_here": {"stage": here, "title": STAGE_TITLES[here], "phase": _phase_for(state, here)}},
            "fidelity_floor": floor, "mark": refine.get("mark"),
            "explorations": {k: {"files": len(v.get("files") or []), "redirected": bool(v.get("redirected"))} for k, v in state["explorations"].items()},
            "redirects": len(state["redirects"]),
            "brief": (root / BRIEF_FILE).is_file(), "guide": (root / GUIDE_FILE).is_file(),
            "staged_brand_system": bool(staged), "approved": approved, "migrated_from": state.get("migrated_from"),
            "live_brand": {"ready": live.get("ready"), "logo": live.get("logo", {}).get("status"), "colors": live.get("colors", {}).get("status")},
            "warnings": warnings, "next_action": _next_action(state, nxt, approved),
        }
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def record(church_folder: str | Path, stage: str, content: str, metadata: dict[str, Any] | None = None, *, replace: bool = False) -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        metadata = metadata or {}
        if stage in LEGACY_STAGES:
            raise WorkflowFailure("stage_replaced", LEGACY_STAGES[stage], field="stage")
        if stage not in STAGES:
            raise WorkflowFailure("unknown_stage", f"Unknown stage: {stage}", field="stage")
        already = _recorded(state, stage)
        if already and not replace:
            raise WorkflowFailure("already_recorded", f"{STAGE_TITLES[stage]} is already recorded; pass --replace to revise it", field="stage")
        owed = _owed_stages(state)
        for earlier in STAGES[: STAGES.index(stage)]:
            if not _recorded(state, earlier):
                if earlier in owed:
                    raise WorkflowFailure("roadmap_required", f"This run began before the plan stage existed. Record {STAGE_TITLES[earlier]} (roadmap) before {STAGE_TITLES[stage]}", field="stage")
                raise WorkflowFailure("stage_out_of_order", f"Record {STAGE_TITLES[earlier]} before {STAGE_TITLES[stage]}", field="stage")
        entry = _validate_stage(root, state, stage, content, metadata)
        guide_body = content
        if stage == "interview":
            _write_text(root / BRIEF_FILE, content.rstrip("\n") + "\n")
            guide_body = _interview_summary(entry["answers"])
        section = _section(state, stage, guide_body, entry if stage in DECISION_STAGES or stage == "roadmap" else metadata)
        guide = _upsert_section(root, stage, section)
        entry["recorded_at"] = _now()
        entry["stale"] = False
        entry.pop("stale_reason", None)
        state["stages"][stage] = entry
        if stage == "fork":
            state["fork"] = entry["decision"]
        if already:
            for later in STAGES[STAGES.index(stage) + 1:]:
                if _recorded(state, later):
                    state["stages"][later]["stale"] = True
        _save_state(root, state)
        receipt = _receipt(root, f"stage-{stage}", {
            "stage": stage, "replace": already, "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "guide": GUIDE_FILE.as_posix(), "guide_sha256": _sha256(guide), "record": entry,
        })
        warnings = ["Later stages are now marked stale and should be revisited"] if already else []
        return {"status": "recorded", "stage": stage, "title": STAGE_TITLES[stage], "guide": str(guide),
                "brief": str(root / BRIEF_FILE) if stage == "interview" else None,
                "receipt": str(receipt), "next_stage": _next_stage(state), "warnings": warnings}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


# ---------------------------------------------------------------- internal exploration

def _exploration_open(state: dict[str, Any]) -> None:
    if not _recorded(state, "direction"):
        raise WorkflowFailure("stage_out_of_order", "Internal exploration opens after the direction round is recorded")
    if _recorded(state, "build"):
        raise WorkflowFailure("stage_out_of_order", "The system is built; exploration is over for this run")


def explore(church_folder: str | Path, round_label: str, files: list[str], *, maker: str = "maker", dark: str | None = None) -> dict[str, Any]:
    """Lay a round of internal exploration out on one contact sheet.

    Sketches are SVG or PNG. Nothing here is scored and nothing here reaches
    the pastor on its own; the creative director looks at the sheet and
    either briefs the senior designer from it or redirects the round.
    """
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        _exploration_open(state)
        key = survival.slug(round_label)
        entry = state["explorations"].get(key) or {"round": key, "opened_at": _now(), "files": []}
        if entry.get("redirected"):
            raise WorkflowFailure("round_redirected", f"Round {key} was redirected; open a new round under the new brief", field="round")
        if not files:
            raise WorkflowFailure("files_required", "Name the sketch files to add to this round", field="files")
        round_dir = root / EXPLORATIONS_DIR / key
        dark = dark or survival.DEFAULT_DARK
        added = []
        for raw in files:
            rel = _existing(root, raw, "files")
            suffix = rel.suffix.casefold()
            if suffix not in {".svg", ".png"}:
                raise WorkflowFailure("invalid_sketch", f"Sketches are SVG or PNG: {raw}", field="files")
            number = len(entry["files"]) + 1
            sketch_id = f"{key}-{number:02d}"
            target = round_dir / f"{sketch_id}{suffix}"
            item: dict[str, Any] = {"id": sketch_id, "source": rel.as_posix(), "maker": maker, "added_at": _now()}
            if suffix == ".svg":
                survival.validate_mark_svg(root / rel)
                survival.copy_in(root / rel, target)
                item["renders"] = survival.render_mark(root, target, round_dir / "renders", dark=dark)
            else:
                try:
                    _brand_setup()._asset(root, rel.as_posix(), "files")
                except ValueError as exc:
                    raise WorkflowFailure("invalid_sketch", str(exc), field="files") from exc
                survival.copy_in(root / rel, target)
            item["file"] = target.relative_to(root).as_posix()
            entry["files"].append(item)
            added.append(item)
        entry["contact_sheet"] = survival.contact_sheet(root, entry["files"], round_dir / "contact-sheet.png")
        state["explorations"][key] = entry
        _save_state(root, state)
        receipt = _receipt(root, "explore", {"round": key, "maker": maker, "added": [i["id"] for i in added], "files": len(entry["files"]), "contact_sheet": entry["contact_sheet"]})
        return {"status": "explored", "round": key, "added": added, "files": len(entry["files"]), "contact_sheet": entry["contact_sheet"],
                "receipt": str(receipt), "next_action": "The creative director judges the sheet against the direction board: brief the senior designer from what holds, or redirect the round."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def redirect(church_folder: str | Path, round_label: str, reason: str, *, rebrief: str | None = None) -> dict[str, Any]:
    """The creative director stops an internal round, says why, and re-briefs, without archiving the run."""
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        _exploration_open(state)
        key = survival.slug(round_label)
        reason = _require_text(reason, "reason")
        entry = state["explorations"].get(key) or {"round": key, "opened_at": _now(), "files": []}
        if entry.get("redirected"):
            raise WorkflowFailure("round_redirected", f"Round {key} is already redirected", field="round")
        note = {"round": key, "reason": reason, "at": _now(), "files_seen": len(entry["files"])}
        lines = [f"# Redirected: round {key}", "", f"Stopped {note['at']} after {note['files_seen']} sketch(es).", "", "## Why", "", reason, ""]
        if rebrief and rebrief.strip():
            lines.extend(["## New brief", "", rebrief.strip(), ""])
            note["rebrief"] = (EXPLORATIONS_DIR / key / "REDIRECTED.md").as_posix()
        path = root / EXPLORATIONS_DIR / key / "REDIRECTED.md"
        _write_text(path, "\n".join(lines))
        note["file"] = path.relative_to(root).as_posix()
        entry["redirected"] = note
        state["explorations"][key] = entry
        state["redirects"].append(note)
        _save_state(root, state)
        receipt = _receipt(root, "redirect", note)
        return {"status": "redirected", **note, "receipt": str(receipt),
                "next_action": "Open a new round under the new brief. The redirected round stays in staging as the record of what was considered."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


# ---------------------------------------------------------------- survival checks and the system

def _dark_color(patch: dict[str, Any] | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    colors = (patch or {}).get("colors") if isinstance(patch, dict) else None
    if isinstance(colors, dict) and isinstance(colors.get("accent_deep"), str) and HEX.fullmatch(colors["accent_deep"]):
        return colors["accent_deep"]
    return survival.DEFAULT_DARK


def _survival_report(root: Path, primary: str, small: str, *, dark: str, waivers: list[dict[str, Any]]) -> dict[str, Any]:
    out = root / CHECKS_DIR
    primary_rel = _existing(root, primary, "marks.primary", under=STAGING_DIR)
    small_rel = _existing(root, small, "marks.small", under=STAGING_DIR)
    results = [
        survival.run_checks(root, root / primary_rel, out / primary_rel.stem, which=survival.PRIMARY_CHECKS, dark=dark),
        survival.run_checks(root, root / small_rel, out / small_rel.stem, which=survival.SMALL_CHECKS, dark=dark),
    ]
    waived = {w["check"]: w["reason"] for w in waivers}
    failures = []
    for item in results:
        for check in item["checks"]:
            if check["passed"]:
                continue
            if check["check"] in waived:
                check["waived"] = waived[check["check"]]
            else:
                failures.append({"mark": item["mark"], **check})
        item["passed"] = not any(not c["passed"] and not c.get("waived") for c in item["checks"])
    report = {"checked_at": _now(), "dark": dark, "marks": results, "waivers": waivers, "failures": failures, "passed": not failures,
              "checks": survival.CHECKS}
    _write_json(out / "report.json", report)
    report["file"] = (CHECKS_DIR / "report.json").as_posix()
    return report


def _validate_waivers(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorkflowFailure("invalid_waivers", "waivers is a list of {check, reason}", field="waivers")
    out = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise WorkflowFailure("invalid_waivers", f"waivers[{index}] must be an object with check and reason", field="waivers")
        check = _require_text(item.get("check"), f"waivers[{index}].check")
        if check not in survival.WAIVABLE:
            raise WorkflowFailure("invalid_waivers", f"{check} cannot be waived; only " + ", ".join(sorted(survival.WAIVABLE)), field="waivers")
        out.append({"check": check, "reason": _require_text(item.get("reason"), f"waivers[{index}].reason")})
    return out


def check_marks(church_folder: str | Path, *, primary: str | None = None, small: str | None = None, dark: str | None = None) -> dict[str, Any]:
    """Run the survival checks on the staged marks, or on named marks before staging. Pass or fail, never a score."""
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        if not _recorded(state, "direction"):
            raise WorkflowFailure("stage_out_of_order", "Survival checks run on a mark designed inside the developed system; record the direction first")
        staged = _read_json(root / STAGED_SYSTEM_FILE, None)
        marks = ((staged or {}).get("brand_system") or {}).get("marks") or {}
        primary = primary or marks.get("primary")
        small = small or marks.get("small")
        if not primary or not small:
            raise WorkflowFailure("marks_required", "Name --primary and --small (the derived small variant), or stage a brand system first")
        waivers = _validate_waivers((staged or {}).get("waivers")) if staged else []
        report = _survival_report(root, primary, small, dark=_dark_color(staged, dark), waivers=waivers)
        receipt = _receipt(root, "check-marks", {k: v for k, v in report.items() if k != "checks"})
        action = ("All survival checks pass. Stage the system when it is built." if report["passed"]
                  else "Fix the mark or the small variant and check again. One color and reversal cannot be waived; the creative director may waive the others with a reason in the staged patch.")
        return {"status": "checked", "passed": report["passed"], "failures": report["failures"], "marks": report["marks"],
                "report": report["file"], "receipt": str(receipt), "next_action": action}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def _validate_imagery(system: dict[str, Any]) -> dict[str, Any]:
    imagery = system.get("imagery")
    if not isinstance(imagery, dict):
        raise WorkflowFailure("imagery_required", "brand_system.imagery states the image language: made_from, announcement, and forbidden. Without it an agent cannot make a program image on brand", field="imagery")
    out = {
        "made_from": _require_text(imagery.get("made_from"), "imagery.made_from"),
        "announcement": _require_text(imagery.get("announcement"), "imagery.announcement"),
    }
    forbidden = imagery.get("forbidden")
    if not isinstance(forbidden, list) or not forbidden or not all(isinstance(f, str) and f.strip() for f in forbidden):
        raise WorkflowFailure("imagery_required", "imagery.forbidden lists what program imagery must never do, as text", field="imagery.forbidden")
    out["forbidden"] = [f.strip() for f in forbidden]
    for key, value in imagery.items():
        if key not in out and isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _validate_brand_system(root: Path, system: Any, *, under: Path) -> dict[str, Any]:
    if not isinstance(system, dict):
        raise WorkflowFailure("invalid_brand_system", "brand_system must be an object", field="brand_system")
    if system.get("schema_version") != BRAND_SYSTEM_SCHEMA_VERSION:
        raise WorkflowFailure("invalid_brand_system", f"brand_system.schema_version must be {BRAND_SYSTEM_SCHEMA_VERSION}; version 2 adds marks.small and the imagery rules", field="schema_version")
    name = system.get("name")
    if not isinstance(name, dict):
        raise WorkflowFailure("invalid_brand_system", "brand_system.name must be an object with wordmark and short", field="name")
    _require_text(name.get("wordmark"), "name.wordmark")
    _require_text(name.get("short"), "name.short")
    direction = system.get("direction")
    if not isinstance(direction, dict):
        raise WorkflowFailure("invalid_brand_system", "brand_system.direction must be an object with name and story", field="direction")
    _require_text(direction.get("name"), "direction.name")
    _require_text(direction.get("story"), "direction.story")
    marks = system.get("marks")
    if not isinstance(marks, dict) or not marks.get("primary") or not marks.get("wordmark") or not marks.get("small"):
        raise WorkflowFailure("invalid_brand_system", "brand_system.marks needs primary, small (the derived small-size variant), and wordmark", field="marks")
    setup = _brand_setup()
    for key, raw in marks.items():
        rel = _existing(root, raw, f"marks.{key}", under=under)
        if rel.suffix.casefold() not in MARK_SUFFIXES:
            raise WorkflowFailure("invalid_mark", f"marks.{key} must be an SVG or PNG", field=f"marks.{key}")
        if key in {"primary", "small"} and rel.suffix.casefold() != ".svg":
            raise WorkflowFailure("invalid_mark", f"marks.{key} must be an editable SVG so it can be checked and reused; PNG exports go under other keys", field=f"marks.{key}")
        try:
            setup._asset(root, rel.as_posix(), f"marks.{key}")
        except ValueError as exc:
            raise WorkflowFailure("invalid_mark", str(exc), field=f"marks.{key}") from exc
    lockup = system.get("lockup_rules")
    _require_text(lockup, "lockup_rules")
    fonts = system.get("type")
    if not isinstance(fonts, dict) or not fonts.get("display") or not fonts.get("text"):
        raise WorkflowFailure("invalid_brand_system", "brand_system.type needs display and text entries", field="type")
    for role, entry in fonts.items():
        if not isinstance(entry, dict):
            raise WorkflowFailure("invalid_type", f"type.{role} must be an object", field=f"type.{role}")
        _require_text(entry.get("family"), f"type.{role}.family")
        _require_text(entry.get("license"), f"type.{role}.license")
        files = entry.get("files")
        if not isinstance(files, dict) or not files.get("regular"):
            raise WorkflowFailure("invalid_type", f"type.{role}.files needs at least a regular face", field=f"type.{role}.files")
        for face, raw in files.items():
            rel = _existing(root, raw, f"type.{role}.files.{face}", under=under)
            if rel.suffix.casefold() not in FONT_SUFFIXES:
                raise WorkflowFailure("invalid_type", f"type.{role}.files.{face} must be a font file", field=f"type.{role}.files.{face}")
    palette = system.get("palette")
    if not isinstance(palette, dict) or not palette:
        raise WorkflowFailure("invalid_brand_system", "brand_system.palette needs at least one named color", field="palette")
    for key, entry in palette.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("hex"), str) or not HEX.fullmatch(entry["hex"]):
            raise WorkflowFailure("invalid_palette", f"palette.{key} needs a six-digit hex value", field=f"palette.{key}")
        _require_text(entry.get("job"), f"palette.{key}.job")
    system["imagery"] = _validate_imagery(system)
    _existing(root, system.get("voice"), "voice", under=under)
    templates = system.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise WorkflowFailure("invalid_brand_system", "brand_system.templates lists the weekly templates that were built", field="templates")
    for key, raw in templates.items():
        _existing(root, raw, f"templates.{key}", under=under)
    return system


def _validate_renderer_patch(root: Path, patch: dict[str, Any], *, under: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    colors = patch.get("colors")
    if colors is not None:
        if not isinstance(colors, dict) or set(colors) != set(RENDERER_COLORS) or any(not isinstance(colors[k], str) or not HEX.fullmatch(colors[k]) for k in RENDERER_COLORS):
            raise WorkflowFailure("invalid_colors", "colors must give all five renderer colors as six-digit hex: " + ", ".join(RENDERER_COLORS), field="colors")
        result["colors"] = dict(colors)
    logo = patch.get("logo")
    if logo is not None:
        if not isinstance(logo, dict) or not logo or set(logo) - {"banner", "mark", "episcopal_shield"}:
            raise WorkflowFailure("invalid_logo", "logo may set banner, mark, and episcopal_shield paths", field="logo")
        result["logo"] = {k: _existing(root, v, f"logo.{k}", under=under).as_posix() for k, v in logo.items()}
    return result


def stage_brand(church_folder: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        if not _recorded(state, "voice"):
            raise WorkflowFailure("stage_out_of_order", "Stage the brand system after the voice round is recorded")
        if not isinstance(patch, dict):
            raise WorkflowFailure("invalid_patch", "The staged brand must be an object")
        system = _validate_brand_system(root, patch.get("brand_system"), under=STAGING_DIR)
        renderer = _validate_renderer_patch(root, patch, under=STAGING_DIR)
        waivers = _validate_waivers(patch.get("waivers"))
        report = _survival_report(root, system["marks"]["primary"], system["marks"]["small"], dark=_dark_color(patch, None), waivers=waivers)
        if not report["passed"]:
            raise WorkflowFailure("survival_failed", "The marks fail survival checks; fix them or, for sign, footer, favicon, and embroidery, record a waiver with a reason: "
                                  + "; ".join(f"{f['mark']} {f['check']}: {f['detail']}" for f in report["failures"]), detail={"report": report["file"], "failures": report["failures"]})
        staged = {"brand_system": system, **renderer, "waivers": waivers, "survival": {"report": report["file"], "checked_at": report["checked_at"], "passed": True}}
        _write_json(root / STAGED_SYSTEM_FILE, staged)
        receipt = _receipt(root, "stage-brand", {"file": STAGED_SYSTEM_FILE.as_posix(), "sha256": _sha256(root / STAGED_SYSTEM_FILE), "survival": report["file"], "waivers": waivers})
        return {"status": "staged", "file": str(root / STAGED_SYSTEM_FILE), "survival": report["file"], "waivers": waivers, "receipt": str(receipt),
                "next_action": "Record the build stage, then render the proof bulletin and the test announcement with the staged brand."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def _rewrite_path(raw: str) -> str:
    prefix = STAGING_DIR.as_posix() + "/"
    return "brand/" + raw[len(prefix):] if raw.startswith(prefix) else raw


def _rewrite(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _rewrite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite(v) for v in value]
    if isinstance(value, str):
        return _rewrite_path(value)
    return value


def approve(church_folder: str | Path, *, approved_by: str = "pastor") -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        owed = _owed_stages(state)
        for stage in STAGES[: STAGES.index(APPROVAL_STAGE) + 1]:
            if not _recorded(state, stage):
                code = "roadmap_required" if stage in owed else "stage_out_of_order"
                raise WorkflowFailure(code, f"Record {STAGE_TITLES[stage]} before approving")
        stale = _stale_stages(state)
        if stale:
            raise WorkflowFailure("stale_stages", "Revisit these stages before approving: " + ", ".join(stale))
        staged = _read_json(root / STAGED_SYSTEM_FILE, None)
        if not staged:
            raise WorkflowFailure("brand_system_not_staged", "Nothing is staged to approve")
        system = _validate_brand_system(root, staged.get("brand_system"), under=STAGING_DIR)
        renderer = _validate_renderer_patch(root, staged, under=STAGING_DIR)
        waivers = _validate_waivers(staged.get("waivers"))
        report = _survival_report(root, system["marks"]["primary"], system["marks"]["small"], dark=_dark_color(staged, None), waivers=waivers)
        if not report["passed"]:
            raise WorkflowFailure("survival_failed", "The staged marks changed and now fail survival checks; stage the system again", detail={"report": report["file"], "failures": report["failures"]})
        setup = _brand_setup()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        archive = root / ARCHIVE_DIR / stamp
        archive.mkdir(parents=True, exist_ok=False)
        archived: list[str] = []
        shutil.copy2(root / "brand.json", archive / "brand.json")
        archived.append("brand.json")
        for item in ARCHIVED_LIVE_ITEMS:
            live = root / "brand" / item
            if live.exists() and not live.is_symlink():
                shutil.move(str(live), str(archive / item))
                archived.append(f"brand/{item}")
        moved: list[str] = []
        staging = root / STAGING_DIR
        for child in sorted(staging.iterdir()):
            if child.name == STAGED_SYSTEM_FILE.name or child.is_symlink():
                continue
            target = root / "brand" / child.name
            if target.exists():
                shutil.move(str(target), str(archive / f"{child.name}.replaced"))
                archived.append(f"brand/{child.name}")
            shutil.move(str(child), str(target))
            moved.append(f"brand/{child.name}")
        shutil.move(str(staging / STAGED_SYSTEM_FILE.name), str(archive / "staged-brand-system.json"))
        if not any(staging.iterdir()):
            staging.rmdir()
        system = _rewrite(system)
        system["approved_on"] = stamp[:10]
        system["approved_by"] = approved_by
        system["survival"] = {"report": _rewrite_path(report["file"]), "checked_at": report["checked_at"], "waivers": waivers}
        brand = setup._read(root)
        brand["brand_system"] = system
        patch: dict[str, Any] = {}
        if renderer.get("colors"):
            patch["colors"] = renderer["colors"]
            patch["colors_status"] = "confirmed"
        if renderer.get("logo"):
            patch["logo"] = {k: _rewrite_path(v) for k, v in renderer["logo"].items()}
            patch["logo_status"] = "provided"
            for key in ("banner", "mark", "episcopal_shield"):
                if key not in patch["logo"]:
                    brand.setdefault("logo", {})[key] = ""
        setup._write(root / "brand.json", brand)
        if patch:
            try:
                setup.update(root, patch)
            except ValueError as exc:
                raise WorkflowFailure("brand_write_failed", str(exc)) from exc
        live = setup.status(root)
        state["approved"] = {"at": _now(), "by": approved_by, "archive": (ARCHIVE_DIR / stamp).as_posix()}
        _save_state(root, state)
        files = {p: _sha256(root / p) for p in sorted({*moved} | {"brand.json"}) if (root / p).is_file()}
        receipt = _receipt(root, "approval", {
            "approved_by": approved_by, "archive": (ARCHIVE_DIR / stamp).as_posix(), "archived": archived,
            "installed": moved, "brand_json_sha256": _sha256(root / "brand.json"), "files": files,
            "proof": state["stages"][APPROVAL_STAGE].get("after"), "announcement": state["stages"][APPROVAL_STAGE].get("announcement"),
            "survival": system["survival"],
        })
        return {"status": "approved", "archive": str(archive), "installed": moved, "live_brand_ready": live.get("ready"),
                "receipt": str(receipt), "next_action": "Record how the brand travels, then the handoff."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


RESTART_ITEMS = ("guide.md", "guide.pdf", "brief.md", "discovery", "staging", "volunteer-card.md")


def restart(church_folder: str | Path, *, reason: str = "") -> dict[str, Any]:
    """Archive an unfinished run so the workflow begins again at the plan.

    Nothing is deleted. The guide, the brief, discovery evidence, staged work
    (including internal exploration), and the run's state, scratch, and
    receipts move under brand/archive/run-<timestamp>/. An approved brand is
    never touched; starting over after approval is a refresh, which begins a
    new run on top of the live brand.
    """
    try:
        root = _church_root(church_folder)
        state = _load_state(root)
        if not any(_recorded(state, s) for s in STAGES) and not (root / GUIDE_FILE).is_file():
            raise WorkflowFailure("nothing_to_restart", "No Build My Brand run has started in this folder")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        archive = root / ARCHIVE_DIR / f"run-{stamp}"
        archive.mkdir(parents=True, exist_ok=False)
        moved: list[str] = []
        for item in RESTART_ITEMS:
            source = root / "brand" / item
            if source.exists() and not source.is_symlink():
                shutil.move(str(source), str(archive / item))
                moved.append(f"brand/{item}")
        run_state = root / STATE_DIR
        if run_state.is_dir():
            shutil.move(str(run_state), str(archive / "workflow-record"))
            moved.append(STATE_DIR.as_posix())
        note = {"archived_at": _now(), "reason": reason.strip(), "fork": state.get("fork"),
                "stages_recorded": [s for s in STAGES if _recorded(state, s)], "approved": state.get("approved"), "moved": moved}
        _write_json(archive / "run.json", note)
        receipt = _receipt(root, "restart", {"archive": (ARCHIVE_DIR / f"run-{stamp}").as_posix(), **note})
        return {"status": "restarted", "archive": str(archive), "moved": moved, "receipt": str(receipt),
                "next_stage": "roadmap", "next_action": "Begin with the plan. Do not read the archived run while running the new one."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def render_guide(church_folder: str | Path, out: str | None = None) -> dict[str, Any]:
    try:
        root = _church_root(church_folder)
        guide = root / GUIDE_FILE
        if not guide.is_file():
            raise WorkflowFailure("guide_missing", "No brand guide exists yet; record the first stage")
        from . import guide as guide_renderer  # noqa: WPS433
        target = root / _relative(root, out, "out") if out else root / "brand" / "guide.pdf"
        result = guide_renderer.render(root, guide, target)
        receipt = _receipt(root, "guide-render", {"pdf": str(target.relative_to(root)), "sha256": _sha256(target), **result})
        return {"status": "rendered", "pdf": str(target), "brand_source": result.get("brand_source"), "receipt": str(receipt)}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)
