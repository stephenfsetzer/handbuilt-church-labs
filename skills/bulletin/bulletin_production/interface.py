"""Deep bulletin-production interface.

Public callers use orient, produce, revise, and finalize. Rendering, imposition,
verification, storage, and approved-history details remain private here.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


IMPLEMENTATION_VERSION = "0.6.0"
SUPPORTED_TEMPLATES = {"classic", "modern"}
REQUIRED_READING_SLOTS = ("first", "psalm", "second", "gospel")
PLACEHOLDER_PATTERNS = (
    re.compile(r"\[[^\]]*(?:goes here|replace|continue each|first half)[^\]]*\]", re.I),
    re.compile(r"\bExample Episcopal Church\b", re.I),
    re.compile(r"\bExample Pastor\b", re.I),
    re.compile(r"\bExample Announcement\b", re.I),
    re.compile(r"\bReplace with this week", re.I),
)
MAX_FOOTER_ROSTER = 9

# Weekly service music uses the same hymn block shape as `hymns`. Keep this
# list deliberately small so a supplied slot cannot disappear silently.
SERVICE_MUSIC_SLOTS = frozenset({
    "prelude", "gloria", "psalm_antiphon", "offertory_anthem",
    "sursum_corda", "sanctus", "fraction_anthem", "doxology",
    "communion_anthem", "postlude",
})
LUTHERAN_SERVICE_MUSIC_SLOTS = frozenset({
    "prelude", "psalm_antiphon", "offertory_anthem", "communion_anthem",
    "postlude",
})


class StageFailure(Exception):
    """Expected operational failure with a stable code and stage."""

    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        *,
        field: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.field = field
        # Structured detail (e.g. every unresolved source-inventory section
        # or import, not just the first one named in ``message``) a caller
        # can use to resolve the specific entry, not just retry blindly.
        self.diagnostics = diagnostics


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _renderer_dir() -> Path:
    return _repo_root() / "skills" / "bulletin" / "renderer"


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(root.resolve()))) == str(root.resolve())
    except ValueError:
        return False


def _require_church_folder(church_folder: Path) -> Path:
    root = church_folder.expanduser().resolve()
    if not root.is_dir():
        raise StageFailure(
            "uninitialized_church_folder",
            "orientation",
            f"Church folder does not exist: {root}",
        )
    missing = [name for name in ("church.yaml", "brand.json") if not (root / name).is_file()]
    if missing:
        raise StageFailure(
            "uninitialized_church_folder",
            "orientation",
            f"Church folder is missing: {', '.join(missing)}",
        )
    return root


def _load_yaml_mapping(path: Path, *, stage: str) -> dict[str, Any]:
    """Load one church-owned YAML mapping without making YAML a hard import."""
    if importlib.util.find_spec("yaml") is None:
        raise StageFailure(
            "dependency_unavailable",
            stage,
            "PyYAML is required to read church.yaml",
            field="church.yaml",
        )
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StageFailure(
            "invalid_church_configuration",
            stage,
            f"Could not read {path.name}: {exc}",
            field="church.yaml",
        ) from exc
    if not isinstance(value, dict):
        raise StageFailure(
            "invalid_church_configuration",
            stage,
            "church.yaml must contain a mapping",
            field="church.yaml",
        )
    return value


def _load_church_configuration(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the two private authorities used by production.

    The returned objects are copies used for resolution only. Neither source
    file is ever rewritten by production.
    """
    church_config = _load_yaml_mapping(root / "church.yaml", stage="configuration")
    try:
        brand = json.loads((root / "brand.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageFailure(
            "invalid_brand",
            "configuration",
            f"Could not read brand.json: {exc}",
            field="brand.json",
        ) from exc
    if not isinstance(brand, dict):
        raise StageFailure("invalid_brand", "configuration", "brand.json must contain an object", field="brand.json")
    return church_config, brand


def _find_church_folder(path: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if (parent / "church.yaml").is_file() and (parent / "brand.json").is_file():
            return parent.resolve()
    raise StageFailure(
        "uninitialized_church_folder",
        "finalization",
        "Production receipt is not inside an initialized church folder",
    )


def _failure(exc: StageFailure | Exception, *, status: str = "blocked") -> dict[str, Any]:
    if isinstance(exc, StageFailure):
        error = {
            "code": exc.code,
            "stage": exc.stage,
            "message": exc.message,
        }
        if exc.field:
            error["field"] = exc.field
        if exc.diagnostics:
            error["diagnostics"] = exc.diagnostics
    else:
        status = "failed"
        error = {
            "code": "unexpected_failure",
            "stage": "unknown",
            "message": str(exc),
        }
    return {"status": status, "errors": [error], "warnings": []}


def _dependency_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for package in ("weasyprint", "pypdf", "Pillow"):
        try:
            version = importlib.metadata.version(package)
            checks.append({"name": package, "available": True, "version": version})
        except importlib.metadata.PackageNotFoundError:
            checks.append({"name": package, "available": False, "version": None})
    for command in ("pdftoppm", "pdfinfo", "pdffonts", "pdftotext"):
        path = shutil.which(command)
        checks.append({"name": command, "available": bool(path), "path": path})
    return checks


def orient(church_folder: str | Path, service_date: str | date) -> dict[str, Any]:
    """Return read-only context for a bulletin conversation."""

    try:
        root = _require_church_folder(Path(church_folder))
        date_text = service_date.isoformat() if isinstance(service_date, date) else str(service_date)
        date.fromisoformat(date_text)
        bulletins = root / "bulletins"
        log_path = bulletins / "bulletin-log.json"
        history: dict[str, Any] = {}
        if log_path.is_file():
            history = json.loads(log_path.read_text(encoding="utf-8"))
        church_config = _load_yaml_mapping(root / "church.yaml", stage="orientation")
        profile_pointer = str(church_config.get("worship_profile") or "worship/profile.yaml").strip()
        relative = Path(profile_pointer)
        profile_path = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not _inside(profile_path, root):
            raise StageFailure("unsafe_path", "orientation", "The worship profile must stay inside the church folder", field="worship_profile")
        church_context = {
            key: copy.deepcopy(church_config.get(key, {}))
            for key in ("church", "leadership", "bulletin", "lectionary", "people")
        }
        leadership = church_context["leadership"]
        roster = leadership.get("clergy_and_staff", []) if isinstance(leadership, dict) else []
        known_people = [
            {"name": person["name"], "role": person["role"]}
            for person in roster if isinstance(person, dict)
            and isinstance(person.get("name"), str) and person["name"].strip()
            and isinstance(person.get("role"), str) and person["role"].strip()
        ] if isinstance(roster, list) else []
        approved_dates = sorted(history)
        last = history[approved_dates[-1]] if approved_dates else None
        existing_work = sorted(
            str(path.relative_to(root))
            for path in bulletins.glob(f"**/{date_text}-*")
            if path.is_dir()
        ) if bulletins.is_dir() else []
        templates = (last or {}).get("templates", {})
        saved_bulletin = church_config.get("bulletin")
        saved_template = saved_bulletin.get("template") if isinstance(saved_bulletin, dict) else None
        default_template = saved_template or next(iter(templates), "classic")
        if default_template not in SUPPORTED_TEMPLATES:
            raise StageFailure("unsupported_template", "orientation", "Choose the Classic or Modern bulletin layout", field="bulletin.template")
        return {
            "status": "ok",
            "initialization_state": "returning" if approved_dates else "first_run",
            "service_date": date_text,
            "existing_work": existing_work,
            "last_approved_bulletin": last,
            "default_template": default_template,
            "church_context": church_context,
            "known_people": known_people,
            "requires_weekly_confirmation": ["preacher", "celebrant", "announcements", "service_time"],
            "carry_forward_candidates": {
                "preacher": (last or {}).get("preacher"),
                "celebrant": (last or {}).get("celebrant"),
                "template": default_template,
                "announcements": (last or {}).get("announcements", []),
            },
            "music_appearance_history": [
                {"date": approved_date, "hymns": entry.get("hymns", [])}
                for approved_date, entry in sorted(history.items(), reverse=True)
            ],
            "reading_appearance_history": [
                {"date": approved_date, "readings": entry.get("readings", {})}
                for approved_date, entry in sorted(history.items(), reverse=True)
            ],
            "worship_profile": {
                "path": profile_pointer,
                "present": profile_path.is_file(),
            },
            "available_music_assets": sorted(
                str(path.relative_to(root / "music"))
                for path in (root / "music").glob("**/*")
                if path.is_file() and path.name != "README.md"
            ) if (root / "music").is_dir() else [],
            "environment_checks": _dependency_checks(),
            "warnings": [],
        }
    except (StageFailure, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, StageFailure):
            return _failure(exc)
        return _failure(StageFailure("invalid_request", "orientation", str(exc)))


def _placeholder_hits(value: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            hits.extend(_placeholder_hits(child, f"{path}.{key}" if path else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_placeholder_hits(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in PLACEHOLDER_PATTERNS):
            hits.append(path)
    return hits


def _validate_source(source: Any, field: str) -> None:
    if not isinstance(source, dict):
        raise StageFailure("unverified_source", "validation", "Missing source record", field=field)
    for key in ("label", "location", "verified_on"):
        if not str(source.get(key, "")).strip():
            raise StageFailure(
                "unverified_source",
                "validation",
                f"Source record is missing {key}",
                field=f"{field}.{key}",
            )


def _normalize_liturgy(bulletin: dict[str, Any]) -> None:
    """Promote legacy option fields into the resolved liturgy contract."""
    options = bulletin.get("options")
    if not isinstance(options, dict):
        options = {}
    liturgy = bulletin.get("liturgy")
    if liturgy is None:
        liturgy = {}
        bulletin["liturgy"] = liturgy
    if not isinstance(liturgy, dict):
        return
    for key in ("eucharistic_prayer", "lords_prayer", "prayers_of_the_people"):
        if not str(liturgy.get(key, "")).strip() and str(options.get(key, "")).strip():
            liturgy[key] = options[key]
    for key in ("include_creed", "include_confession", "print_full_eucharistic_prayer",
                "include_first_reading", "include_second_reading"):
        if key not in liturgy and key in options:
            liturgy[key] = options[key]
    if liturgy.get("doxology", "traditional") != "custom":
        for group in ("sources", "files"):
            if isinstance(liturgy.get(group), dict):
                liturgy[group].pop("doxology", None)
    # Existing weekly records predate the resolved liturgy contract. Form III
    # is retained only as a migration value for those records; new callers
    # must supply the form through the church profile or weekly input.
    if (
        not str(liturgy.get("prayers_of_the_people", "")).strip()
        and not options.get("prayers_of_the_people")
        and "prayers_of_the_people" not in liturgy
        and not str(liturgy.get("worship_profile_ref", "")).strip()
    ):
        liturgy["prayers_of_the_people"] = "III"


def _standing_bulletin_preferences(church_config: dict[str, Any]) -> dict[str, Any]:
    """Return only confirmed standing display preferences.

    Older church files placed these values at the root. The nested ``bulletin``
    mapping is canonical for new onboarding, while the root aliases preserve
    compatibility with existing private folders.
    """
    bulletin = church_config.get("bulletin")
    bulletin = bulletin if isinstance(bulletin, dict) else {}
    defaults = bulletin.get("defaults")
    defaults = defaults if isinstance(defaults, dict) else {}
    leadership = church_config.get("leadership")
    leadership = leadership if isinstance(leadership, dict) else {}
    values: dict[str, Any] = {}
    for key in ("include_serving_today", "serving_roles", "serving_today_roles", "serving_role_policy"):
        value = bulletin.get(key)
        if value is None:
            value = defaults.get(key)
        if value is None:
            value = church_config.get(key)
        if value is None:
            value = leadership.get(key)
        if value is not None:
            values[key] = copy.deepcopy(value)
    return values


def _resolve_standing_preferences(bulletin: dict[str, Any], church_config: dict[str, Any]) -> None:
    """Carry standing preferences into options only when weekly input omits them."""
    options = bulletin.get("options")
    if options is None:
        options = {}
        bulletin["options"] = options
    if not isinstance(options, dict):
        raise StageFailure("invalid_request", "validation", "Bulletin options must be a mapping", field="options")
    saved_bulletin = church_config.get("bulletin")
    if isinstance(saved_bulletin, dict) and not bulletin.get("template") and not bulletin.get("_template"):
        if saved_bulletin.get("template"):
            bulletin["template"] = saved_bulletin["template"]
    if isinstance(saved_bulletin, dict) and saved_bulletin.get("doxology_music") is not None:
        music = bulletin.setdefault("service_music", {})
        if not isinstance(music, dict):
            raise StageFailure("invalid_request", "validation", "Service music must be a mapping", field="service_music")
        if "doxology" not in music:
            music["doxology"] = copy.deepcopy(saved_bulletin["doxology_music"])
    liturgy = bulletin.get("liturgy") or {}
    psalm = (bulletin.get("readings") or {}).get("psalm")
    if isinstance(psalm, dict):
        for saved, weekly in (("psalm_format", "format"), ("psalm_response_start", "response_start")):
            if liturgy.get(saved) and not psalm.get(weekly):
                psalm[weekly] = liturgy[saved]
    standing = _standing_bulletin_preferences(church_config)
    for key, value in standing.items():
        if key not in options or options[key] is None:
            options[key] = copy.deepcopy(value)


PARISH_INFORMATION_SCOPES = ("before_service", "after_service")


def _validate_parish_information_shape(value: Any, field: str) -> None:
    """Reject an unsafe or unrecognized parish-information shape outright.

    Shared by the saved standing value (``church.yaml bulletin.parish_information``)
    and the resolved weekly value, so a hand-edited bad standing config fails
    here just as clearly as a bad weekly override, rather than being
    silently dropped. Consistent with the JSON schema: only an *absent*
    scope means "inherit the saved sections"; an explicit ``null`` is
    neither a list nor a valid override and is rejected here, not treated
    as either inheritance or suppression. Never coerces a non-string title
    or text (``None``, a number, a list, a mapping) into text: each must
    already be an actual nonblank string.
    """
    if not isinstance(value, dict) or set(value) - set(PARISH_INFORMATION_SCOPES):
        raise StageFailure(
            "invalid_parish_information",
            "validation",
            f"{field} may only use: {', '.join(PARISH_INFORMATION_SCOPES)}",
            field=field,
        )
    for scope in PARISH_INFORMATION_SCOPES:
        if scope not in value:
            continue
        sections = value[scope]
        scope_field = f"{field}.{scope}"
        if not isinstance(sections, list):
            raise StageFailure(
                "invalid_parish_information", "validation", f"{scope_field} must be a list", field=scope_field
            )
        for index, entry in enumerate(sections):
            entry_field = f"{scope_field}[{index}]"
            if not isinstance(entry, dict) or set(entry) - {"title", "text", "source"}:
                raise StageFailure(
                    "invalid_parish_information",
                    "validation",
                    f"{entry_field} must contain only title, text, and an optional source",
                    field=entry_field,
                )
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                raise StageFailure(
                    "invalid_parish_information", "validation", f"{entry_field}.title must be nonblank text",
                    field=f"{entry_field}.title",
                )
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                raise StageFailure(
                    "invalid_parish_information", "validation", f"{entry_field}.text must be nonblank text",
                    field=f"{entry_field}.text",
                )
            if "source" in entry:
                _validate_source(entry["source"], f"{entry_field}.source")


def _resolve_parish_information(bulletin: dict[str, Any], church_config: dict[str, Any]) -> None:
    """Carry the saved standing parish-information sections into the week.

    Ordered title-and-text sections for recurring content that belongs
    neither to a dated announcement nor to any other supported standing
    field: a welcome, an accessibility note, pastoral contact, or a
    worship-book explanation. Each scope resolves independently: a weekly
    value, present at all, always wins, whether it is a non-empty override
    or an explicit empty list suppressing that scope for the week. A scope
    the week omits entirely falls back to the saved sections in
    ``church.yaml bulletin.parish_information``. The saved value is
    validated here too, so a malformed hand-edited standing config blocks
    with a clear error instead of silently losing its content.
    """
    saved_bulletin = church_config.get("bulletin")
    saved = saved_bulletin.get("parish_information") if isinstance(saved_bulletin, dict) else None
    if saved is not None:
        _validate_parish_information_shape(saved, "church.yaml bulletin.parish_information")
    saved = saved if isinstance(saved, dict) else {}
    weekly = bulletin.get("parish_information")
    if weekly is None:
        # Absent entirely (not an explicit null further below): inherit
        # every scope from the saved sections.
        weekly = {}
    if not isinstance(weekly, dict) or set(weekly) - set(PARISH_INFORMATION_SCOPES):
        # Leave an unsafe or unrecognized weekly value exactly as supplied.
        # _validate_parish_information (run after resolution) rejects it
        # clearly; silently discarding an unrecognized key here instead
        # would let it through as if the week had said nothing.
        bulletin["parish_information"] = weekly
        return
    resolved: dict[str, Any] = {}
    for scope in PARISH_INFORMATION_SCOPES:
        resolved[scope] = weekly[scope] if scope in weekly else copy.deepcopy(saved.get(scope, []))
    bulletin["parish_information"] = resolved


def _validate_parish_information(bulletin: dict[str, Any]) -> None:
    """Reject an unsafe or unrecognized resolved parish-information shape.

    Never silently drops or reinterprets a bad value: an unknown scope, a
    non-list scope (including an explicit ``null``), a section missing its
    title or text, a non-string title or text, or an unknown field inside a
    section all fail clearly rather than rendering nothing or something
    unintended such as the literal text "None".
    """
    value = bulletin.get("parish_information")
    if value is None:
        return
    _validate_parish_information_shape(value, "parish_information")


def _leadership_entries(leadership: dict[str, Any]) -> list[tuple[str, Any]]:
    entries: list[tuple[str, Any]] = []
    if (
        "governing_body" in leadership
        and leadership.get("governing_body") is not None
        and not isinstance(leadership.get("governing_body"), dict)
    ):
        raise StageFailure(
            "invalid_leadership_entry",
            "validation",
            "Leadership governing_body must be an object",
            field="leadership.governing_body",
        )
    for group in ("staff", "clergy_and_staff", "officers", "members"):
        value = leadership.get(group, [])
        if value is None:
            continue
        if not isinstance(value, list):
            raise StageFailure(
                "invalid_leadership_entry",
                "validation",
                f"Leadership {group} must be a list of entries",
                field=f"leadership.{group}",
            )
        entries.extend((group, entry) for entry in value)
    governing = leadership.get("governing_body")
    if isinstance(governing, dict):
        for group in ("officers", "members"):
            value = governing.get(group, [])
            if value is None:
                continue
            if not isinstance(value, list):
                raise StageFailure(
                    "invalid_leadership_entry",
                    "validation",
                    f"Leadership governing_body.{group} must be a list of entries",
                    field=f"leadership.governing_body.{group}",
                )
            entries.extend((f"governing_body.{group}", entry) for entry in value)
    for body_key, body in leadership.items():
        if body_key in {"governing_body", "staff", "clergy_and_staff", "officers", "members"} or not isinstance(body, dict):
            continue
        # Private church files may name the governing body directly, such as
        # ``vestry``. This remains data, not a public default.
        if any(key in body for key in ("officers", "members", "body_name", "label")):
            for group in ("officers", "members"):
                value = body.get(group, [])
                if value is None:
                    continue
                if not isinstance(value, list):
                    raise StageFailure(
                        "invalid_leadership_entry",
                        "validation",
                        f"Leadership {body_key}.{group} must be a list of entries",
                        field=f"leadership.{body_key}.{group}",
                    )
                entries.extend((f"{body_key}.{group}", entry) for entry in value)
    return entries


LEADERSHIP_PLACEMENTS = ("auto", "footer", "body")


def _resolve_leadership_placement(entry_count: int, requested: Any) -> str:
    """Resolve where the leadership roster prints without guessing silently.

    ``auto`` keeps the running-footer roster for a small roster and flows a
    roster over the footer's capacity into a normal readable body section.
    An explicit ``footer`` or ``body`` choice always wins, so an explicit
    footer request still enforces the footer's capacity. Only a missing or
    blank value defaults to ``auto``; any other unrecognized value is a
    configuration error rather than a silent fallback.
    """
    value = str(requested or "").strip().lower()
    if not value:
        value = "auto"
    if value not in LEADERSHIP_PLACEMENTS:
        raise StageFailure(
            "invalid_leadership_placement",
            "validation",
            f"leadership.placement must be one of {', '.join(LEADERSHIP_PLACEMENTS)}, not {value!r}",
            field="leadership.placement",
        )
    if value == "auto":
        return "footer" if entry_count <= MAX_FOOTER_ROSTER else "body"
    return value


def _validate_leadership(church_config: dict[str, Any]) -> dict[str, Any]:
    leadership = church_config.get("leadership")
    if not isinstance(leadership, dict) or leadership.get("print_in_bulletin") is not True:
        return {"entries": [], "printed": False, "placement": "footer"}
    entries = _leadership_entries(leadership)
    governing = leadership.get("governing_body")
    governing = governing if isinstance(governing, dict) else {}
    named_bodies = [
        value for key, value in leadership.items()
        if isinstance(value, dict) and key not in {"governing_body"}
        and any(child in value for child in ("officers", "members", "body_name", "label"))
    ]
    governing_entries = [
        group for group, _ in entries
        if group.startswith("governing_body") or ".officers" in group or ".members" in group
        or group in {"officers", "members"}
    ]
    label = governing.get("label")
    if label is None:
        label = leadership.get("governing_body_label")
    if label is None:
        labels = [body.get("label", body.get("body_name")) for body in named_bodies]
        label = next((value for value in labels if value is not None), None)
    if governing_entries and not str(label or "").strip():
        raise StageFailure(
            "unresolved_leadership_label",
            "validation",
            "Leadership has governing-body officers or members but no exact governing-body label is confirmed",
            field="leadership.governing_body.label",
        )
    for group, entry in entries:
        if not isinstance(entry, dict):
            raise StageFailure(
                "invalid_leadership_entry",
                "validation",
                "Each leadership entry must be an object with a name and role",
                field=f"leadership.{group}",
            )
        role_optional = group.endswith(".members") or group == "members"
        if not str(entry.get("name", "")).strip() or (not role_optional and not str(entry.get("role", "")).strip()):
            raise StageFailure(
                "invalid_leadership_entry",
                "validation",
                "Each leadership entry requires nonblank name and role",
                field=f"leadership.{group}",
            )
    printed = leadership.get("print_in_bulletin") is True
    placement = _resolve_leadership_placement(len(entries), leadership.get("placement"))
    if printed and placement == "footer" and len(entries) > MAX_FOOTER_ROSTER:
        raise StageFailure(
            "leadership_roster_capacity",
            "quality_gate",
            f"The printed leadership roster has {len(entries)} people; the running footer supports at most {MAX_FOOTER_ROSTER}. Set leadership.placement to body for a directory section, or send this bulletin for layout review",
            field="leadership",
        )
    return {"entries": copy.deepcopy(entries), "printed": printed, "label": label or "", "placement": placement}


def _qr_item_path(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return None
    for key in ("image", "path", "file", "asset"):
        value = item.get(key)
        if str(value or "").strip():
            return str(value).strip()
    return None


def _qr_copy_complete(qr: dict[str, Any], key: str) -> bool:
    custom = qr.get("custom_copy") or qr.get("copy")
    if not isinstance(custom, dict):
        return False
    # The first promoted shape used flat keys. Keep it as a compatibility
    # input while new onboarding may use nested action data.
    prefix = "connect" if key == "connect" else "give"
    if str(custom.get(f"{prefix}_head", "")).strip() or str(custom.get(f"{prefix}_body", "")).strip():
        return bool(
            str(custom.get("heading", "")).strip()
            and str(custom.get(f"{prefix}_head", "")).strip()
        )
    if not str(custom.get("heading", "")).strip():
        return False
    item = custom.get(key)
    if isinstance(item, str):
        return bool(item.strip())
    if not isinstance(item, dict):
        return False
    # Supporting body copy is optional. The action heading is the required
    # church-facing wording for each configured code.
    action_heading = item.get("heading", item.get("label", ""))
    return bool(str(action_heading).strip())


def _validate_qr(
    brand: dict[str, Any],
    root: Path,
    warnings: list[dict[str, Any]],
    church_config: dict[str, Any] | None = None,
) -> None:
    qr = brand.get("qr")
    if not isinstance(qr, dict):
        return
    urls = qr.get("urls") if isinstance(qr.get("urls"), dict) else {}
    bulletin = church_config.get("bulletin", {}) if isinstance(church_config, dict) else {}
    bulletin_qr = bulletin.get("qr", {}) if isinstance(bulletin, dict) else {}
    bulletin_qr = bulletin_qr if isinstance(bulletin_qr, dict) else {}
    configured = [(key, item) for key, item in qr.items() if key not in {"_comment", "urls", "standard_copy_accepted", "custom_copy", "copy"} and _qr_item_path(item)]
    if not configured:
        return
    standard_accepted = qr.get("standard_copy_accepted") is True or bulletin_qr.get("standard_copy_accepted") is True
    for key, item in configured:
        path = _qr_item_path(item)
        if not path:
            continue
        bulletin_item = bulletin_qr.get(key)
        if isinstance(bulletin_item, dict):
            item_url = bulletin_item.get("confirmed_url") or bulletin_item.get("url") or bulletin_item.get("destination")
            if item_url and key not in urls:
                urls[key] = item_url
        if isinstance(item, str):
            raise StageFailure(
                "unresolved_qr_configuration",
                "validation",
                f"QR image {key} uses a legacy path string; provide a configured image object with a confirmed URL",
                field=f"brand.qr.{key}",
            )
        url = item.get("confirmed_url") or item.get("url") or item.get("destination") or urls.get(key)
        if not isinstance(url, str) or not re.match(r"^https?://[^\s]+$", url.strip()):
            raise StageFailure(
                "unresolved_qr_configuration",
                "validation",
                f"QR image {key} requires a confirmed http(s) destination URL",
                field=f"brand.qr.{key}.url",
            )
        if item.get("url_confirmed") is False or item.get("confirmed") is False:
            raise StageFailure(
                "unresolved_qr_configuration",
                "validation",
                f"QR destination for {key} is not confirmed",
                field=f"brand.qr.{key}.url",
            )
        copy_qr = dict(qr)
        if not copy_qr.get("custom_copy") and isinstance(bulletin_qr.get("copy"), dict):
            copy_qr["copy"] = bulletin_qr["copy"]
        if not standard_accepted and not _qr_copy_complete(copy_qr, key):
            raise StageFailure(
                "unresolved_qr_configuration",
                "validation",
                f"QR image {key} requires accepted standard invitation wording or complete custom wording",
                field="brand.qr.standard_copy_accepted",
            )
        candidate = Path(path)
        resolved_candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if not _inside(resolved_candidate, root):
            raise StageFailure(
                "unsafe_path",
                "asset_resolution",
                f"QR image escapes the church folder: {path}",
                field=f"brand.qr.{key}",
            )
        if not resolved_candidate.is_file():
            warnings.append({
                "code": "qr_asset_missing",
                "field": f"brand.qr.{key}",
                "message": f"QR image was not found: {path}",
            })


def _validate_brand_asset_paths(brand: dict[str, Any], root: Path) -> None:
    """Keep logo and QR assets inside the private church folder."""
    def check(raw: str, field: str) -> None:
        candidate = Path(raw)
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if not _inside(resolved, root):
            raise StageFailure(
                "unsafe_path",
                "asset_resolution",
                f"Brand asset escapes the church folder: {raw}",
                field=field,
            )

    logo = brand.get("logo", {})
    if isinstance(logo, dict):
        for key, value in logo.items():
            if isinstance(value, str) and value.strip():
                check(value, f"brand.logo.{key}")
    qr = brand.get("qr", {})
    if isinstance(qr, dict):
        for key, value in qr.items():
            if key in {"_comment", "urls", "copy", "custom_copy", "standard_copy_accepted"}:
                continue
            path = _qr_item_path(value)
            if path:
                check(path, f"brand.qr.{key}")


def _validate_lyric_layout(bulletin: dict[str, Any]) -> None:
    """Validate lyric layout data without making a rights determination."""
    lyrics_entries: list[tuple[str, dict[str, Any]]] = []
    for group_name in ("hymns", "service_music"):
        group = bulletin.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for slot, hymn in group.items():
            if not isinstance(hymn, dict) or "lyrics" not in hymn or not hymn.get("lyrics"):
                continue
            lyrics_entries.append((f"{group_name}.{slot}", hymn))
    if not lyrics_entries:
        return
    for field, hymn in lyrics_entries:
        if "lyric_columns" in hymn and hymn["lyric_columns"] not in (1, 2):
            raise StageFailure("invalid_lyric_columns", "validation", "lyric_columns must be 1 or 2", field=f"{field}.lyric_columns")


def _validate_service_music(bulletin: dict[str, Any]) -> None:
    """Reject service music that the selected plan cannot render."""
    music = bulletin.get("service_music", {})
    if music is None:
        return
    if not isinstance(music, dict):
        raise StageFailure("invalid_request", "validation", "Service music must be a mapping", field="service_music")
    plan = (bulletin.get("liturgy") or {}).get("service_plan")
    allowed = (LUTHERAN_SERVICE_MUSIC_SLOTS
               if plan == "lutheran-holy-communion" else SERVICE_MUSIC_SLOTS)
    for slot, entry in music.items():
        if not entry:
            continue
        field = f"service_music.{slot}"
        if slot not in allowed:
            if plan == "lutheran-holy-communion":
                raise StageFailure(
                    "unsupported_service_music",
                    "validation",
                    f"The Lutheran service plan does not have a supported position for {slot!r}. Use one of: {', '.join(sorted(allowed))}.",
                    field=field,
                )
            raise StageFailure(
                "unsupported_service_music",
                "validation",
                f"Unknown service music slot {slot!r}. Use one of: {', '.join(sorted(allowed))}.",
                field=field,
            )
        if not isinstance(entry, dict):
            raise StageFailure(
                "invalid_service_music",
                "validation",
                "Service music entries use the hymn shape with title, image(s), custom_text, or lyrics.",
                field=field,
            )


def _validate_service_variant(bulletin: dict[str, Any], church_root: Path) -> None:
    liturgy = bulletin.get("liturgy")
    if not isinstance(liturgy, dict) or "service_variant" not in liturgy:
        return
    variant = liturgy.get("service_variant")
    provenance = liturgy.get("service_variant_provenance")
    if not isinstance(variant, dict):
        raise StageFailure("invalid_service_variant", "validation", "liturgy.service_variant must be an object", field="liturgy.service_variant")
    if not isinstance(provenance, dict):
        raise StageFailure("service_variant_provenance_required", "validation", "A resolved service variant requires matching provenance", field="liturgy.service_variant_provenance")
    variant_id = variant.get("id")
    if not isinstance(variant_id, str) or not variant_id.strip():
        raise StageFailure("invalid_service_variant", "validation", "A service variant requires a nonblank id", field="liturgy.service_variant.id")
    if provenance.get("variant_id") != variant_id:
        raise StageFailure("service_variant_provenance_mismatch", "validation", "Service variant provenance must name the resolved variant id", field="liturgy.service_variant_provenance.variant_id")
    chain = provenance.get("order_file_chain")
    if not isinstance(chain, list) or any(not isinstance(path, str) or not path.strip() for path in chain):
        raise StageFailure("invalid_service_variant_provenance", "validation", "order_file_chain must be a list of nonblank paths", field="liturgy.service_variant_provenance.order_file_chain")
    policy = provenance.get("confirmation_policy")
    if not isinstance(policy, str) or not policy.strip():
        raise StageFailure("invalid_service_variant_provenance", "validation", "A service variant requires a confirmation_policy", field="liturgy.service_variant_provenance.confirmation_policy")
    if variant_id == "none":
        if chain or policy != "explicit_none":
            raise StageFailure("invalid_service_variant_provenance", "validation", "The none service variant requires an empty order_file_chain and explicit_none confirmation policy", field="liturgy.service_variant_provenance")
        return
    profile_ref = liturgy.get("worship_profile_ref")
    if not isinstance(profile_ref, str) or not profile_ref.strip():
        raise StageFailure("invalid_service_variant_provenance", "validation", "A selected service variant requires worship_profile_ref", field="liturgy.worship_profile_ref")
    if not chain:
        raise StageFailure("invalid_service_variant_provenance", "validation", "A selected service variant requires a nonempty order_file_chain", field="liturgy.service_variant_provenance.order_file_chain")
    for raw_path in chain:
        posix = PurePosixPath(raw_path)
        windows = PureWindowsPath(raw_path)
        if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts:
            raise StageFailure("unsafe_service_variant_path", "validation", "Service variant order files must be church-relative paths without parent traversal", field="liturgy.service_variant_provenance.order_file_chain")
        resolved_path = (church_root / posix).resolve()
        if not _inside(resolved_path, church_root) or not resolved_path.is_file():
            raise StageFailure("missing_service_variant_source", "asset_resolution", f"Service variant order file was not found inside the church folder: {raw_path}", field="liturgy.service_variant_provenance.order_file_chain")


def _liturgy_identifier(key: str, value: Any, liturgy: dict[str, Any]) -> str:
    """Map a selected worship choice to the renderer's shipped identifier."""
    selected = str(value or "").strip()
    aliases = {
        ("eucharistic_prayer", "A"): "eucharistic-prayer-a",
        ("eucharistic_prayer", "A_full"): "eucharistic-prayer-a-full",
        ("eucharistic_prayer", "B"): "eucharistic-prayer-b",
        ("eucharistic_prayer", "C"): "eucharistic-prayer-c",
        ("eucharistic_prayer", "D"): "eucharistic-prayer-d",
        ("lords_prayer", "contemporary"): "lords-prayer-contemporary",
        ("prayers_of_the_people", "I"): "prayers-of-the-people-i",
        ("prayers_of_the_people", "II"): "prayers-of-the-people-ii",
        ("prayers_of_the_people", "IV"): "prayers-of-the-people-iv",
        ("prayers_of_the_people", "V"): "prayers-of-the-people-v",
        ("prayers_of_the_people", "VI"): "prayers-of-the-people-vi",
        ("lords_prayer", "traditional"): "lords-prayer-traditional",
        ("prayers_of_the_people", "III"): "prayers-of-the-people",
    }
    if key == "eucharistic_prayer" and selected in ("A", "B", "C", "D") and liturgy.get("print_full_eucharistic_prayer"):
        return f"eucharistic-prayer-{selected.lower()}-full"
    return aliases.get((key, selected), selected)


def _private_liturgy_source(raw: Any, root: Path, field: str) -> Path | None:
    """Resolve one church-owned source and reject unsafe paths early."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw)
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if windows.is_absolute() and not posix.is_absolute():
        raise StageFailure("unsafe_path", "asset_resolution", f"Liturgy source escapes the church folder: {raw}", field=field)
    if posix.is_absolute() or windows.is_absolute():
        if not _inside(candidate, root):
            raise StageFailure("unsafe_path", "asset_resolution", f"Liturgy source escapes the church folder: {raw}", field=field)
    candidates = [candidate] if candidate.is_absolute() else [root / candidate, root / "worship" / "liturgy" / candidate.name]
    resolved_candidates = [item.resolve() for item in candidates]
    if any(not _inside(item, root) for item in resolved_candidates):
        raise StageFailure("unsafe_path", "asset_resolution", f"Liturgy source escapes the church folder: {raw}", field=field)
    resolved = next((item for item in resolved_candidates if item.is_file()), None)
    if resolved is None:
        raise StageFailure("missing_liturgy_source", "asset_resolution", f"Liturgy source was not found: {raw}", field=field)
    if not _inside(resolved, root):
        raise StageFailure("unsafe_path", "asset_resolution", f"Liturgy source escapes the church folder: {raw}", field=field)
    from ..liturgy_sources import LiturgySourceError, require_verified_source
    try:
        require_verified_source(root, resolved)
    except LiturgySourceError as exc:
        raise StageFailure("unverified_liturgy_source", "asset_resolution", str(exc), field=field) from exc
    return resolved


def _source_is_shipped(raw: Any, root: Path) -> bool:
    if not isinstance(raw, str) or not raw.strip():
        return False
    path = Path(raw)
    # Match staging's private-first precedence, including bare shipped names.
    if any(item.is_file() for item in (root / path, root / "worship" / "liturgy" / path.name)):
        return False
    return raw == path.stem and (_renderer_dir() / "liturgy" / f"{raw}.md").is_file()


def _validate_liturgy_sources(bulletin: dict[str, Any], church_root: Path) -> None:
    """Ensure every worship section has shipped or private text before render."""
    liturgy = bulletin.get("liturgy")
    if not isinstance(liturgy, dict):
        return
    files = liturgy.get("files") if isinstance(liturgy.get("files"), dict) else {}
    sources = liturgy.get("sources") if isinstance(liturgy.get("sources"), dict) else {}
    renderer_liturgy = _renderer_dir() / "liturgy"
    from ..sunday_library import SundayLibraryError, verify_shipped_liturgy
    try:
        manifest = json.loads((_repo_root() / "skills/bulletin/resources/bcp1979/manifest.json").read_text())
        for identifier in manifest["liturgy"]:
            verify_shipped_liturgy(identifier)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StageFailure("bundled_liturgy_changed", "asset_resolution", f"Restore the verified plugin Sunday library before producing: {exc}", field="liturgy") from exc
    plan = str(liturgy.get("service_plan", "")).strip()
    required: list[tuple[str, str]] = []

    def variant_identifier(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("unit") or value.get("file") or value.get("id") or "").strip()
        return str(value or "").strip()

    if plan == "episcopal-rite-ii":
        for key in ("eucharistic_prayer", "lords_prayer", "prayers_of_the_people"):
            value = str(liturgy.get(key, "")).strip()
            if value:
                required.append((key, _liturgy_identifier(key, value, liturgy)))
        variant = liturgy.get("service_variant")
        if isinstance(variant, dict):
            for operation_name, operation in (("replace", variant.get("replace", [])), ("insert", variant.get("insert", []))):
                for item in operation or []:
                    if not isinstance(item, dict):
                        continue
                    values = item.get("with") if operation_name == "replace" else item.get("units", [])
                    if not isinstance(values, list):
                        values = [values]
                    for value in values:
                        identifier = variant_identifier(value)
                        if identifier:
                            required.append(("service_variant", identifier))
    elif plan == "lutheran-holy-communion" and liturgy.get("worship_profile_ref"):
        from ..worship_resolution import required_lutheran_units
        required = [(key, key) for key in required_lutheran_units(liturgy)]

    for group_name, group in (("sources", sources), ("files", files)):
        for key, raw in group.items():
            if not _source_is_shipped(raw, church_root):
                _private_liturgy_source(raw, church_root, f"liturgy.{group_name}.{key}")
    if liturgy.get("doxology") == "custom" and not (files.get("doxology") or sources.get("doxology")):
        raise StageFailure("missing_liturgy_source", "asset_resolution", "Provide the church's verified doxology text before using a custom doxology.", field="liturgy.files.doxology")

    checked: set[tuple[str, str]] = set()
    for key, identifier in required:
        marker = (key, identifier)
        if marker in checked:
            continue
        checked.add(marker)
        raw = sources.get(key)
        if raw is None:
            raw = sources.get("eucharistic_prayer") if key == "eucharistic_prayer" else None
        if raw is not None:
            if not isinstance(raw, str) or not raw.strip():
                raise StageFailure(
                    "invalid_liturgy_source",
                    "asset_resolution",
                    f"Liturgy source for {key} must be a church-relative file path",
                    field=f"liturgy.sources.{key}",
                )
            raw_text = str(raw).strip() if isinstance(raw, str) else ""
            if not _source_is_shipped(raw_text, church_root):
                _private_liturgy_source(raw, church_root, f"liturgy.sources.{key}")
            continue
        raw_file = files.get(identifier)
        if raw_file is None:
            raw_file = files.get(key)
        if raw_file is not None:
            if not _source_is_shipped(raw_file, church_root):
                _private_liturgy_source(raw_file, church_root, f"liturgy.files.{key}")
            continue
        bundled = renderer_liturgy / f"{identifier}.md"
        if bundled.is_file():
            if "[Proper Preface inserted here]" in bundled.read_text() and not str(bulletin.get("proper_preface") or "").strip():
                raise StageFailure(
                    "proper_preface_required", "validation",
                    "The agent must select the verified occasion's proper preface from the bundled Sunday library before printing the full prayer.",
                    field="proper_preface",
                )
            continue
        raise StageFailure(
            "missing_liturgy_source",
            "asset_resolution",
            f"No shipped or church-owned liturgy source is available for {key.replace('_', ' ')} {liturgy.get(key, identifier)}. Provide a confirmed source under worship/liturgy/.",
            field=f"liturgy.files.{key}" if plan == "lutheran-holy-communion" else f"liturgy.{key}",
        )


def _validate_back_page_merge(bulletin: dict[str, Any]) -> None:
    options = bulletin.get("options") or {}
    if not isinstance(options, dict) or options.get("merge_back_page") is not True:
        return
    closing = (bulletin.get("hymns") or {}).get("closing")
    if not isinstance(closing, dict):
        return
    images = closing.get("images") or ([closing["image"]] if closing.get("image") else [])
    unsafe = bool(images)
    if unsafe:
        raise StageFailure(
            "back_page_merge_unsafe",
            "validation",
            "Back-page merge cannot safely combine a closing hymn with image engraving; send this layout for explicit review",
            field="options.merge_back_page",
        )


def _validate_reading_presentation(reading: dict[str, Any], slot: str) -> None:
    field = f"readings.{slot}"
    def fail(message: str) -> None:
        raise StageFailure("reading_presentation_unresolved", "validation", message, field=field)
    if slot != "psalm":
        form = reading.get("format", "prose")
        if form not in ("prose", "poetry"):
            fail("Choose prose or poetry for this reading.")
        paragraphs = reading.get("paragraphs")
        if paragraphs is not None:
            if not isinstance(paragraphs, list) or not paragraphs or any(not isinstance(p, str) or not p.strip() for p in paragraphs):
                fail("Supply the reading's verified paragraphs as a list of nonempty text paragraphs.")
            reading["text"] = "\n\n".join(paragraphs)
        blocks = [p.strip() for p in re.split(r"\n\s*\n", str(reading.get("text", ""))) if p.strip()]
        numbered = [p for p in blocks if re.match(r"^\d{1,3}[ .]\s*\D", p)]
        if len(numbered) >= 2 and len(numbered) >= len(blocks) / 2:
            fail("This reading still appears to have printed verse numbers. Compare it with the source and supply its actual paragraphs without verse labels; preserve poetry lines where appropriate.")
        return
    form = reading.get("format")
    if form is None:
        return  # Existing records retain their explicit text and bold markup.
    if form not in ("responsive_half_verse", "responsive_whole_verse", "unison", "plain"):
        fail("Choose how the congregation will read the psalm: half verses, whole verses, together, or plain text.")
    if reading.get("response_start", "second") not in ("first", "second"):
        fail("Choose whether the people begin on the first or second whole verse.")
    verses = reading.get("verses")
    if verses is not None:
        if not isinstance(verses, list) or not verses:
            fail("Supply the psalm's numbered verses.")
        keys = ("number", "first") if form == "responsive_half_verse" else ("number", "text")
        if any(not isinstance(v, dict) or any(not str(v.get(k, "")).strip() for k in keys) for v in verses):
            fail("Each psalm verse needs its number and verified text; half-verse responses need both halves.")
        if form == "responsive_half_verse" and any(
            not str(v.get("second", "")).strip()
            and not ("asterisk" in v and v["asterisk"] is None and v.get("second") == "")
            for v in verses
        ):
            fail("Half-verse responses need both halves, except when the verified source explicitly has no asterisk division.")
        reading["text"] = "\n\n".join(f"{v['number']} " + ((v['first'] + (" * " + v['second'] if v['second'] else "")) if form == "responsive_half_verse" else str(v['text'])) for v in verses)
    else:
        blocks = [p.strip() for p in re.split(r"\n\s*\n", str(reading.get("text", ""))) if p.strip()]
        if form.startswith("responsive") and (not blocks or any(not re.match(r"^\d+\s+", p) for p in blocks)):
            fail("Keep the psalm verse numbers and confirm the response pattern from the source.")
        if form == "responsive_half_verse" and any(not re.search(r"(?<!\*)\*(?!\*)", p) for p in blocks):
            fail("Mark each verified psalm half-verse division with a single asterisk, or supply first and second halves.")


def _validate_bulletin(bulletin: dict[str, Any]) -> None:
    hits = _placeholder_hits(bulletin)
    if hits:
        raise StageFailure(
            "placeholder_content",
            "validation",
            "Unresolved example or placeholder content remains",
            field=hits[0],
        )
    service = bulletin.get("service")
    if not isinstance(service, dict):
        raise StageFailure("invalid_request", "validation", "Missing service data", field="service")
    for key in (
        "date",
        "occasion",
        "proper",
        "lectionary_track",
        "preacher",
        "celebrant",
        "liturgical_color",
    ):
        if not str(service.get(key, "")).strip():
            raise StageFailure("invalid_request", "validation", f"Missing {key}", field=f"service.{key}")
    try:
        date.fromisoformat(str(service["date"]))
    except ValueError as exc:
        raise StageFailure("invalid_request", "validation", str(exc), field="service.date") from exc
    template = bulletin.get("template") or bulletin.get("_template") or "classic"
    if template not in SUPPORTED_TEMPLATES:
        raise StageFailure(
            "unsupported_template",
            "validation",
            f"Unsupported template: {template}",
            field="template",
        )
    readings = bulletin.get("readings")
    if not isinstance(readings, dict):
        raise StageFailure("invalid_request", "validation", "Missing readings", field="readings")
    liturgy = bulletin.get("liturgy")
    if not isinstance(liturgy, dict):
        raise StageFailure("unresolved_liturgy", "validation", "Missing resolved worship choices", field="liturgy")
    include_first = liturgy.get("include_first_reading", True) if isinstance(liturgy, dict) else True
    include_second = liturgy.get("include_second_reading", True) if isinstance(liturgy, dict) else True
    for key, value in (("include_first_reading", include_first), ("include_second_reading", include_second)):
        if not isinstance(value, bool):
            raise StageFailure("unresolved_liturgy", "validation", f"Confirm whether {key.replace('_', ' ')} should be included before producing", field=f"liturgy.{key}")
    if not include_first and not include_second:
        raise StageFailure("invalid_request", "validation", "At least one non-Gospel reading must be included", field="liturgy.include_first_reading")
    required_slots = ["psalm", "gospel"]
    if include_first:
        required_slots.append("first")
    if include_second:
        required_slots.append("second")
    for slot in REQUIRED_READING_SLOTS:
        reading = readings.get(slot)
        if not isinstance(reading, dict):
            if slot not in required_slots and reading is None:
                continue
            raise StageFailure("invalid_request", "validation", f"Missing {slot}", field=f"readings.{slot}")
        _validate_reading_presentation(reading, slot)
        citation_key = "number" if slot == "psalm" else "citation"
        for key in (citation_key, "text"):
            if not str(reading.get(key, "")).strip():
                raise StageFailure(
                    "invalid_request",
                    "validation",
                    f"Missing {key}",
                    field=f"readings.{slot}.{key}",
                )
        _validate_source(reading.get("source"), f"readings.{slot}.source")
    if not str(bulletin.get("collect_of_day", "")).strip():
        raise StageFailure(
            "invalid_request",
            "validation",
            "Missing collect of the day",
            field="collect_of_day",
        )
    for key, choices in {
        "doxology": ("traditional", "custom", "omit"),
        "prayer_presentation": ("continuous", "repeated_labels"),
        "rubric_style": ("concise", "source"),
    }.items():
        if key in liturgy and liturgy[key] not in choices:
            raise StageFailure("unresolved_liturgy", "validation", f"Confirm the {key.replace('_', ' ')} preference.", field=f"liturgy.{key}")
    for key in ("include_creed", "include_confession", "print_full_eucharistic_prayer") if liturgy.get("service_plan") == "episcopal-rite-ii" else ():
        if key in liturgy and liturgy[key] is None:
            raise StageFailure(
                "unresolved_liturgy",
                "validation",
                f"Confirm whether {key.replace('_', ' ')} should be included before producing",
                field=f"liturgy.{key}",
            )
    for key in ("eucharistic_prayer", "lords_prayer"):
        if not str(liturgy.get(key, "")).strip():
            raise StageFailure(
                "unresolved_liturgy",
                "validation",
                f"No resolved {key.replace('_', ' ')} was supplied",
                field=f"liturgy.{key}",
            )
    if (
        liturgy.get("service_plan") == "episcopal-rite-ii"
        and liturgy.get("worship_profile_ref")
        and "prayers_of_the_people" not in liturgy
    ) or ("prayers_of_the_people" in liturgy and not str(liturgy.get("prayers_of_the_people", "")).strip()):
        raise StageFailure(
            "unresolved_liturgy",
            "validation",
            "No resolved Prayers of the People form was supplied",
            field="liturgy.prayers_of_the_people",
        )
    if not str(liturgy.get("service_plan", "")).strip():
        raise StageFailure(
            "unresolved_liturgy",
            "validation",
            "No resolved service plan was supplied",
            field="liturgy.service_plan",
        )
    blessing = str(liturgy.get("blessing", "")).strip()
    if not blessing:
        raise StageFailure(
            "unresolved_blessing",
            "validation",
            "Resolve a blessing or choose omit explicitly before producing the bulletin",
            field="liturgy.blessing",
        )


def _stage_effective_brand(
    brand: dict[str, Any], church_config: dict[str, Any], root: Path, stage_dir: Path
) -> Path:
    """Stage current church settings with the private visual assets."""
    effective = copy.deepcopy(brand)
    identity = church_config.get("church")
    if isinstance(identity, dict):
        printed = effective.setdefault("church", {})
        previous_name = printed.get("name")
        for key in ("name", "short_name", "address", "website"):
            if isinstance(identity.get(key), str) and identity[key].strip():
                printed[key] = identity[key]
        # Keep a deliberately different display name, but refresh a copied
        # formal name when the church identity changes.
        if not printed.get("public_name") or printed.get("public_name") == previous_name:
            printed["public_name"] = printed.get("name", "")
        services = identity.get("regular_services")
        if isinstance(services, list) and services:
            printed["service_time"] = (
                str(services[0].get("time") or "")
                if len(services) == 1 and isinstance(services[0], dict) else ""
            )
    # church.yaml is the sole leadership authority. Any stale copied block in
    # brand.json must be removed before the effective object is composed.
    effective.pop("leadership", None)
    leadership = church_config.get("leadership")
    if isinstance(leadership, dict) and leadership.get("print_in_bulletin") is True:
        # Stage only renderer inputs. Church metadata such as confirmation
        # dates may be native YAML date objects and is not bulletin content.
        effective["leadership"] = {
            key: copy.deepcopy(leadership[key])
            for key in ("print_in_bulletin", "clergy_and_staff", "governing_body")
            if key in leadership
        }
        effective["leadership"]["placement"] = _resolve_leadership_placement(
            len(_leadership_entries(leadership)), leadership.get("placement")
        )
    bulletin = church_config.get("bulletin")
    if isinstance(bulletin, dict) and "footer" in bulletin:
        footer = bulletin["footer"]
        if not isinstance(footer, dict):
            raise StageFailure(
                "invalid_bulletin_footer",
                "configuration",
                "church.yaml.bulletin.footer must be a mapping",
                field="bulletin.footer",
            )
        effective["bulletin_footer"] = copy.deepcopy(footer)

    # Renderer asset paths are resolved relative to the explicit brand path.
    # Make paths absolute in this temporary object so staging never changes
    # the meaning of church-owned logo or QR assets.
    def absolutize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: absolutize(child) for key, child in value.items()}
        if isinstance(value, list):
            return [absolutize(child) for child in value]
        if isinstance(value, str):
            candidate = Path(value)
            if not candidate.is_absolute() and (root / candidate).is_file():
                return str((root / candidate).resolve())
        return value

    effective = absolutize(effective)
    path = stage_dir / "effective-brand.json"
    path.write_text(json.dumps(effective, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _booklet_signature(sequential_pdf: Path, booklet_pdf: Path) -> dict[str, int]:
    """Derive booklet economics from the verified PDF page streams."""
    from pypdf import PdfReader

    sequential_pages = len(PdfReader(str(sequential_pdf)).pages)
    booklet_pages = len(PdfReader(str(booklet_pdf)).pages)
    padded_pages = ((sequential_pages + 3) // 4) * 4
    blank_pages = padded_pages - sequential_pages
    sheet_count = padded_pages // 4
    expected_booklet_sides = padded_pages // 2
    if booklet_pages != expected_booklet_sides:
        raise StageFailure(
            "quality_gate_failed",
            "quality_gate",
            f"Booklet PDF has {booklet_pages} sides but {expected_booklet_sides} were expected from {sequential_pages} sequential pages",
        )
    return {
        "sequential_pages": sequential_pages,
        "padded_pages": padded_pages,
        "booklet_sides": booklet_pages,
        "sheet_count_11x17": sheet_count,
        "sheets_11x17": sheet_count,
        "blank_pages": blank_pages,
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "service"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_inventory_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "errors": result.get("errors", []),
        "unresolved_sections": result.get("unresolved_sections", []),
        "visual_review": result.get("visual_review", []),
        "imports_checked": result.get("imports_checked"),
    }


def _validate_source_inventory(root: Path, bulletin: dict[str, Any]) -> dict[str, Any]:
    """Block on an invalid supplied-bulletin source mapping before production
    relies on it, using the source inventory validator.

    A church with no imported bulletin is always valid: there is nothing to
    check. An invalid result blocks with a pastor-actionable reason drawn
    from the first problem, and every error, unresolved section, and
    required visual review attached as diagnostics, so the agent can
    resolve the specific entry rather than retry blindly. This never
    silently ignores an invalid inventory: a status other than valid, or a
    raised InventoryError, always becomes a StageFailure.
    """
    from ..source_inventory import InventoryError, validate_for_production

    try:
        result = validate_for_production(root, bulletin)
    except InventoryError as exc:
        raise StageFailure("source_inventory_invalid", "source_inventory", str(exc)) from exc
    if result.get("status") != "valid":
        first = next(iter(result.get("errors") or result.get("unresolved_sections") or []), {})
        message = first.get("message") or "A supplied bulletin's source mapping is not ready for production."
        locator = ".".join(
            str(part) for part in (first.get("import_id"), first.get("section_id")) if part
        )
        raise StageFailure(
            "source_inventory_invalid",
            "source_inventory",
            message,
            field=f"source_inventory.{locator}" if locator else "source_inventory",
            diagnostics=_source_inventory_diagnostics(result),
        )
    return result


def _authority_fingerprint(
    root: Path, bulletin: dict[str, Any], *, source_inventory_fingerprint: str | None = None
) -> str:
    """Fingerprint consumed private authorities and referenced file content."""
    records: list[dict[str, str]] = []

    def record(path: Path, label: str) -> None:
        resolved = path.resolve()
        if not _inside(resolved, root):
            records.append({"path": label, "sha256": "outside-church-folder"})
        elif resolved.is_file():
            records.append({"path": label, "sha256": _sha256(resolved)})
        else:
            records.append({"path": label, "sha256": "missing"})

    record(root / "church.yaml", "church.yaml")
    record(root / "brand.json", "brand.json")
    # Public worship text is also an input, including implicit defaults.
    for source in sorted((_renderer_dir() / "liturgy").glob("*.md")):
        records.append({"path": f"plugin/liturgy/{source.name}", "sha256": _sha256(source)})

    def private_path(raw: Any, label: str, *, music_fallback: bool = False) -> None:
        if not isinstance(raw, str) or not raw.strip():
            return
        candidate = Path(raw)
        options = [candidate] if candidate.is_absolute() else [root / candidate]
        if music_fallback and not candidate.is_absolute():
            options.append(root / "music" / candidate.name)
        resolved = next((item.resolve() for item in options if item.is_file()), options[0].resolve())
        record(resolved, label)

    for group_name in ("hymns", "service_music"):
        group = bulletin.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for slot, entry in group.items():
            if not isinstance(entry, dict):
                continue
            raw_images = entry.get("images") or ([entry["image"]] if entry.get("image") else [])
            if isinstance(raw_images, list):
                for index, raw in enumerate(raw_images):
                    private_path(raw, f"{group_name}.{slot}.images[{index}]", music_fallback=True)

    announcements = bulletin.get("announcements", [])
    if isinstance(announcements, list):
        for ann_index, entry in enumerate(announcements):
            if not isinstance(entry, dict):
                continue
            raw_images = entry.get("images") or ([entry["image"]] if entry.get("image") else [])
            if isinstance(raw_images, list):
                for index, raw in enumerate(raw_images):
                    private_path(raw, f"announcements[{ann_index}].images[{index}]", music_fallback=True)

    liturgy = bulletin.get("liturgy", {})
    if isinstance(liturgy, dict):
        for group_name in ("sources", "files"):
            group = liturgy.get(group_name, {})
            if isinstance(group, dict):
                for key, raw in group.items():
                    private_path(raw, f"liturgy.{group_name}.{key}")
                    if isinstance(raw, str) and not _source_is_shipped(raw, root):
                        text_path = _private_liturgy_source(raw, root, f"liturgy.{group_name}.{key}")
                        if text_path:
                            from ..liturgy_sources import require_verified_source
                            evidence = require_verified_source(root, text_path)
                            record(Path(str(text_path) + ".source.json"), f"liturgy.{group_name}.{key}.verification")
                            record(root / evidence["source"]["path"], f"liturgy.{group_name}.{key}.original")

    brand = {}
    try:
        brand = json.loads((root / "brand.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if isinstance(brand, dict):
        logo = brand.get("logo", {})
        if isinstance(logo, dict):
            for key, raw in logo.items():
                private_path(raw, f"brand.logo.{key}")
        qr = brand.get("qr", {})
        if isinstance(qr, dict):
            for key, item in qr.items():
                path = _qr_item_path(item)
                if path:
                    private_path(path, f"brand.qr.{key}")
    return _json_digest({
        "implementation_version": IMPLEMENTATION_VERSION,
        "files": sorted(records, key=lambda item: item["path"]),
        "source_inventory_fingerprint": source_inventory_fingerprint,
    })


def _copy_music_assets(
    bulletin: dict[str, Any], root: Path, stage: Path, warnings: list[dict[str, Any]]
) -> None:
    destination = stage / "hymn-images"
    destination.mkdir()
    for group_name in ("hymns", "service_music"):
        group = bulletin.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for slot, entry in group.items():
            if not isinstance(entry, dict):
                continue
            requested = entry.get("images") or ([entry["image"]] if entry.get("image") else [])
            copied: list[str] = []
            for raw in requested:
                candidate = Path(str(raw))
                candidates = [candidate] if candidate.is_absolute() else [root / candidate, root / "music" / candidate.name]
                source = next((path.resolve() for path in candidates if path.is_file()), None)
                if source is None:
                    warnings.append({
                        "code": "music_title_fallback",
                        "field": f"{group_name}.{slot}",
                        "message": f"Music image was not found: {raw}",
                    })
                    continue
                if not _inside(source, root):
                    raise StageFailure(
                        "unsafe_path",
                        "asset_resolution",
                        f"Music asset escapes the church folder: {raw}",
                        field=f"{group_name}.{slot}",
                    )
                target = destination / source.name
                shutil.copy2(source, target)
                copied.append(f"hymn-images/{target.name}")
            if not requested and not entry.get("lyrics"):
                warnings.append({
                    "code": "music_title_fallback",
                    "field": f"{group_name}.{slot}",
                    "message": "No music image was supplied; number and title will be printed.",
                })
            entry["images"] = copied
            entry.pop("image", None)


def _copy_announcement_assets(bulletin: dict[str, Any], root: Path, stage: Path) -> None:
    """Stage a supplied event poster or inline QR graphic attached to one
    announcement, with the same folder-safety as a hymn image, but two
    differences suited to announcement content specifically: the exact
    supplied church-relative (or absolute-but-confined) path is resolved,
    never a ``music/<basename>`` fallback that could silently substitute an
    unrelated same-named file; and a missing image blocks production
    outright rather than becoming a soft warning, because a poster or QR
    graphic has no safe text substitute for its content the way a hymn's
    number and title do. Staged filenames are index-qualified so two
    different source images that happen to share a basename never collide
    and silently overwrite one another in the review package.
    """
    items = bulletin.get("announcements", [])
    if not isinstance(items, list):
        return
    destination = stage / "announcement-images"
    for index, entry in enumerate(items):
        if not isinstance(entry, dict):
            continue
        requested = entry.get("images") or ([entry["image"]] if entry.get("image") else [])
        if not requested:
            continue
        if not destination.is_dir():
            destination.mkdir()
        copied: list[str] = []
        for position, raw in enumerate(requested):
            field = f"announcements[{index}].images[{position}]"
            candidate = Path(str(raw))
            source = (candidate if candidate.is_absolute() else (root / candidate)).resolve()
            if not source.is_file():
                raise StageFailure(
                    "missing_announcement_image",
                    "asset_resolution",
                    f"Announcement image was not found: {raw}",
                    field=field,
                )
            if not _inside(source, root):
                raise StageFailure(
                    "unsafe_path",
                    "asset_resolution",
                    f"Announcement image escapes the church folder: {raw}",
                    field=field,
                )
            target = destination / f"{index}-{position}-{source.name}"
            shutil.copy2(source, target)
            copied.append(f"announcement-images/{target.name}")
        entry["images"] = copied
        entry.pop("image", None)


def _copy_liturgy_sources(
    bulletin: dict[str, Any], root: Path, stage: Path
) -> Path | None:
    """Stage church-owned liturgy sources over the public source set."""
    liturgy = bulletin.get("liturgy", {})
    if not isinstance(liturgy, dict):
        return None
    sources = liturgy.get("sources", {})
    files = liturgy.get("files", {})
    if not isinstance(sources, dict):
        sources = {}
    if not isinstance(files, dict):
        files = {}
    if not sources and not files:
        return None

    destination = stage / "liturgy"
    shutil.copytree(_renderer_dir() / "liturgy", destination)

    def copy_source(identifier: str, raw_path: Any, field: str) -> str:
        source = Path(str(raw_path))
        candidates = [source] if source.is_absolute() else [root / source, root / "worship" / "liturgy" / source.name]
        resolved = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
        shipped = _renderer_dir() / "liturgy" / f"{source.stem}.md"
        if resolved is None and not source.is_absolute() and source.name == source.stem and shipped.is_file():
            return source.stem
        if resolved is None:
            raise StageFailure(
                "missing_liturgy_source",
                "asset_resolution",
                f"Liturgy source was not found: {raw_path}",
                field=field,
            )
        if not _inside(resolved, root):
            raise StageFailure(
                "unsafe_path",
                "asset_resolution",
                f"Liturgy source escapes the church folder: {raw_path}",
                field=field,
            )
        _private_liturgy_source(str(resolved), root, field)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", identifier).strip("-")
        if safe_id == "doxology":
            safe_id = "church-doxology"
        if not safe_id:
            raise StageFailure("invalid_request", "asset_resolution", "Liturgy source has no usable identifier", field=field)
        shutil.copy2(resolved, destination / f"{safe_id}.md")
        return safe_id

    def alias_keys(key: str, selected: str) -> tuple[str, ...]:
        identifier = _liturgy_identifier(key, selected, liturgy)
        return (identifier,) if identifier != selected else ()

    generated_file_keys: set[str] = set()
    for key, raw_path in sources.items():
        selected = str(liturgy.get(key, "")).strip()
        if selected:
            identifier = copy_source(selected, raw_path, f"liturgy.sources.{key}")
            files[key] = identifier
            generated_file_keys.add(key)
            for alias in alias_keys(key, selected):
                files[alias] = identifier
                generated_file_keys.add(alias)
    for section, raw_path in files.items():
        if section in generated_file_keys:
            continue
        if not str(raw_path).strip():
            continue
        identifier = copy_source(str(section), raw_path, f"liturgy.files.{section}")
        files[section] = identifier
    liturgy["files"] = files
    return destination


def _run(
    command: list[str],
    *,
    stage: str,
    env: dict[str, str] | None = None,
    reject_warnings: bool = False,
) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, env=env)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise StageFailure(f"{stage}_failed", stage, detail or f"{stage} failed")
    messages = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if reject_warnings and re.search(r"\b(?:warning|error)\b", messages, re.I):
        raise StageFailure(f"{stage}_warning", stage, messages)
    return completed.stdout


def _pdf_size(page: Any) -> tuple[float, float]:
    return round(float(page.mediabox.width), 2), round(float(page.mediabox.height), 2)


def _quality_gate(
    stage_dir: Path,
    sequential_pdf: Path,
    booklet_pdf: Path,
    occasion: str,
) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    checks: list[dict[str, Any]] = []
    sequential = PdfReader(str(sequential_pdf))
    booklet = PdfReader(str(booklet_pdf))
    if not sequential.pages:
        raise StageFailure("quality_gate_failed", "quality_gate", "Sequential PDF has no pages")
    if not booklet.pages:
        raise StageFailure("quality_gate_failed", "quality_gate", "Booklet PDF has no pages")
    if any(_pdf_size(page) != (612.0, 792.0) for page in sequential.pages):
        raise StageFailure("quality_gate_failed", "quality_gate", "Sequential PDF is not US Letter")
    if any(_pdf_size(page) != (1224.0, 792.0) for page in booklet.pages):
        raise StageFailure("quality_gate_failed", "quality_gate", "Booklet PDF is not 11x17 landscape")
    checks.extend([
        {"name": "sequential_page_size", "passed": True, "pages": len(sequential.pages)},
        {"name": "booklet_page_size", "passed": True, "pages": len(booklet.pages)},
    ])

    pdffonts = shutil.which("pdffonts")
    pdftotext = shutil.which("pdftotext")
    if not pdffonts or not pdftotext:
        raise StageFailure(
            "dependency_unavailable",
            "quality_gate",
            "Poppler font and text inspection tools are required",
        )
    fonts = _run([pdffonts, str(sequential_pdf)], stage="quality_gate")
    font_rows = [line for line in fonts.splitlines()[2:] if line.strip()]
    if not font_rows or any(re.search(r"\sno\s+(?:yes|no)\s+(?:yes|no)\s+\d+\s+\d+\s*$", row) for row in font_rows):
        raise StageFailure("quality_gate_failed", "quality_gate", "A required font is not embedded")
    checks.append({"name": "fonts_embedded", "passed": True, "fonts": len(font_rows)})

    extracted = stage_dir / ".extracted.txt"
    _run([pdftotext, "-layout", str(sequential_pdf), str(extracted)], stage="quality_gate")
    text = extracted.read_text(encoding="utf-8", errors="replace")
    extracted.unlink(missing_ok=True)
    if _placeholder_hits(text, "pdf_text"):
        raise StageFailure("quality_gate_failed", "quality_gate", "Rendered PDF contains placeholder text")
    compact_text = re.sub(r"\s+", "", text).casefold()
    for required in (occasion, "The Word of God", "The Holy Communion"):
        compact_required = re.sub(r"\s+", "", required).casefold()
        if compact_required not in compact_text:
            raise StageFailure(
                "quality_gate_failed",
                "quality_gate",
                f"Rendered PDF is missing required text: {required}",
            )
    checks.append({"name": "required_text", "passed": True})
    return checks


def _artifact(path: Path, role: str, root: Path, pages: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "role": role,
        "path": str(path.relative_to(root)),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }
    if pages is not None:
        item["pages"] = pages
    return item


def _deep_merge(base: Any, override: Any) -> Any:
    """Merge a revision patch without losing nested source-owned values."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = _deep_merge(merged[key], value) if key in merged else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


def _relative_source_path(root: Path, raw: Any, field: str) -> str:
    """Normalize one source path to a safe church-relative POSIX path."""
    if not isinstance(raw, str) or not raw.strip():
        raise StageFailure("revision_source_unrecoverable", "revision", f"Missing source path for {field}", field=field)
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not _inside(resolved, root) or not resolved.is_file():
        raise StageFailure(
            "revision_source_unrecoverable",
            "revision",
            f"Source path is not a file inside the church folder: {raw}",
            field=field,
        )
    return resolved.relative_to(root).as_posix()


def _migrate_v1_source_config(root: Path, receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Recover source paths from a v1 package without rewriting its receipt.

    v1 configs may contain staged music paths and logical liturgy identifiers.
    Only unambiguous private sources are migrated. Anything uncertain blocks
    the revision instead of silently changing the printed bulletin.
    """
    config_artifact = next((item for item in receipt.get("artifacts", []) if item.get("role") == "config"), None)
    if not isinstance(config_artifact, dict) or not str(config_artifact.get("path", "")).strip():
        raise StageFailure("revision_source_unrecoverable", "revision", "The prior receipt has no config artifact")
    config_path = _receipt_artifact_path(root, receipt_path, receipt, config_artifact["path"])
    if not _inside(config_path, root) or not config_path.is_file():
        raise StageFailure("revision_source_unrecoverable", "revision", "The prior config artifact is unavailable")
    try:
        source = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageFailure("revision_source_unrecoverable", "revision", f"Could not read the prior config: {exc}") from exc
    if not isinstance(source, dict):
        raise StageFailure("revision_source_unrecoverable", "revision", "The prior config is not an object")

    package_dir = receipt_path.parent
    for group_name in ("hymns", "service_music"):
        group = source.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for slot, entry in group.items():
            if not isinstance(entry, dict):
                continue
            raw_images = entry.get("images") or ([entry["image"]] if entry.get("image") else [])
            if not isinstance(raw_images, list):
                continue
            migrated: list[str] = []
            for index, raw in enumerate(raw_images):
                field = f"{group_name}.{slot}.images[{index}]"
                value = str(raw or "").strip()
                if not value:
                    continue
                if not value.replace("\\", "/").startswith("hymn-images/"):
                    migrated.append(_relative_source_path(root, value, field))
                    continue
                staged = (package_dir / value).resolve()
                if not staged.is_file():
                    raise StageFailure("revision_source_unrecoverable", "revision", f"Staged music source is missing: {value}", field=field)
                candidates = [path.resolve() for path in (root / "music").rglob(staged.name) if path.is_file()]
                matches = [path for path in candidates if _sha256(path) == _sha256(staged)]
                if len(matches) != 1:
                    detail = "no matching private source" if not matches else "multiple matching private sources"
                    raise StageFailure("revision_source_unrecoverable", "revision", f"Could not recover {field}: {detail}", field=field)
                migrated.append(matches[0].relative_to(root).as_posix())
            if "images" in entry:
                entry["images"] = migrated
            elif migrated:
                entry["images"] = migrated
            entry.pop("image", None)

    liturgy = source.get("liturgy", {})
    if isinstance(liturgy, dict):
        sources = liturgy.get("sources", {})
        if not isinstance(sources, dict):
            sources = {}
        for key, raw in list(sources.items()):
            sources[key] = _relative_source_path(root, raw, f"liturgy.sources.{key}")
        liturgy["sources"] = sources
        files = liturgy.get("files", {})
        if isinstance(files, dict):
            public_ids = {
                path.stem for path in (_renderer_dir() / "liturgy").glob("*.md") if path.is_file()
            }
            migrated_files: dict[str, str] = {}
            for key, raw in files.items():
                value = str(raw or "").strip()
                if key in sources:
                    migrated_files[key] = sources[key]
                elif value in public_ids:
                    migrated_files[key] = value
                else:
                    try:
                        migrated_files[key] = _relative_source_path(root, value, f"liturgy.files.{key}")
                    except StageFailure as exc:
                        raise StageFailure(
                            "revision_source_unrecoverable",
                            "revision",
                            f"Private liturgy source for {key!r} cannot be recovered from the v1 package",
                            field=f"liturgy.files.{key}",
                        ) from exc
            liturgy["files"] = migrated_files
    if "template" not in source:
        for artifact in receipt.get("artifacts", []):
            if artifact.get("role") == "sequential_pdf":
                match = re.search(r"-([a-z]+)\.pdf$", str(artifact.get("path", "")))
                if match:
                    source["template"] = match.group(1)
                break
    return source


def _receipt_artifact_path(root: Path, receipt_path: Path, receipt: dict[str, Any], raw_path: Any) -> Path:
    """Resolve an artifact from either its active or archived receipt path."""
    path = Path(str(raw_path))
    direct = (root / path).resolve()
    package_dir = receipt_path.parent.resolve()
    if ".revisions" not in package_dir.parts:
        return direct
    week_folder = Path(str(receipt.get("week_folder", "")))
    try:
        relative = path.relative_to(week_folder)
    except ValueError:
        relative = Path(path.name)
    archived = (package_dir / relative).resolve()
    return archived if archived.is_file() else direct


def _load_prior_revision(root: Path, prior_run: str | Path) -> dict[str, Any]:
    """Load and validate the exact prior review receipt named by the caller."""
    receipt_path = Path(prior_run).expanduser()
    if not receipt_path.is_absolute():
        receipt_path = (root / receipt_path).resolve()
    else:
        receipt_path = receipt_path.resolve()
    if not _inside(receipt_path, root):
        raise StageFailure("unsafe_path", "revision", "Prior receipt must remain inside the church folder")
    if not receipt_path.is_file():
        # A successful revision moves the predecessor receipt under
        # .revisions. Retain idempotence for a repeated command that still
        # names the predecessor's original active path by following the
        # explicit predecessor link in the active receipt.
        requested = str(receipt_path.relative_to(root))
        candidates: list[Path] = []
        for candidate in (root / "bulletins").glob("**/bulletin-production-receipt.json"):
            try:
                candidate_receipt = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            link = candidate_receipt.get("revision_of") if isinstance(candidate_receipt, dict) else None
            if isinstance(link, dict) and link.get("original_receipt_path") == requested:
                archive_path = root / str(link.get("receipt_path", ""))
                if archive_path.is_file():
                    candidates.append(archive_path)
        if len(candidates) == 1:
            receipt_path = candidates[0].resolve()
        else:
            raise StageFailure("prior_run_missing", "revision", f"Prior production receipt was not found: {receipt_path}")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageFailure("prior_receipt_invalid", "revision", f"Could not read the prior production receipt: {exc}") from exc
    if not isinstance(receipt, dict) or not str(receipt.get("run_id", "")).strip():
        raise StageFailure("prior_receipt_invalid", "revision", "Prior production receipt has no run_id")
    if receipt.get("status") != "ready_for_review":
        raise StageFailure("prior_run_not_reviewable", "revision", "Only a ready-for-review package can be revised")
    package_dir = receipt_path.parent.resolve()
    approval_path = package_dir / "bulletin-approval-receipt.json"
    if approval_path.is_file():
        raise StageFailure("prior_run_approved", "revision", "An approved bulletin cannot be revised")
    for artifact in receipt.get("artifacts", []):
        if not isinstance(artifact, dict) or not str(artifact.get("path", "")).strip():
            raise StageFailure("prior_receipt_invalid", "revision", "Prior receipt has an invalid artifact")
        path = _receipt_artifact_path(root, receipt_path, receipt, artifact["path"])
        if not _inside(path, root) or not path.is_file():
            raise StageFailure("prior_receipt_invalid", "revision", f"Prior artifact is unavailable: {artifact['path']}")
        expected_sha = str(artifact.get("sha256", "")).strip()
        if expected_sha and _sha256(path) != expected_sha:
            raise StageFailure("prior_artifact_changed", "revision", f"Prior artifact changed after review: {artifact['path']}")
    history_path = root / "bulletins" / "bulletin-log.json"
    if history_path.is_file():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageFailure("approved_history_invalid", "revision", f"Could not read approved bulletin history: {exc}") from exc
        for entry in history.values() if isinstance(history, dict) else []:
            if not isinstance(entry, dict):
                continue
            run_ids = {
                str(value.get("production_run_id"))
                for value in (entry.get("templates", {}) or {}).values()
                if isinstance(value, dict) and value.get("production_run_id")
            }
            if receipt["run_id"] in run_ids:
                raise StageFailure("prior_run_approved", "revision", "The prior run appears in approved bulletin history")
    if receipt.get("receipt_version", 1) >= 2 and isinstance(receipt.get("source_config"), dict):
        source_path = _receipt_artifact_path(root, receipt_path, receipt, receipt["source_config"].get("path", ""))
        if _inside(source_path, root) and source_path.is_file():
            try:
                source = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StageFailure("revision_source_unrecoverable", "revision", f"Could not read the prior source config: {exc}") from exc
            if isinstance(source, dict):
                source_sha = str(receipt["source_config"].get("sha256", "")).strip()
                if source_sha and _sha256(source_path) != source_sha:
                    raise StageFailure("prior_artifact_changed", "revision", "The prior source config changed after review")
                return {"path": receipt_path, "receipt": receipt, "source": source, "package_dir": package_dir}
    return {"path": receipt_path, "receipt": receipt, "source": _migrate_v1_source_config(root, receipt_path, receipt), "package_dir": package_dir}


def _consume_saved_worship_resolution(root: Path, bulletin: dict[str, Any]) -> None:
    """Merge the church's saved worship resolution into the weekly liturgy.

    A church that has never chosen a worship tradition pack yet (the
    onboarding-in-progress case: the profile file exists at its default,
    unconfigured) has no saved worship resolution to consult, so its weekly
    liturgy passes through unchanged, and ``_validate_bulletin`` still
    requires that weekly liturgy to be a complete, explicit set of worship
    choices on its own. That bypass is narrow: a profile the church folder
    is supposed to have, but that is missing or unreadable (moved, deleted,
    corrupted), is a broken connection, not an unconfigured church, and
    blocks production with reconnect guidance rather than silently reverting
    to the legacy no-profile path and losing every saved preference.

    Once a tradition pack is chosen, production consults the same resolver
    the agent uses instead of trusting a hand-merged weekly input, so a
    saved choice (doxology, confession, closing-hymn position, a configured
    service variant, or any other worship-profile default) cannot be
    silently dropped. An explicit weekly override always wins: the resolver
    applies it after the saved defaults. A choice the profile still needs
    blocks production with the resolver's own reason instead of guessing.
    """
    from ..worship_resolution import WorshipResolutionError, resolve_worship_profile

    liturgy = bulletin.get("liturgy")
    liturgy = liturgy if isinstance(liturgy, dict) else {}
    service = bulletin.get("service")
    service = service if isinstance(service, dict) else {}
    weekly: dict[str, Any] = {"liturgy": liturgy, "service": service}
    if str(liturgy.get("service_plan", "")).strip():
        weekly["service_plan"] = liturgy["service_plan"]
    try:
        resolution = resolve_worship_profile(root, weekly)
    except WorshipResolutionError as exc:
        if exc.code == "tradition_pack_unresolved":
            return
        if exc.code == "profile_missing":
            raise StageFailure(
                "worship_profile_missing",
                "worship_resolution",
                f"{exc.message} Reconnect or restore the saved worship profile through onboarding before producing; "
                "do not treat a missing saved profile as an unconfigured church.",
                field=exc.field or "worship_profile",
            ) from exc
        raise StageFailure(exc.code, "worship_resolution", exc.message, field=exc.field) from exc
    if resolution["status"] == "needs_input":
        reason = resolution["unresolved"][0]
        raise StageFailure(
            "worship_resolution_needs_input",
            "worship_resolution",
            reason["reason"],
            field=reason["field"],
        )
    bulletin["liturgy"] = resolution["liturgy"]


def _validate_service_time_choice(church_config: dict[str, Any], bulletin: dict[str, Any]) -> None:
    """Require an explicit weekly time when the church has several services.

    A single saved service safely fills the printed time (see
    ``_stage_effective_brand``). Several saved services must never be
    guessed among; the weekly input must say which one this bulletin is for.
    """
    identity = church_config.get("church")
    services = identity.get("regular_services") if isinstance(identity, dict) else None
    if not isinstance(services, list) or len(services) <= 1:
        return
    service = bulletin.get("service")
    weekly_time = service.get("time") if isinstance(service, dict) else None
    if not str(weekly_time or "").strip():
        raise StageFailure(
            "service_time_choice_required",
            "validation",
            f"This church has {len(services)} saved services; confirm which one's time applies to this week's bulletin",
            field="service.time",
        )


def _history_has_run(root: Path, service_date: str, run_id: str) -> bool:
    history_path = root / "bulletins" / "bulletin-log.json"
    if not history_path.is_file():
        return False
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    entry = history.get(service_date) if isinstance(history, dict) else None
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(value, dict) and value.get("production_run_id") == run_id
        for value in (entry.get("templates", {}) or {}).values()
    )


def _is_legacy_unapproved_history(entry: Any) -> bool:
    """Recognize the old renderer log shape without treating it as approval."""
    if not isinstance(entry, dict):
        return False
    if entry.get("approval_id") or entry.get("evidence_label") == "approved_bulletin":
        return False
    templates = entry.get("templates")
    if not isinstance(templates, dict) or not templates:
        return False
    return all(
        isinstance(value, dict) and not value.get("production_run_id")
        for value in templates.values()
    )


def produce(church_folder: str | Path, bulletin: dict[str, Any], *, _revision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Produce verified review artifacts without updating approved history."""

    stage_dir: Path | None = None
    try:
        root = _require_church_folder(Path(church_folder))
        church_config, brand = _load_church_configuration(root)
        source_resolved = copy.deepcopy(bulletin)
        _validate_service_time_choice(church_config, source_resolved)
        _consume_saved_worship_resolution(root, source_resolved)
        _normalize_liturgy(source_resolved)
        _resolve_standing_preferences(source_resolved, church_config)
        _resolve_parish_information(source_resolved, church_config)
        _validate_leadership(church_config)
        warnings: list[dict[str, Any]] = []
        _validate_brand_asset_paths(brand, root)
        _validate_qr(brand, root, warnings, church_config)
        _validate_lyric_layout(source_resolved)
        _validate_service_music(source_resolved)
        _validate_service_variant(source_resolved, root)
        _validate_back_page_merge(source_resolved)
        if (source_resolved.get("options") or {}).get("merge_back_page") is True:
            warnings.append({
                "code": "back_page_merge_visual_review_required",
                "field": "options.merge_back_page",
                "message": "Back-page merge was requested and requires human visual review if the selected template applies it.",
            })
        _validate_parish_information(source_resolved)
        _validate_bulletin(source_resolved)
        _validate_liturgy_sources(source_resolved, root)
        inventory_result = _validate_source_inventory(root, source_resolved)
        template = source_resolved.get("template") or source_resolved.get("_template") or "classic"
        if template in SUPPORTED_TEMPLATES:
            from ..renderer.render_bulletin import cover_logo
            try:
                logo_path = cover_logo(brand, root, template)
                if logo_path:
                    if logo_path.suffix.lower() == ".svg":
                        from xml.etree import ElementTree
                        if ElementTree.parse(logo_path).getroot().tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
                            raise ValueError("The configured logo file is not an SVG image.")
                    else:
                        from PIL import Image
                        with Image.open(logo_path) as logo_image:
                            logo_image.verify()
            except (OSError, ValueError, SyntaxError) as exc:
                raise StageFailure("church_logo_unavailable", "asset_resolution",
                                   f"The {template.title()} cover needs the configured church logo. {exc}",
                                   field="brand.logo") from exc
        service = source_resolved["service"]
        run_id = str(uuid.uuid4())
        digest = _json_digest({
            "implementation_version": IMPLEMENTATION_VERSION,
            "authority_fingerprint": _authority_fingerprint(
                root, source_resolved, source_inventory_fingerprint=inventory_result["fingerprint"]
            ),
            "template": template,
            "bulletin": source_resolved,
        })
        week_name = f"{service['date']}-{_slug(service['occasion'])}"
        final_dir = root / "bulletins" / service["date"][:4] / service["date"][5:7] / week_name
        revision_digest = _json_digest({
            "prior_run_id": (_revision or {}).get("receipt", {}).get("run_id"),
            "resolved_bulletin_digest": digest,
        }) if _revision else None

        if final_dir.exists():
            receipt_path = final_dir / "bulletin-production-receipt.json"
            if receipt_path.is_file():
                prior = json.loads(receipt_path.read_text(encoding="utf-8"))
                if _revision and prior.get("revision_request_digest") == revision_digest:
                    return {
                        "status": prior.get("status", "ready_for_review"),
                        "receipt_path": str(receipt_path),
                        "week_folder": str(final_dir),
                        "warnings": prior.get("warnings", []),
                        "booklet_signature": prior.get("booklet_signature", {}),
                        "idempotent": True,
                    }
                if prior.get("resolved_bulletin_digest") == digest:
                    return {
                        "status": prior.get("status", "ready_for_review"),
                        "receipt_path": str(receipt_path),
                        "week_folder": str(final_dir),
                        "warnings": prior.get("warnings", []),
                        "booklet_signature": prior.get("booklet_signature", {}),
                        "idempotent": True,
                    }
                if _revision and prior.get("run_id") != (_revision.get("receipt") or {}).get("run_id"):
                    raise StageFailure(
                        "revision_target_conflict",
                        "conflict_check",
                        f"Active bulletin work does not match the explicit prior run: {final_dir}",
                    )
            elif _revision:
                raise StageFailure("revision_target_conflict", "conflict_check", f"Active bulletin folder has no production receipt: {final_dir}")
            if not _revision:
                raise StageFailure(
                    "existing_run_conflict",
                    "conflict_check",
                    f"Existing bulletin work requires an explicit revision: {final_dir}",
                )

        bulletins_root = root / "bulletins"
        bulletins_root.mkdir(exist_ok=True)
        staging_root = bulletins_root / ".staging"
        staging_root.mkdir(exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=staging_root))
        staged_brand = _stage_effective_brand(brand, church_config, root, stage_dir)
        resolved = copy.deepcopy(source_resolved)
        resolved.pop("template", None)
        resolved.pop("_template", None)
        _copy_music_assets(resolved, root, stage_dir, warnings)
        _copy_announcement_assets(resolved, root, stage_dir)
        staged_liturgy = _copy_liturgy_sources(resolved, root, stage_dir)
        config_path = stage_dir / "bulletin-config.json"
        config_path.write_text(json.dumps(source_resolved, indent=2, ensure_ascii=False), encoding="utf-8")
        render_config_path = stage_dir / ".render-bulletin-config.json"
        render_config_path.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")

        renderer = _renderer_dir()
        render_script = renderer / "render_bulletin.py"
        impose_script = renderer / "impose_booklet.py"
        if not render_script.is_file() or not impose_script.is_file():
            raise StageFailure("dependency_unavailable", "render", "Bulletin renderer is unavailable")
        cache = stage_dir / ".cache"
        cache.mkdir()
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(cache)
        render_command = [
            sys.executable,
            str(render_script),
            "--config",
            str(render_config_path),
            "--template",
            template,
            "--brand",
            str(staged_brand),
            "--out",
            str(stage_dir),
            "--no-log",
        ]
        if staged_liturgy is not None:
            render_command.extend(["--liturgy-dir", str(staged_liturgy)])
        _run(render_command, stage="render", env=env, reject_warnings=True)
        stem = f"bulletin-{service['date']}-{template}"
        html_path = stage_dir / f"{stem}.html"
        sequential_pdf = stage_dir / f"{stem}.pdf"
        booklet_pdf = stage_dir / f"{stem}-booklet-11x17.pdf"
        _run([sys.executable, str(impose_script), str(sequential_pdf), str(booklet_pdf)], stage="imposition")

        (stage_dir / "bulletin-log.json").unlink(missing_ok=True)
        shutil.rmtree(cache, ignore_errors=True)
        for render_cache in stage_dir.glob("**/.render-cache"):
            shutil.rmtree(render_cache, ignore_errors=True)
        checks = _quality_gate(stage_dir, sequential_pdf, booklet_pdf, service["occasion"])
        signature = _booklet_signature(sequential_pdf, booklet_pdf)
        checks.append({"name": "booklet_signature", "passed": True, **signature})
        staged_brand.unlink(missing_ok=True)
        if staged_liturgy is not None:
            shutil.rmtree(staged_liturgy, ignore_errors=True)
        render_config_path.unlink(missing_ok=True)

        from pypdf import PdfReader

        final_paths = {
            "config": final_dir / config_path.name,
            "html": final_dir / html_path.name,
            "sequential_pdf": final_dir / sequential_pdf.name,
            "booklet_pdf": final_dir / booklet_pdf.name,
        }
        artifacts = [
            _artifact(config_path, "config", stage_dir),
            _artifact(html_path, "html", stage_dir),
            _artifact(sequential_pdf, "sequential_pdf", stage_dir, len(PdfReader(str(sequential_pdf)).pages)),
            _artifact(booklet_pdf, "booklet_pdf", stage_dir, len(PdfReader(str(booklet_pdf)).pages)),
        ]
        for item in artifacts:
            item["path"] = str(final_paths[item["role"]].relative_to(root))

        receipt = {
            "receipt_version": 2,
            "run_id": run_id,
            "status": "ready_for_review",
            "created_at": _now(),
            "implementation_version": IMPLEMENTATION_VERSION,
            "resolved_bulletin_digest": digest,
            "church_folder": ".",
            "week_folder": str(final_dir.relative_to(root)),
            "revision_of": (
                {
                    "run_id": (_revision.get("receipt") or {}).get("run_id"),
                    "receipt_path": str(_revision["archive_dir"].relative_to(root) / "bulletin-production-receipt.json"),
                    "original_receipt_path": str(_revision["receipt_path"].relative_to(root)),
                    "receipt_sha256": _revision.get("receipt_sha256"),
                }
                if _revision else None
            ),
            "revision_request_digest": revision_digest,
            "source_bulletin_digest": _json_digest(source_resolved),
            "source_config": {
                "path": str(final_paths["config"].relative_to(root)),
                "sha256": next(item["sha256"] for item in artifacts if item["role"] == "config"),
            },
            "artifacts": artifacts,
            "quality_checks": checks,
            "booklet_signature": signature,
            "service_variant": (source_resolved.get("liturgy") or {}).get("service_variant"),
            "service_variant_provenance": (source_resolved.get("liturgy") or {}).get("service_variant_provenance"),
            "resolved_provenance": {
                "service_variant": (source_resolved.get("liturgy") or {}).get("service_variant"),
                "service_variant_provenance": (source_resolved.get("liturgy") or {}).get("service_variant_provenance"),
                "worship_profile_ref": (source_resolved.get("liturgy") or {}).get("worship_profile_ref"),
            },
            "warnings": warnings,
            "blocking_failures": [],
            "dependency_versions": _dependency_checks(),
            "cleanup_status": "clean",
            "source_inventory": {
                "fingerprint": inventory_result["fingerprint"],
                "imports_checked": inventory_result["imports_checked"],
                "visual_review": inventory_result["visual_review"],
            },
        }
        receipt_path = stage_dir / "bulletin-production-receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")

        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if _revision:
            archive_dir = _revision["archive_dir"]
            if archive_dir.exists():
                raise StageFailure("revision_archive_conflict", "archive", f"Archive destination already exists: {archive_dir}")
            archive_dir.parent.mkdir(parents=True, exist_ok=True)
            archived = False
            try:
                if final_dir.exists():
                    shutil.move(str(final_dir), str(archive_dir))
                    archived = True
                os.replace(stage_dir, final_dir)
            except Exception as exc:
                if archived and not final_dir.exists() and archive_dir.exists():
                    try:
                        shutil.move(str(archive_dir), str(final_dir))
                    except Exception as restore_exc:
                        raise StageFailure("archive_restore_failed", "archive", f"Could not restore the prior bulletin after replacement failed: {restore_exc}") from exc
                raise StageFailure("revision_storage_failed", "archive", str(exc)) from exc
        else:
            os.replace(stage_dir, final_dir)
        stage_dir = None
        staging_root.rmdir() if not any(staging_root.iterdir()) else None
        return {
            "status": "ready_for_review",
            "receipt_path": str(final_dir / receipt_path.name),
            "week_folder": str(final_dir),
            "artifacts": receipt["artifacts"],
            "warnings": warnings,
            "booklet_signature": signature,
            "idempotent": False,
        }
    except StageFailure as exc:
        return _failure(exc, status="blocked")
    except Exception as exc:  # defensive conversion at the public seam
        return _failure(exc, status="failed")
    finally:
        if stage_dir is not None:
            shutil.rmtree(stage_dir, ignore_errors=True)


def revise(church_folder: str | Path, prior_run: str | Path, bulletin: dict[str, Any]) -> dict[str, Any]:
    """Produce a replacement for one explicit, unapproved review package."""

    try:
        root = _require_church_folder(Path(church_folder))
        prior = _load_prior_revision(root, prior_run)
        source = prior["source"]
        if not isinstance(bulletin, dict):
            raise StageFailure("invalid_request", "revision", "Revision input must be an object")
        merged = _deep_merge(source, bulletin)
        service = merged.get("service") if isinstance(merged, dict) else None
        prior_service = source.get("service") if isinstance(source, dict) else None
        if not isinstance(service, dict) or not isinstance(prior_service, dict):
            raise StageFailure("revision_source_unrecoverable", "revision", "The prior package has no usable service data")
        if str(service.get("date", "")) != str(prior_service.get("date", "")):
            raise StageFailure("revision_date_mismatch", "revision", "A revision must keep the prior service date")
        occasion = str(service.get("occasion", "")).strip()
        if not occasion:
            raise StageFailure("invalid_request", "revision", "A revision requires a service occasion", field="service.occasion")
        expected_dir = root / "bulletins" / str(service["date"])[:4] / str(service["date"])[5:7] / f"{service['date']}-{_slug(occasion)}"
        prior_week = prior["receipt"].get("week_folder")
        if prior_week and (root / str(prior_week)).resolve() != expected_dir.resolve():
            raise StageFailure("revision_target_conflict", "revision", "A revision must keep the prior service folder and occasion")
        prior_package = prior["package_dir"].resolve()
        if prior_package != expected_dir.resolve():
            if ".revisions" not in prior_package.parts:
                raise StageFailure("revision_target_conflict", "revision", "The explicit prior receipt is not the active review package")
            active_receipt_path = expected_dir / "bulletin-production-receipt.json"
            if not active_receipt_path.is_file():
                raise StageFailure("revision_target_conflict", "revision", "The archived prior receipt has no active replacement package")
            try:
                active_receipt = json.loads(active_receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StageFailure("revision_target_conflict", "revision", "The active replacement receipt is unreadable") from exc
            link = active_receipt.get("revision_of") if isinstance(active_receipt, dict) else None
            if not isinstance(link, dict) or link.get("run_id") != prior["receipt"]["run_id"]:
                raise StageFailure("revision_target_conflict", "revision", "The archived prior receipt is not the active package predecessor")
        archive_dir = expected_dir.parent / ".revisions" / expected_dir.name / str(prior["receipt"]["run_id"])
        revision = {
            "receipt": prior["receipt"],
            "receipt_path": prior["path"],
            "receipt_sha256": _sha256(prior["path"]),
            "archive_dir": archive_dir,
        }
        return produce(root, merged, _revision=revision)
    except StageFailure as exc:
        return _failure(exc, status="blocked")
    except Exception as exc:
        return _failure(exc, status="failed")


def _history_entry(config: dict[str, Any], receipt: dict[str, Any], approval_id: str) -> dict[str, Any]:
    service = config["service"]
    readings = config.get("readings", {})

    def music_entries(group_name: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for slot, item in config.get(group_name, {}).items():
            if not isinstance(item, dict):
                continue
            result.append({
                "slot": slot,
                "number": item.get("number"),
                "title": item.get("title"),
                "tune": item.get("tune"),
            })
        return result

    template = Path(next(
        artifact["path"] for artifact in receipt["artifacts"] if artifact["role"] == "sequential_pdf"
    )).stem.rsplit("-", 1)[-1]
    return {
        "date": service["date"],
        "occasion": service.get("occasion"),
        "proper": service.get("proper"),
        "lectionary_track": service.get("lectionary_track"),
        "liturgical_color": service.get("liturgical_color"),
        "service_variant": (config.get("liturgy") or {}).get("service_variant"),
        "service_variant_provenance": (config.get("liturgy") or {}).get("service_variant_provenance"),
        "provenance": {
            "service_variant": (config.get("liturgy") or {}).get("service_variant"),
            "service_variant_provenance": (config.get("liturgy") or {}).get("service_variant_provenance"),
            "worship_profile_ref": (config.get("liturgy") or {}).get("worship_profile_ref"),
        },
        "preacher": service.get("preacher"),
        "celebrant": service.get("celebrant"),
        "readings": {
            "first": (readings.get("first") or {}).get("citation"),
            "psalm": (readings.get("psalm") or {}).get("number"),
            "second": (readings.get("second") or {}).get("citation"),
            "gospel": (readings.get("gospel") or {}).get("citation"),
        },
        "hymns": music_entries("hymns"),
        "service_music": music_entries("service_music"),
        "announcements": [item.get("title") for item in config.get("announcements", [])],
        "options": config.get("options", {}),
        "templates": {template: {"production_run_id": receipt["run_id"]}},
        "approval_id": approval_id,
        "approved_at": _now(),
        "evidence_label": "approved_bulletin",
    }


def finalize(production_receipt: str | Path, approval: dict[str, Any]) -> dict[str, Any]:
    """Finalize an unchanged review package and update approved history."""

    try:
        receipt_path = Path(production_receipt).expanduser().resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        root = _find_church_folder(receipt_path)
        if not _inside(receipt_path, root):
            raise StageFailure("unsafe_path", "finalization", "Receipt escapes the church folder")
        if ".revisions" in receipt_path.parent.parts:
            raise StageFailure("archived_review_package", "finalization", "An archived review package cannot be finalized")
        if receipt.get("status") != "ready_for_review":
            raise StageFailure("invalid_request", "finalization", "Receipt is not ready for review")
        if approval.get("production_run_id") != receipt.get("run_id"):
            raise StageFailure("approval_mismatch", "finalization", "Approval identifies a different run")
        if not str(approval.get("approved_by", "")).strip():
            raise StageFailure("invalid_request", "finalization", "Approval requires approved_by")

        approval_path = receipt_path.parent / "bulletin-approval-receipt.json"
        if approval_path.is_file():
            prior = json.loads(approval_path.read_text(encoding="utf-8"))
            if prior.get("production_run_id") == receipt["run_id"]:
                return {
                    "status": "approved",
                    "approval_receipt_path": str(approval_path),
                    "idempotent": True,
                }

        actual_hashes: dict[str, str] = {}
        for artifact in receipt.get("artifacts", []):
            path = root / artifact["path"]
            if not path.is_file() or _sha256(path) != artifact["sha256"]:
                raise StageFailure(
                    "artifact_changed_after_review",
                    "finalization",
                    f"Artifact changed after production: {artifact['path']}",
                )
            actual_hashes[artifact["role"]] = artifact["sha256"]
        reviewed = approval.get("reviewed_artifact_hashes")
        if not isinstance(reviewed, dict) or not reviewed:
            raise StageFailure(
                "invalid_request",
                "finalization",
                "Approval requires reviewed_artifact_hashes",
            )
        if reviewed != actual_hashes:
            raise StageFailure("approval_mismatch", "finalization", "Reviewed hashes do not match artifacts")

        config_artifact = next(item for item in receipt["artifacts"] if item["role"] == "config")
        config = json.loads((root / config_artifact["path"]).read_text(encoding="utf-8"))

        # Re-run the same read-only source-inventory gate used at production.
        # An artifact/config file hash matching the receipt only proves the
        # resolved bulletin is unchanged; it says nothing about a mapped
        # source file, or its review attestation, changing since. That would
        # never be caught otherwise, and source review would silently vanish
        # from the approved handoff.
        inventory_result = _validate_source_inventory(root, config)
        stored_inventory = receipt.get("source_inventory") or {}
        if (
            stored_inventory.get("fingerprint") is not None
            and inventory_result["fingerprint"] != stored_inventory["fingerprint"]
        ):
            raise StageFailure(
                "source_inventory_changed",
                "finalization",
                "The source mapping or its reviewed content changed since this bulletin was produced; "
                "produce a fresh review package before approving.",
                field="source_inventory",
            )

        approval_id = str(uuid.uuid4())
        approval_receipt = {
            "receipt_version": 1,
            "approval_id": approval_id,
            "production_run_id": receipt["run_id"],
            "approved_at": approval.get("approved_at") or _now(),
            "approved_by": approval["approved_by"],
            "note": approval.get("note", ""),
            "reviewed_artifact_hashes": actual_hashes,
            "production_receipt_sha256": _sha256(receipt_path),
            "history_update": "verified",
            "source_inventory": {
                "fingerprint": inventory_result["fingerprint"],
                "imports_checked": inventory_result["imports_checked"],
                "visual_review": inventory_result["visual_review"],
            },
        }

        bulletins = root / "bulletins"
        history_path = bulletins / "bulletin-log.json"
        history: dict[str, Any] = {}
        if history_path.is_file():
            history = json.loads(history_path.read_text(encoding="utf-8"))
        entry = _history_entry(config, receipt, approval_id)
        existing = history.get(entry["date"]) if isinstance(history, dict) else None
        legacy_history_snapshot: dict[str, Any] | None = None
        if isinstance(existing, dict):
            existing_templates = existing.get("templates", {}) or {}
            matching = any(
                isinstance(value, dict) and value.get("production_run_id") == receipt.get("run_id")
                for value in existing_templates.values()
            ) if isinstance(existing_templates, dict) else False
            if not matching:
                if _is_legacy_unapproved_history(existing):
                    legacy_history_snapshot = copy.deepcopy(existing)
                else:
                    raise StageFailure(
                        "approved_history_conflict",
                        "finalization",
                        f"Approved or ambiguous bulletin history already contains service date {entry['date']}; it will not be overwritten",
                    )
        if legacy_history_snapshot is not None:
            approval_receipt["history_update"] = "migrated_legacy_render_history"
            approval_receipt["legacy_unapproved_history_replaced"] = {
                "date": entry["date"],
                "entry": legacy_history_snapshot,
            }
        history[entry["date"]] = entry
        ordered = {key: history[key] for key in sorted(history)}

        approval_tmp = approval_path.with_suffix(".json.tmp")
        history_tmp = history_path.with_suffix(".json.tmp")
        approval_tmp.write_text(json.dumps(approval_receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        history_tmp.write_text(json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(history_tmp, history_path)
        os.replace(approval_tmp, approval_path)
        return {
            "status": "approved",
            "approval_receipt_path": str(approval_path),
            "history_path": str(history_path),
            "idempotent": False,
        }
    except StageFailure as exc:
        return _failure(exc, status="blocked")
    except Exception as exc:
        return _failure(exc, status="failed")
