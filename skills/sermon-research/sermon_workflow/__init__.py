"""Portable, receipt-governed sermon research workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


IMPLEMENTATION_VERSION = "0.7.0"
RECEIPT_SCHEMA_VERSION = 3
STAGE_FILES = {
    "readings": "readings.md",
    "research": "research-brief.md",
}
STAGE_ORDER = tuple(STAGE_FILES)
DEPENDENCIES = {
    "readings": (),
    "research": ("readings",),
}
# Each stage's receipt depends only on the church.yaml fields that actually
# govern it, not the whole file. Roster, footer, template, branding and other
# display-only preferences must not stale a verified stage; a change to one
# of these semantic fields must. church.tradition and lectionary.authorities
# are included because they affect the calendar/source contract readings are
# verified against.
CONFIG_DEPENDENCY_FIELDS = {
    "readings": (
        ("church", "tradition"),
        ("lectionary", "system"),
        ("lectionary", "track"),
        ("lectionary", "translation"),
        ("lectionary", "optional_verses"),
        ("lectionary", "authorities"),
        ("sermon", "selection_mode"),
        ("sermon", "primary_text"),
    ),
    "research": (
        ("sermon", "research_preferences"),
    ),
}
# The receipt key each stage's fingerprint is recorded under. Renamed from
# the legacy "church_config" whole-file dependency so an older receipt (which
# recorded a full-file hash under that key) is never mistaken for a match
# against the new narrower fingerprint; it safely falls back to "stale" and
# must be re-verified once.
CONFIG_DEPENDENCY_KEY = {
    "readings": "sermon_config",
    "research": "research_preferences",
}
REQUIRED_CHECKS = {
    "readings": {"content", "sources", "dependencies"},
    "research": {"content", "sources", "dependencies"},
}
READING_ROLES = ("first", "psalm", "second", "gospel", "selected")
SELECTION_MODES = ("lectionary", "pastor_selected")
SELECTION_MODE_DISPLAY = {
    "lectionary": "Lectionary",
    "pastor_selected": "Pastor-selected passage",
}
OPTIONAL_POLICY_DISPLAY = {
    "appointed": "Use appointed options",
    "include_all": "Include all appointed options",
    "omit_optional": "Omit appointed options",
    "ask_each_week": "Ask each week",
}
RESEARCH_HEADINGS = (
    "Research orientation",
    "Language and Historical Context",
    "Interpretive Conversations",
    "Contemporary Convergence",
    "Pastoral Applications",
    "Possible Preaching Centers",
    "References",
    "Questions for reflection",
)
LOCALIZATION = re.compile(
    r"\byour own (?:city|town|neighborhood|parish|congregation|community)\b|"
    r"\b(?:this|your|our) (?:parish|congregation)\b|"
    r"\byour (?:neighborhood|people|pews)\b|"
    r"\bthe parish is\b|"
    r"\bin your context\b",
    re.I,
)


class WorkflowFailure(Exception):
    """Expected workflow failure with a stable code."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(root.resolve()))) == str(root.resolve())
    except ValueError:
        return False


def _church_root(church_folder: str | Path) -> Path:
    root = Path(church_folder).expanduser().resolve()
    if not root.is_dir() or not (root / "church.yaml").is_file():
        raise WorkflowFailure(
            "uninitialized_church_folder",
            f"Church folder is not initialized: {root}",
        )
    return root


def _date_text(service_date: str | date) -> str:
    value = service_date.isoformat() if isinstance(service_date, date) else str(service_date)
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise WorkflowFailure("invalid_date", str(exc), field="date") from exc
    return value


def _mode_text(mode: str) -> str:
    if mode not in {"manual", "scheduled"}:
        raise WorkflowFailure("invalid_mode", f"Unknown workflow mode: {mode}", field="mode")
    return mode


def _failure(exc: WorkflowFailure | Exception) -> dict[str, Any]:
    if isinstance(exc, WorkflowFailure):
        item: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.field:
            item["field"] = exc.field
        return {"status": "blocked", "errors": [item], "warnings": []}
    return {
        "status": "failed",
        "errors": [{"code": "unexpected_failure", "message": str(exc)}],
        "warnings": [],
    }


def _nonempty(path: Path) -> bool:
    return path.is_file() and bool(path.read_text(encoding="utf-8").strip())


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sermon_primary_text(root: Path) -> str | None:
    text = (root / "church.yaml").read_text(encoding="utf-8")
    section = re.search(r"^sermon:\s*$([\s\S]*?)(?=^\S|\Z)", text, re.M)
    if not section:
        return None
    match = re.search(r"^\s{2}primary_text:\s*[\"']?([^\n\"'#]+)", section.group(1), re.M)
    if not match:
        return None
    value = match.group(1).strip().lower()
    return value if value in READING_ROLES else None


def _sermon_selection_mode(root: Path) -> str | None:
    configured = _yaml_scalar(root, "sermon", "selection_mode")
    if configured:
        value = configured.strip().lower()
        return value if value in SELECTION_MODES else None
    lectionary_system = (_yaml_scalar(root, "lectionary", "system") or "").strip().casefold()
    if lectionary_system and lectionary_system != "none":
        return "lectionary"
    return None


def _yaml_scalar(root: Path, section_name: str, key: str) -> str | None:
    text = (root / "church.yaml").read_text(encoding="utf-8")
    section = re.search(
        rf"^{re.escape(section_name)}:\s*$([\s\S]*?)(?=^\S|\Z)",
        text,
        re.M,
    )
    if not section:
        return None
    match = re.search(
        rf"^\s{{2}}{re.escape(key)}:\s*[\"']?([^\n\"'#]+)",
        section.group(1),
        re.M,
    )
    return match.group(1).strip() if match else None


def _config_fingerprint(root: Path, stage: str) -> str:
    """Hash only the church.yaml field values that govern this stage's output.

    Parsed with yaml.safe_load rather than matched as raw text, so
    reordering keys, reformatting, or adding a comment leaves the
    fingerprint unchanged; only an actual change to a selected field's
    value does.
    """
    config = yaml.safe_load((root / "church.yaml").read_text(encoding="utf-8"))
    config = config if isinstance(config, dict) else {}
    values: dict[str, Any] = {}
    for section, key in CONFIG_DEPENDENCY_FIELDS.get(stage, ()):
        section_value = config.get(section)
        values[f"{section}.{key}"] = section_value.get(key) if isinstance(section_value, dict) else None
    canonical = json.dumps(values, sort_keys=True, default=str)
    return _sha256_bytes(canonical.encode("utf-8"))


def _receipt_sort_key(item: tuple[Path, dict[str, Any]]) -> tuple[str, str]:
    _, receipt = item
    return (str(receipt.get("created_at", "")), str(receipt.get("receipt_id", "")))


def _receipt_records(sermon_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    receipt_dir = sermon_dir / ".receipts"
    if not receipt_dir.is_dir():
        return []
    records = []
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append((path, value))
    return sorted(records, key=_receipt_sort_key)


def _checks_pass(receipt: dict[str, Any], stage: str) -> bool:
    checks = receipt.get("validation")
    if not isinstance(checks, list):
        return False
    passed = {
        item.get("check")
        for item in checks
        if isinstance(item, dict) and item.get("result") == "pass"
    }
    return REQUIRED_CHECKS[stage] <= passed


def _dependency_map(receipt: dict[str, Any]) -> dict[str, str]:
    values = receipt.get("dependencies")
    if not isinstance(values, list):
        return {}
    return {
        str(item.get("key") or item.get("stage")): str(item.get("sha256"))
        for item in values
        if isinstance(item, dict)
        and (item.get("key") or item.get("stage"))
        and item.get("sha256")
    }


def _artifact_states(
    root: Path,
    sermon_dir: Path,
    receipts: list[tuple[Path, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    current_hashes: dict[str, str] = {}
    for stage in STAGE_ORDER:
        path = sermon_dir / STAGE_FILES[stage]
        present = _nonempty(path)
        current_hash = _sha256(path) if present else None
        if current_hash:
            current_hashes[stage] = current_hash
        stage_receipts = [
            (receipt_path, receipt)
            for receipt_path, receipt in receipts
            if receipt.get("stage") == stage
        ]
        state = {
            "path": str(path),
            "present": present,
            "sha256": current_hash,
            "status": "missing" if not present else "unverified",
            "receipt": None,
            "reason": None,
        }
        if not present:
            states[stage] = state
            continue

        matching = [
            (receipt_path, receipt)
            for receipt_path, receipt in stage_receipts
            if receipt.get("schema_version") == RECEIPT_SCHEMA_VERSION
            and isinstance(receipt.get("artifact"), dict)
            and receipt["artifact"].get("sha256") == current_hash
        ]
        stale_reason = None
        for receipt_path, receipt in reversed(matching):
            if not _checks_pass(receipt, stage):
                stale_reason = "required validation is missing or did not pass"
                continue
            recorded_dependencies = _dependency_map(receipt)
            dependency_failure = next(
                (
                    dependency
                    for dependency in DEPENDENCIES[stage]
                    if states.get(dependency, {}).get("status") != "verified"
                    or recorded_dependencies.get(dependency) != current_hashes.get(dependency)
                ),
                None,
            )
            if dependency_failure:
                stale_reason = f"{dependency_failure} changed or is not verified"
                continue
            config_key = CONFIG_DEPENDENCY_KEY.get(stage)
            auxiliary_failure = (
                config_key
                if config_key is not None
                and recorded_dependencies.get(config_key) != _config_fingerprint(root, stage)
                else None
            )
            if auxiliary_failure:
                stale_reason = f"{auxiliary_failure} changed or is not verified"
                continue
            state.update(
                {
                    "status": "verified",
                    "receipt": str(receipt_path),
                    "reason": None,
                }
            )
            break
        else:
            if matching:
                state["status"] = "stale"
                state["reason"] = stale_reason or "no current receipt has valid dependencies"
            elif stage_receipts:
                state["status"] = "modified"
                state["reason"] = "the file hash does not match any current receipt"
            else:
                state["reason"] = "no receipt exists for this file"
        states[stage] = state
    return states


def _workflow_state(states: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    if states["readings"]["status"] != "verified":
        return "needs_readings", ["readings"]
    if states["research"]["status"] != "verified":
        return "needs_research", ["research"]
    return "research_complete", []


def orient(
    church_folder: str | Path,
    service_date: str | date,
    *,
    mode: str = "manual",
) -> dict[str, Any]:
    """Inspect a sermon workflow without writing anything."""

    try:
        root = _church_root(church_folder)
        date_value = _date_text(service_date)
        mode = _mode_text(mode)
        sermon_dir = root / "sermons" / date_value
        receipts = _receipt_records(sermon_dir)
        states = _artifact_states(root, sermon_dir, receipts)
        state, next_actions = _workflow_state(states)
        selection_mode = _sermon_selection_mode(root)
        if (
            selection_mode == "pastor_selected"
            and states["readings"]["status"] != "verified"
        ):
            state = "awaiting_passage"
            next_actions = [] if mode == "scheduled" else ["confirm_passage"]
        warnings = [
            {
                "code": f"{stage}_{item['status']}",
                "message": item["reason"],
            }
            for stage, item in states.items()
            if item["present"] and item["status"] != "verified" and item["reason"]
        ]
        primary_text = _sermon_primary_text(root)
        if selection_mode is None:
            warnings.append({
                "code": "selection_mode_missing",
                "message": "Choose lectionary or pastor_selected as sermon.selection_mode in church.yaml.",
            })
        if primary_text is None:
            allowed_focus = (
                "selected"
                if selection_mode == "pastor_selected"
                else "first, psalm, second, or gospel"
            )
            warnings.append({
                "code": "research_focus_missing",
                "message": f"Choose {allowed_focus} as the primary research text in church.yaml before recording readings.",
            })
            if states["readings"]["status"] == "verified" and states["research"]["status"] != "verified":
                next_actions = ["choose_research_focus", "research"]
        return {
            "status": "ok",
            "service_date": date_value,
            "mode": mode,
            "stop_after": "research",
            "workflow_state": state,
            "next_actions": next_actions,
            "stage_files": states,
            "selection_mode": selection_mode,
            "research_focus": primary_text,
            "receipts": [str(path) for path, _ in receipts],
            "warnings": warnings,
        }
    except (WorkflowFailure, OSError) as exc:
        return _failure(exc)


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowFailure("invalid_metadata", f"Missing {field}", field=field)
    return text


def _require_iso_datetime(value: Any, field: str) -> str:
    text = _require_text(value, field)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowFailure("invalid_timestamp", f"Invalid ISO timestamp for {field}", field=field) from exc
    return text


def _reading_selection(metadata: dict[str, Any]) -> dict[str, Any]:
    selection = metadata.get("selection")
    if not isinstance(selection, dict):
        raise WorkflowFailure(
            "missing_reading_selection",
            "Reading metadata requires one normalized selection",
            field="metadata.selection",
        )
    selection_mode = _require_text(
        selection.get("selection_mode"),
        "metadata.selection.selection_mode",
    ).lower()
    if selection_mode not in SELECTION_MODES:
        raise WorkflowFailure(
            "invalid_selection_mode",
            "Reading selection_mode must be lectionary or pastor_selected",
            field="metadata.selection.selection_mode",
        )
    for key in ("service_date", "occasion", "translation"):
        _require_text(selection.get(key), f"metadata.selection.{key}")
    readings = selection.get("readings")
    if not isinstance(readings, dict):
        raise WorkflowFailure(
            "missing_reading_selection",
            "Reading selection requires a readings record",
            field="metadata.selection.readings",
        )
    if selection_mode == "lectionary":
        for key in (
            "lectionary_system",
            "year",
            "track",
            "optional_verses_policy",
            "optional_verses",
        ):
            _require_text(selection.get(key), f"metadata.selection.{key}")
        required_roles = ("first", "psalm", "second", "gospel")
    else:
        required_roles = ("selected",)
    for key in required_roles:
        _require_text(readings.get(key), f"metadata.selection.readings.{key}")
    if set(readings) != set(required_roles):
        raise WorkflowFailure(
            "invalid_reading_roles",
            f"{selection_mode} readings must contain exactly: {', '.join(required_roles)}",
            field="metadata.selection.readings",
        )
    placeholders = {"tbd", "unknown", "citation", "passage", "not sure", "later"}
    for key in required_roles:
        if str(readings[key]).strip().casefold() in placeholders:
            raise WorkflowFailure(
                "placeholder_reading",
                f"Reading citation for {key} is still a placeholder",
                field=f"metadata.selection.readings.{key}",
            )
    if selection_mode == "lectionary" and str(selection["lectionary_system"]).strip().casefold() == "none":
        raise WorkflowFailure(
            "invalid_selection_mode",
            "A lectionary selection requires a named lectionary system",
            field="metadata.selection.lectionary_system",
        )
    return selection


def _visible_field(content: str, label: str, *, bullet: bool = False) -> str:
    prefix = r"^-\s+" if bullet else r"^\*\*"
    suffix = r"" if bullet else r"\*\*"
    match = re.search(
        rf"{prefix}{re.escape(label)}:{suffix}\s+(.+?)\s*$",
        content,
        re.I | re.M,
    )
    if not match:
        raise WorkflowFailure(
            "invalid_readings",
            f"Readings are missing a structured {label} value",
            field="content",
        )
    return match.group(1).strip()


def _visible_service_date(content: str) -> str:
    value = _visible_field(content, "Service date")
    for parser in (
        lambda text: date.fromisoformat(text),
        lambda text: datetime.strptime(text, "%B %d, %Y").date(),
        lambda text: datetime.strptime(text, "%b %d, %Y").date(),
    ):
        try:
            return parser(value).isoformat()
        except ValueError:
            continue
    raise WorkflowFailure(
        "invalid_readings",
        "Service date must be ISO or a spelled-out English date",
        field="content",
    )


def _validate_reading_sources(
    metadata: dict[str, Any],
    content: str,
    root: Path,
    service_date: str,
) -> None:
    selection = _reading_selection(metadata)
    if str(selection["service_date"]) != service_date:
        raise WorkflowFailure(
            "reading_selection_mismatch",
            "Reading selection date does not match the requested service date",
            field="metadata.selection.service_date",
        )
    selection_mode = str(selection["selection_mode"]).strip().lower()
    visible_values = {
        "service_date": _visible_service_date(content),
        "occasion": _visible_field(content, "Occasion"),
        "translation": _visible_field(content, "Translation"),
    }
    if selection_mode == "lectionary":
        visible_values.update({
            "lectionary_system": _visible_field(content, "Lectionary"),
            "year": _visible_field(content, "Year"),
            "track": _visible_field(content, "Track"),
            "optional_verses": _visible_field(content, "Optional verses this week"),
        })
        visible_readings = {
            "first": _visible_field(content, "First Reading", bullet=True),
            "psalm": _visible_field(content, "Psalm", bullet=True),
            "second": _visible_field(content, "Second Reading", bullet=True),
            "gospel": _visible_field(content, "Gospel", bullet=True),
        }
    else:
        visible_readings = {
            "selected": _visible_field(content, "Selected Text", bullet=True),
        }
    for key, visible in visible_values.items():
        expected = str(selection[key]).strip()
        if visible.casefold() != expected.casefold():
            raise WorkflowFailure(
                "reading_content_mismatch",
                f"Visible {key} does not match the normalized selection",
                field="content",
            )
    visible_mode = _visible_field(content, "Selection mode")
    if visible_mode.casefold() != SELECTION_MODE_DISPLAY[selection_mode].casefold():
        raise WorkflowFailure(
            "reading_content_mismatch",
            "Visible selection mode does not match the normalized selection",
            field="content",
        )
    if selection_mode == "lectionary":
        visible_policy = _visible_field(content, "Optional verse approach")
        policy_key = str(selection["optional_verses_policy"]).strip()
        expected_policy = OPTIONAL_POLICY_DISPLAY.get(policy_key.casefold(), policy_key)
        if visible_policy.casefold() != expected_policy.casefold():
            raise WorkflowFailure(
                "reading_content_mismatch",
                "Visible optional verse approach does not match the normalized selection",
                field="content",
            )
    for role, visible in visible_readings.items():
        expected = str(selection["readings"][role]).strip()
        if visible != expected:
            raise WorkflowFailure(
                "reading_content_mismatch",
                f"Visible {role} citation does not match the normalized selection",
                field="content",
            )
    configured_mode = _sermon_selection_mode(root)
    if configured_mode is None:
        raise WorkflowFailure(
            "selection_mode_missing",
            "Set sermon.selection_mode in church.yaml before recording readings",
            field="church.yaml",
        )
    if configured_mode != selection_mode:
        raise WorkflowFailure(
            "selection_mode_mismatch",
            "Reading selection mode does not match sermon.selection_mode in church.yaml",
            field="metadata.selection.selection_mode",
        )
    configured_values = {
        "translation": _yaml_scalar(root, "lectionary", "translation"),
    }
    if selection_mode == "lectionary":
        configured_values.update({
            "lectionary_system": _yaml_scalar(root, "lectionary", "system"),
            "track": _yaml_scalar(root, "lectionary", "track"),
            "optional_verses_policy": _yaml_scalar(root, "lectionary", "optional_verses"),
        })
    missing_policy = [key for key, value in configured_values.items() if not value]
    if missing_policy:
        raise WorkflowFailure(
            "reading_policy_missing",
            f"Church reading policy is missing: {', '.join(missing_policy)}",
            field="church.yaml",
        )
    for key, configured in configured_values.items():
        selected = str(selection[key]).strip()
        if selected.casefold() != str(configured).strip().casefold():
            raise WorkflowFailure(
                "reading_policy_mismatch",
                f"Reading selection {key} does not match church.yaml",
                field=f"metadata.selection.{key}",
            )
    if selection_mode == "pastor_selected":
        confirmation = metadata.get("selection_confirmation")
        if not isinstance(confirmation, dict):
            raise WorkflowFailure(
                "pastor_selection_unconfirmed",
                "A pastor-selected passage requires explicit pastor confirmation",
                field="metadata.selection_confirmation",
            )
        if confirmation.get("authorship") != "pastor_supplied":
            raise WorkflowFailure(
                "pastor_selection_unconfirmed",
                "Passage confirmation must be marked pastor_supplied",
                field="metadata.selection_confirmation.authorship",
            )
        confirmed_at = _require_iso_datetime(
            confirmation.get("confirmed_at"),
            "metadata.selection_confirmation.confirmed_at",
        )
        confirmed_time = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
        if confirmed_time.tzinfo is None:
            raise WorkflowFailure(
                "invalid_timestamp",
                "Passage confirmation time must include a timezone",
                field="metadata.selection_confirmation.confirmed_at",
            )
        if confirmed_time.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise WorkflowFailure(
                "future_confirmation",
                "Passage confirmation time cannot be in the future",
                field="metadata.selection_confirmation.confirmed_at",
            )
        confirmed_service_date = _require_text(
            confirmation.get("service_date"),
            "metadata.selection_confirmation.service_date",
        )
        if confirmed_service_date != service_date:
            raise WorkflowFailure(
                "pastor_selection_date_mismatch",
                "Pastor confirmation does not belong to the requested service date",
                field="metadata.selection_confirmation.service_date",
            )
        selected_text = _require_text(
            confirmation.get("selected_text"),
            "metadata.selection_confirmation.selected_text",
        )
        if selected_text != str(selection["readings"]["selected"]).strip():
            raise WorkflowFailure(
                "pastor_selection_mismatch",
                "Pastor confirmation does not match the selected passage",
                field="metadata.selection_confirmation.selected_text",
            )
        visible_confirmation = _visible_field(content, "Selection confirmation")
        if visible_confirmation != "Pastor confirmed this passage for this service.":
            raise WorkflowFailure(
                "pastor_selection_unconfirmed",
                "readings.md must state that the pastor confirmed the passage",
                field="content",
            )
    configured_primary = _sermon_primary_text(root)
    if configured_primary is None:
        raise WorkflowFailure(
            "research_focus_missing",
            "Set sermon.primary_text in church.yaml before recording readings",
            field="church.yaml",
        )
    allowed_primary = (
        {"first", "psalm", "second", "gospel"}
        if selection_mode == "lectionary"
        else {"selected"}
    )
    if configured_primary not in allowed_primary:
        raise WorkflowFailure(
            "research_focus_mismatch",
            "sermon.primary_text is incompatible with sermon.selection_mode",
            field="church.yaml",
        )
    expected_primary = f"{configured_primary.title()}, {selection['readings'][configured_primary]}"
    visible_primary = _visible_field(content, "Primary research text")
    if visible_primary != expected_primary:
        raise WorkflowFailure(
            "reading_content_mismatch",
            "Visible primary research text does not match church.yaml and the normalized selection",
            field="content",
        )
    sources = metadata.get("sources")
    minimum_sources = 2 if selection_mode == "lectionary" else 1
    if not isinstance(sources, list) or len(sources) < minimum_sources:
        raise WorkflowFailure(
            "unverified_sources",
            (
                "Lectionary readings require two retrieved sources on distinct published hosts"
                if selection_mode == "lectionary"
                else "A pastor-selected passage requires one retrieved published text reference"
            ),
            field="metadata.sources",
        )
    hosts = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise WorkflowFailure("unverified_sources", "Each source must be a record")
        prefix = f"metadata.sources[{index}]"
        for key in ("label", "url", "host", "verified_on", "supports"):
            _require_text(source.get(key), f"{prefix}.{key}")
        _require_iso_datetime(source.get("retrieved_at"), f"{prefix}.retrieved_at")
        if source.get("result") != "verified":
            raise WorkflowFailure(
                "unverified_sources",
                "Every reading source result must be verified",
                field=f"{prefix}.result",
            )
        parsed = urlparse(str(source["url"]))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise WorkflowFailure("invalid_source_url", "Reading source URL is invalid", field=f"{prefix}.url")
        declared = str(source["host"]).lower().removeprefix("www.")
        actual = parsed.hostname.lower().removeprefix("www.")
        if declared != actual:
            raise WorkflowFailure(
                "source_host_mismatch",
                f"Declared host {declared} does not match URL host {actual}",
                field=f"{prefix}.host",
            )
        hosts.add(actual)
        if str(source["url"]).strip() not in content:
            raise WorkflowFailure(
                "reading_source_unlinked",
                "Every reading verification URL must appear in readings.md",
                field=f"{prefix}.url",
            )
        if selection_mode == "lectionary":
            observed = source.get("observed_selection")
            if observed != selection:
                raise WorkflowFailure(
                    "reading_source_disagreement",
                    "Reading source observation does not match the normalized selection",
                    field=f"{prefix}.observed_selection",
                )
        else:
            observed_text = _require_text(
                source.get("observed_text"),
                f"{prefix}.observed_text",
            )
            if observed_text != str(selection["readings"]["selected"]).strip():
                raise WorkflowFailure(
                    "reading_source_disagreement",
                    "Published text reference does not match the pastor-selected passage",
                    field=f"{prefix}.observed_text",
                )
            observed_translation = _require_text(
                source.get("observed_translation"),
                f"{prefix}.observed_translation",
            )
            if observed_translation.casefold() != str(selection["translation"]).strip().casefold():
                raise WorkflowFailure(
                    "reading_source_disagreement",
                    "Published text reference does not match the configured translation",
                    field=f"{prefix}.observed_translation",
                )
    if selection_mode == "lectionary" and len(hosts) < 2:
        raise WorkflowFailure(
            "duplicate_source_host",
            "Reading verification requires two distinct hosts",
            field="metadata.sources",
        )


def _validate_research_sources(metadata: dict[str, Any]) -> None:
    sources = metadata.get("sources")
    if not isinstance(sources, list) or len(sources) < 4:
        raise WorkflowFailure(
            "unverified_sources",
            "Research requires at least four materially used sources",
            field="metadata.sources",
        )
    required = (
        "source_id",
        "title",
        "author",
        "publisher",
        "url_or_citation",
        "source_type",
        "retrieved_at",
        "access_result",
        "claim_support",
        "currency_note",
    )
    source_ids = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise WorkflowFailure("unverified_sources", "Each source must be a record")
        prefix = f"metadata.sources[{index}]"
        for key in required:
            if key != "retrieved_at":
                _require_text(source.get(key), f"{prefix}.{key}")
        _require_iso_datetime(source.get("retrieved_at"), f"{prefix}.retrieved_at")
        if source["access_result"] not in {"opened", "verified"}:
            raise WorkflowFailure(
                "unverified_sources",
                "Research source access_result must be opened or verified",
                field=f"{prefix}.access_result",
            )
        source_id = str(source["source_id"])
        if source_id in source_ids:
            raise WorkflowFailure("duplicate_source_id", f"Duplicate source_id: {source_id}")
        source_ids.add(source_id)
        location = str(source["url_or_citation"]).strip()
        parsed = urlparse(location)
        if parsed.scheme:
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise WorkflowFailure(
                    "invalid_source_url",
                    "Research source URL is invalid",
                    field=f"{prefix}.url_or_citation",
                )
        elif len(location.split()) < 4:
            raise WorkflowFailure(
                "imprecise_source_citation",
                "A non-URL research source needs a precise citation",
                field=f"{prefix}.url_or_citation",
            )
        if len(str(source["claim_support"]).split()) < 4:
            raise WorkflowFailure(
                "insufficient_claim_support",
                "Research source claim_support must identify the supported claim",
                field=f"{prefix}.claim_support",
            )
        if len(str(source["currency_note"]).split()) < 2:
            raise WorkflowFailure(
                "missing_currency_note",
                "Research source currency_note must explain its date fitness",
                field=f"{prefix}.currency_note",
            )


def _stage_receipt_metadata(
    states: dict[str, dict[str, Any]],
    stage: str,
) -> dict[str, Any]:
    receipt_path = states[stage].get("receipt")
    if not receipt_path:
        raise WorkflowFailure("receipt_missing", f"Current {stage} receipt is unavailable")
    try:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowFailure("malformed_receipt", f"Current {stage} receipt is invalid") from exc
    metadata = receipt.get("metadata") if isinstance(receipt, dict) else None
    if not isinstance(metadata, dict):
        raise WorkflowFailure("malformed_receipt", f"Current {stage} receipt metadata is invalid")
    return metadata


def _research_header_value(header: str, label: str) -> str:
    match = re.search(
        rf"^\*\*{re.escape(label)}:\*\*\s+(.+?)\s*$",
        header,
        re.M,
    )
    if not match:
        raise WorkflowFailure(
            "invalid_research_header",
            f"Research brief header is missing {label}",
            field="content",
        )
    return match.group(1).strip()


def _research_header_date(header: str) -> str:
    value = _research_header_value(header, "Preaching date")
    for parser in (
        lambda text: date.fromisoformat(text),
        lambda text: datetime.strptime(text, "%B %d, %Y").date(),
        lambda text: datetime.strptime(text, "%b %d, %Y").date(),
    ):
        try:
            return parser(value).isoformat()
        except ValueError:
            continue
    raise WorkflowFailure(
        "invalid_research_header",
        "Preaching date must be ISO or a spelled-out English date",
        field="content",
    )


def _validate_research_header(
    content: str,
    reading_metadata: dict[str, Any],
    role: str,
    citation: str,
) -> str:
    header = content.split("## Research orientation", 1)[0]
    selection = reading_metadata.get("selection")
    if not isinstance(selection, dict):
        raise WorkflowFailure("malformed_receipt", "Current readings selection is invalid")
    selection_mode = str(selection.get("selection_mode") or "").strip().lower()
    if not selection_mode and selection.get("lectionary_system"):
        selection_mode = "lectionary"
    if selection_mode not in SELECTION_MODES:
        raise WorkflowFailure("malformed_receipt", "Current readings selection mode is invalid")
    exact_values = {
        "Liturgical setting": str(selection["occasion"]).strip(),
        "Text": citation,
        "Selection mode": SELECTION_MODE_DISPLAY[selection_mode],
        "Translation": str(selection["translation"]).strip(),
    }
    if _research_header_date(header) != str(selection["service_date"]).strip():
        raise WorkflowFailure(
            "research_header_mismatch",
            "Research preaching date does not match the verified readings",
            field="content",
        )
    for label, expected in exact_values.items():
        if _research_header_value(header, label).casefold() != expected.casefold():
            raise WorkflowFailure(
                "research_header_mismatch",
                f"Research {label} does not match the verified readings",
                field="content",
            )
    sources = reading_metadata.get("sources")
    if not isinstance(sources, list):
        raise WorkflowFailure("malformed_receipt", "Current readings sources are invalid")
    source_urls = [str(source.get("url") or "").strip() for source in sources if isinstance(source, dict)]
    if selection_mode == "lectionary":
        expected_lectionary = f"{selection['lectionary_system']}, Year {selection['year']}"
        if _research_header_value(header, "Lectionary").casefold() != expected_lectionary.casefold():
            raise WorkflowFailure(
                "research_header_mismatch",
                "Research lectionary and year do not match the verified readings",
                field="content",
            )
        for label, key in (("Track", "track"), ("Optional verses", "optional_verses")):
            if _research_header_value(header, label).casefold() != str(selection[key]).strip().casefold():
                raise WorkflowFailure(
                    "research_header_mismatch",
                    f"Research {label} does not match the verified readings",
                    field="content",
                )
        verification = _research_header_value(header, "Reading verification")
        if not source_urls or any(url not in verification for url in source_urls):
            raise WorkflowFailure(
                "research_header_mismatch",
                "Research header must include every reading verification URL",
                field="content",
            )
    else:
        for forbidden in ("Lectionary", "Year", "Track", "Optional verses"):
            if re.search(rf"^\*\*{re.escape(forbidden)}:\*\*", header, re.M):
                raise WorkflowFailure(
                    "false_lectionary_context",
                    "Pastor-selected research must not claim lectionary, year, track, or optional-verse context",
                    field="content",
                )
        if _research_header_value(header, "Selection provenance") != "Pastor confirmed for this service":
            raise WorkflowFailure(
                "research_header_mismatch",
                "Pastor-selected research must state its selection provenance",
                field="content",
            )
        if re.search(r"^\*\*Text verification:\*\*", header, re.M):
            raise WorkflowFailure(
                "invalid_research_header",
                "Keep text verification in readings.md and its receipt, not the research brief",
                field="content",
            )
    return selection_mode


def _validate_research_target(
    content: str,
    metadata: dict[str, Any],
    reading_metadata: dict[str, Any],
    configured_role: str | None,
    mode: str,
) -> None:
    target = metadata.get("research_target")
    if not isinstance(target, dict):
        raise WorkflowFailure(
            "research_target_missing",
            "Research metadata must identify the primary preaching text",
            field="metadata.research_target",
        )
    role = str(target.get("role", "")).strip().lower()
    if role not in READING_ROLES:
        raise WorkflowFailure(
            "invalid_research_target",
            "Research target role must be first, psalm, second, gospel, or selected",
            field="metadata.research_target.role",
        )
    selection = reading_metadata.get("selection")
    readings = selection.get("readings") if isinstance(selection, dict) else None
    selection_mode = str(selection.get("selection_mode") or "").strip().lower() if isinstance(selection, dict) else ""
    if not selection_mode and isinstance(selection, dict) and selection.get("lectionary_system"):
        selection_mode = "lectionary"
    if selection_mode not in SELECTION_MODES:
        raise WorkflowFailure("malformed_receipt", "Current readings selection mode is invalid")
    basis = str(target.get("selection_basis", "")).strip()
    allowed_roles = (
        {"first", "psalm", "second", "gospel"}
        if selection_mode == "lectionary"
        else {"selected"}
    )
    allowed_bases = (
        {"church_profile", "pastor_override"}
        if selection_mode == "lectionary"
        else {"pastor_selection"}
    )
    if role not in allowed_roles:
        raise WorkflowFailure(
            "research_target_mode_mismatch",
            "Research target role is incompatible with the verified selection mode",
            field="metadata.research_target.role",
        )
    if basis not in allowed_bases:
        raise WorkflowFailure(
            "invalid_research_target",
            f"Research target selection_basis must be one of: {', '.join(sorted(allowed_bases))}",
            field="metadata.research_target.selection_basis",
        )
    expected_citation = readings.get(role) if isinstance(readings, dict) else None
    if not isinstance(expected_citation, str) or not expected_citation.strip():
        raise WorkflowFailure(
            "malformed_receipt",
            f"Current readings receipt has no {role} citation",
            field="readings.metadata.selection",
        )
    citation = str(target.get("citation", "")).strip()
    if citation != expected_citation.strip():
        raise WorkflowFailure(
            "research_target_mismatch",
            "Research target citation does not match the verified readings",
            field="metadata.research_target.citation",
        )
    if basis in {"church_profile", "pastor_selection"}:
        if configured_role is None:
            raise WorkflowFailure(
                "research_focus_missing",
                "Set sermon.primary_text in church.yaml before using the church profile",
                field="church.yaml",
            )
        if role != configured_role:
            raise WorkflowFailure(
                "research_focus_mismatch",
                "Research target does not match sermon.primary_text in church.yaml",
                field="metadata.research_target.role",
            )
    scheduled_basis = "church_profile" if selection_mode == "lectionary" else "pastor_selection"
    if mode == "scheduled" and (configured_role is None or basis != scheduled_basis):
        raise WorkflowFailure(
            "scheduled_research_focus_required",
            "Scheduled research requires the configured, verified primary text",
            field="church.yaml",
        )
    _validate_research_header(content, reading_metadata, role, citation)


def _headings(content: str) -> list[str]:
    return [
        re.sub(r"^#{1,6}\s+", "", line).strip()
        for line in content.splitlines()
        if re.match(r"^#{1,6}\s+", line)
    ]


def _church_local_terms(root: Path) -> list[str]:
    text = (root / "church.yaml").read_text(encoding="utf-8")
    values = []
    for key in ("name", "short_name", "city", "address"):
        match = re.search(rf"^\s{{2}}{key}:\s*[\"']?([^\n\"']+)", text, re.M)
        if match:
            value = match.group(1).strip()
            if len(value) >= 4:
                values.append(value)
    return values


def _validate_research(
    content: str,
    metadata: dict[str, Any],
    root: Path,
) -> list[dict[str, str]]:
    headings = _headings(content)
    missing = [
        required
        for required in RESEARCH_HEADINGS
        if not any(required.lower() in heading.lower() for heading in headings)
    ]
    if missing:
        raise WorkflowFailure(
            "invalid_research_shape",
            f"Research brief is missing sections: {', '.join(missing)}",
            field="content",
        )
    positions = [
        next(index for index, heading in enumerate(headings) if required.lower() in heading.lower())
        for required in RESEARCH_HEADINGS
    ]
    if positions != sorted(positions):
        raise WorkflowFailure(
            "invalid_research_order",
            "Research brief sections are out of the required order",
            field="content",
        )
    retired_headings = {
        "theological voices",
        "interpretive disagreement",
        "interpretive guardrails",
        "scholarship account",
    }
    if any(heading.casefold() in retired_headings for heading in headings):
        raise WorkflowFailure(
            "invalid_research_organization",
            "Use the current research brief shape without retired duplicate or scholarship sections",
            field="content",
        )
    voices_match = re.search(
        r"^##\s+Interpretive Conversations\s*$([\s\S]*?)(?=^##\s+Contemporary Convergence\s*$)",
        content,
        re.I | re.M,
    )
    thematic_headings = re.findall(
        r"^###\s+(.+?)\s*$",
        voices_match.group(1) if voices_match else "",
        re.M,
    )
    if len(thematic_headings) < 2 or any(
        not heading.rstrip().endswith("?") for heading in thematic_headings
    ):
        raise WorkflowFailure(
            "invalid_research_organization",
            "Interpretive Conversations must use at least two question-shaped thematic subsections",
            field="content",
        )
    header = content.split("## Research orientation", 1)[0]
    for field in (
        "Preaching date",
        "Liturgical setting",
        "Text",
        "Selection mode",
        "Translation",
    ):
        if not re.search(rf"^\*\*{re.escape(field)}:\*\*\s+\S", header, re.M):
            raise WorkflowFailure(
                "invalid_research_header",
                f"Research brief header is missing {field}",
                field="content",
            )
    reflection_index = next(
        index
        for index, heading in enumerate(headings)
        if "questions for reflection" in heading.lower()
    )
    if reflection_index != len(headings) - 1:
        raise WorkflowFailure(
            "reflection_stop_violated",
            "Questions for reflection must be the final section",
            field="content",
        )
    reflection_match = re.search(
        r"^#{1,6}\s+Questions for reflection\s*$([\s\S]*)\Z",
        content,
        re.I | re.M,
    )
    reflection_lines = [
        re.sub(r"^[-*\d.)\s]+", "", line).strip()
        for line in (reflection_match.group(1).splitlines() if reflection_match else [])
        if line.strip()
    ]
    if not reflection_lines or any(not line.endswith("?") for line in reflection_lines):
        raise WorkflowFailure(
            "reflection_stop_violated",
            "The final section may contain reflection questions only",
            field="content",
        )
    if LOCALIZATION.search(content):
        raise WorkflowFailure(
            "research_localization",
            "Research must not claim knowledge of the pastor's local context",
            field="content",
        )
    local_hits = [term for term in _church_local_terms(root) if term.lower() in content.lower()]
    if local_hits:
        raise WorkflowFailure(
            "research_localization",
            f"Research contains church-folder local data: {', '.join(local_hits)}",
            field="content",
        )
    if re.search(r"[\u2014\u2013]", content):
        raise WorkflowFailure("prohibited_dash", "Research contains an em dash or en dash", field="content")
    links = len(re.findall(r"\]\(https?://", content))
    if links < 4:
        raise WorkflowFailure(
            "insufficient_citations",
            f"Research brief has {links} linked citations; at least four are required",
            field="content",
        )
    for index, source in enumerate(metadata.get("sources", [])):
        location = str(source.get("url_or_citation", "")).strip()
        if urlparse(location).scheme in {"http", "https"} and location not in content:
            raise WorkflowFailure(
                "unlinked_research_source",
                "Every URL source in the ledger must appear in the research brief",
                field=f"metadata.sources[{index}].url_or_citation",
            )
    words = len(content.split())
    if words < 1200:
        raise WorkflowFailure(
            "research_too_short",
            f"Research brief has {words} words; 1,200 is the mechanical floor",
            field="content",
        )
    warnings = []
    if words < 2500:
        scope_note = str(metadata.get("scope_note", "")).strip()
        if len(scope_note.split()) < 5:
            raise WorkflowFailure(
                "research_scope_unexplained",
                "A research brief below 2,500 words requires a specific scope_note",
                field="metadata.scope_note",
            )
        warnings.append({
            "code": "research_below_typical_range",
            "message": f"Research brief has {words} words; the typical range starts at 2,500",
        })
    return warnings


def _validate_content(
    stage: str,
    content: str,
    metadata: dict[str, Any],
    root: Path,
) -> list[dict[str, str]]:
    if not content.strip():
        raise WorkflowFailure("empty_content", f"{stage} content is empty", field="content")
    if stage == "readings":
        selection = _reading_selection(metadata)
        common_fields = (
            "Service date",
            "Occasion",
            "Selection mode",
            "Primary research text",
            "Translation",
        )
        if str(selection["selection_mode"]).strip().lower() == "lectionary":
            required_fields = common_fields + (
                "Lectionary",
                "Year",
                "Track",
                "Optional verse approach",
                "Optional verses this week",
                "First Reading",
                "Psalm",
                "Second Reading",
                "Gospel",
            )
            minimum_links = 2
        else:
            required_fields = common_fields + ("Selected Text", "Selection confirmation")
            minimum_links = 1
        if not all(re.search(rf"\b{re.escape(name)}\b", content, re.I) for name in required_fields):
            raise WorkflowFailure(
                "invalid_readings",
                "Readings are missing required service, selection, translation, or citation fields",
                field="content",
            )
        if len(re.findall(r"\]\(https?://", content)) < minimum_links:
            raise WorkflowFailure(
                "invalid_readings",
                "Readings do not cite the required published verification page or pages",
                field="content",
            )
        if re.search(r"[\u2014\u2013]", content):
            raise WorkflowFailure("prohibited_dash", "Readings contain an em dash or en dash")
        return []
    if stage == "research":
        return _validate_research(content, metadata, root)
    raise WorkflowFailure("unknown_stage", f"Unknown sermon research stage: {stage}")


def _check_order(
    states: dict[str, dict[str, Any]],
    _root: Path,
    stage: str,
) -> None:
    for required in DEPENDENCIES[stage]:
        if states[required]["status"] != "verified":
            raise WorkflowFailure(
                "stage_out_of_order",
                f"Complete and verify {required} before {stage}",
                field=required,
            )
def _dependency_receipt_values(
    root: Path,
    states: dict[str, dict[str, Any]],
    stage: str,
) -> list[dict[str, str]]:
    values = [
        {"key": dependency, "kind": "artifact", "sha256": str(states[dependency]["sha256"])}
        for dependency in DEPENDENCIES[stage]
    ]
    config_key = CONFIG_DEPENDENCY_KEY.get(stage)
    if config_key is not None:
        values.append({
            "key": config_key,
            "kind": "configuration_fields",
            "path": "church.yaml",
            "sha256": _config_fingerprint(root, stage),
        })
    return values


def _validation_values(stage: str) -> list[dict[str, str]]:
    return [
        {"check": check, "result": "pass"}
        for check in sorted(REQUIRED_CHECKS[stage])
    ]


def _write_receipt_and_artifact(
    sermon_dir: Path,
    target: Path,
    content: bytes,
    receipt: dict[str, Any],
) -> Path:
    sermon_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir = sermon_dir / ".receipts"
    receipt_dir.mkdir(exist_ok=True)
    receipt_path = receipt_dir / f"{receipt['stage']}-{receipt['receipt_id']}.json"
    artifact_fd, artifact_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=sermon_dir)
    receipt_fd, receipt_name = tempfile.mkstemp(prefix=".receipt.", dir=receipt_dir)
    try:
        with os.fdopen(artifact_fd, "wb") as artifact_handle:
            artifact_handle.write(content)
            artifact_handle.flush()
            os.fsync(artifact_handle.fileno())
        with os.fdopen(receipt_fd, "w", encoding="utf-8") as receipt_handle:
            json.dump(receipt, receipt_handle, indent=2)
            receipt_handle.write("\n")
            receipt_handle.flush()
            os.fsync(receipt_handle.fileno())
        os.replace(artifact_name, target)
        os.replace(receipt_name, receipt_path)
    finally:
        for temporary in (artifact_name, receipt_name):
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass
    return receipt_path


def record(
    church_folder: str | Path,
    service_date: str | date,
    stage: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    *,
    replace: bool = False,
    mode: str = "manual",
) -> dict[str, Any]:
    """Validate and record one visible artifact with an immutable receipt."""

    try:
        root = _church_root(church_folder)
        date_value = _date_text(service_date)
        mode = _mode_text(mode)
        if stage not in STAGE_FILES:
            raise WorkflowFailure("unknown_stage", f"Unknown sermon stage: {stage}", field="stage")
        metadata = metadata or {}
        if mode == "scheduled" and stage == "readings":
            selection = _reading_selection(metadata)
            if str(selection["selection_mode"]).strip().lower() == "pastor_selected":
                raise WorkflowFailure(
                    "scheduled_selection_required",
                    "Scheduled runs cannot choose or record a pastor-selected passage",
                    field="metadata.selection.selection_mode",
                )
        sermon_dir = (root / "sermons" / date_value).resolve()
        if not _inside(sermon_dir, root):
            raise WorkflowFailure("unsafe_path", "Sermon path escapes the church folder")
        receipts = _receipt_records(sermon_dir)
        states = _artifact_states(root, sermon_dir, receipts)
        _check_order(states, root, stage)

        warnings = _validate_content(stage, content, metadata, root)
        if stage == "readings":
            _validate_reading_sources(metadata, content, root, date_value)
        elif stage == "research":
            _validate_research_sources(metadata)
            _validate_research_target(
                content,
                metadata,
                _stage_receipt_metadata(states, "readings"),
                _sermon_primary_text(root),
                mode,
            )

        target = sermon_dir / STAGE_FILES[stage]
        if target.exists() and not replace:
            normalized_hash = _sha256_bytes((content.rstrip() + "\n").encode("utf-8"))
            existing_normalized_hash = _sha256_bytes(
                (target.read_text(encoding="utf-8").rstrip() + "\n").encode("utf-8")
            )
            stage_has_receipt = any(receipt.get("stage") == stage for _, receipt in receipts)
            adopting_first_file = (
                not stage_has_receipt
                and states[stage]["status"] == "unverified"
                and existing_normalized_hash == normalized_hash
            )
            if not adopting_first_file:
                raise WorkflowFailure(
                    "stage_exists",
                    f"Stage already exists: {target}. Pass replace only after confirming replacement with the pastor.",
                    field="replace",
                )

        content_bytes = (content.rstrip() + "\n").encode("utf-8")
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "receipt_id": str(uuid.uuid4()),
            "created_at": _now(),
            "implementation_version": IMPLEMENTATION_VERSION,
            "service_date": date_value,
            "stage": stage,
            "artifact": {
                "path": str(target.relative_to(root)),
                "sha256": _sha256_bytes(content_bytes),
                "bytes": len(content_bytes),
            },
            "dependencies": _dependency_receipt_values(root, states, stage),
            "validation": _validation_values(stage),
            "metadata": metadata,
        }
        receipt_path = _write_receipt_and_artifact(sermon_dir, target, content_bytes, receipt)
        state = orient(root, date_value, mode=mode)
        return {
            "status": "recorded",
            "stage": stage,
            "artifact": receipt["artifact"],
            "receipt": str(receipt_path),
            "workflow_state": state.get("workflow_state"),
            "next_actions": state.get("next_actions", []),
            "warnings": warnings,
        }
    except (WorkflowFailure, OSError) as exc:
        return _failure(exc)


__all__ = ["orient", "record"]
