"""Resolve a church worship profile into explicit weekly liturgy choices.

The resolver is intentionally separate from PDF production. It reads the
church-owned profile, applies a week's explicit overrides, validates the
selected tradition vocabulary, and returns a reviewable result. Production
receives that result and does not infer worship choices.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any


REQUIRED_CHOICES = ("eucharistic_prayer", "lords_prayer")
PROFILE_NAME = "worship/profile.yaml"
GENERAL_BLESSING = "general-blessing"
VARIANT_FIELD = "service.variant"
SOURCE_CHOICE_KEYS = ("eucharistic_prayer", "lords_prayer", "prayers_of_the_people")
EXPLICIT_PRINT_CHOICES = ("include_creed", "include_confession", "print_full_eucharistic_prayer")
READING_DISPLAY_CHOICES = ("include_first_reading", "include_second_reading")
SERVICE_PLAN_ANCHORS = {
    "episcopal-rite-ii": frozenset({
        "opening-acclamation",
        "collect-for-purity",
        "collect-of-day",
        "nicene-creed",
        "prayers-of-the-people",
        "confession-of-sin",
        "peace",
        "doxology",
        "eucharistic-prayer",
        "lords-prayer",
        "breaking-of-bread",
        "post-communion-prayer",
        "dismissal",
    }),
    "lutheran-holy-communion": frozenset({
        "gathering",
        "word",
        "creed",
        "prayers",
        "peace",
        "meal",
        "communion",
        "sending",
    }),
}


class WorshipResolutionError(ValueError):
    """A profile cannot be resolved into a safe weekly worship input."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def _yaml_module() -> Any:
    if importlib.util.find_spec("yaml") is None:
        raise WorshipResolutionError(
            "dependency_unavailable",
            "PyYAML is required to read worship/profile.yaml. Install it with: python3 -m pip install PyYAML",
        )
    import yaml

    return yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load one YAML mapping with a stable operational error."""
    target = Path(path)
    if not target.is_file():
        raise WorshipResolutionError("profile_missing", f"Worship profile was not found: {target}")
    try:
        value = _yaml_module().safe_load(target.read_text(encoding="utf-8"))
    except WorshipResolutionError:
        raise
    except Exception as exc:
        raise WorshipResolutionError("profile_invalid", f"Could not read {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorshipResolutionError("profile_invalid", f"Expected a YAML mapping in {target}")
    return value


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _profile_path(church_folder: str | Path) -> tuple[Path, str]:
    root = Path(church_folder).expanduser().resolve()
    church_config = root / "church.yaml"
    pointer = PROFILE_NAME
    if church_config.is_file():
        try:
            values = load_yaml(church_config)
            pointer = str(values.get("worship_profile") or pointer)
        except WorshipResolutionError as exc:
            if exc.code != "dependency_unavailable":
                raise
    profile = (root / pointer).resolve()
    try:
        profile.relative_to(root)
    except ValueError as exc:
        raise WorshipResolutionError(
            "unsafe_path", "The worship profile must remain inside the church folder", field="worship_profile"
        ) from exc
    return profile, pointer


def _pack_path(pack_id: str, plugin_root: Path) -> Path:
    safe_id = Path(pack_id)
    if safe_id.name != pack_id or safe_id.suffix:
        raise WorshipResolutionError("invalid_tradition_pack", f"Invalid tradition pack identifier: {pack_id}")
    catalog_path = plugin_root / "skills" / "bulletin" / "traditions" / "catalog.yaml"
    catalog = load_yaml(catalog_path)
    entries = catalog.get("packs", [])
    registered = {
        str(entry.get("id")) for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    } if isinstance(entries, list) else set()
    if pack_id not in registered:
        raise WorshipResolutionError("tradition_pack_unregistered", f"Tradition pack is not registered: {pack_id}")
    path = plugin_root / "skills" / "bulletin" / "traditions" / f"{pack_id}.yaml"
    if not path.is_file():
        raise WorshipResolutionError("tradition_pack_missing", f"Tradition pack was not found: {pack_id}")
    return path


def _choice_values(pack: dict[str, Any], key: str) -> list[str]:
    choices = pack.get("choices", {})
    item = choices.get(key, {}) if isinstance(choices, dict) else {}
    values = item.get("values", []) if isinstance(item, dict) else []
    return [str(value) for value in values] if isinstance(values, list) else []


def _shipped_source(pack: dict[str, Any], key: str, choice: str) -> str | None:
    """Return the shipped source identifier for one selected choice."""
    shipped = pack.get("shipped_sources", {})
    choices = shipped.get(key, {}) if isinstance(shipped, dict) else {}
    if not isinstance(choices, dict):
        return None
    value = choices.get(choice)
    return str(value).strip() if str(value or "").strip() else None


def _private_source_status(
    value: Any,
    *,
    choice: str,
    church_root: Path | None,
    field: str,
) -> tuple[bool, str | None]:
    """Check a private source path without allowing folder escape."""
    raw = value
    if not isinstance(raw, str) or not raw.strip():
        return False, None
    if church_root is None:
        return False, f"Confirm the church-owned source path for {choice!r} before producing"
    try:
        path = _safe_church_path(church_root, raw, field=field)
    except WorshipResolutionError as exc:
        return False, exc.message
    if not path.is_file():
        return False, f"Private source file was not found for {choice!r}: {raw}"
    from .liturgy_sources import LiturgySourceError, require_verified_source
    try:
        require_verified_source(church_root, path)
    except LiturgySourceError as exc:
        return False, str(exc)
    return True, None


def required_lutheran_units(liturgy: dict[str, Any]) -> list[str]:
    """List the local texts used by the Lutheran renderer's service sections."""
    sections = [("gathering", "gathering"), ("prayers", "prayers"),
                ("meal", "great-thanksgiving"), ("lords-prayer", "lords-prayer"),
                ("communion", "communion"), ("sending", "sending")]
    variant = liturgy.get("service_variant")
    variant = variant if isinstance(variant, dict) else {}
    replacements = {item.get("unit"): item.get("with", [])
                    for item in variant.get("replace", []) if isinstance(item, dict)}
    def identifiers(values: Any) -> list[str]:
        if not isinstance(values, list):
            values = [values]
        return [str(value.get("unit") or value.get("file") or value.get("id") or "")
                if isinstance(value, dict) else str(value or "") for value in values]
    required = []
    for anchor, default in sections:
        required.extend(identifiers(replacements.get(anchor, [default])))
        for item in variant.get("insert", []):
            if isinstance(item, dict) and item.get("after") == anchor:
                required.extend(identifiers(item.get("units", [])))
    return list(dict.fromkeys(value for value in required if value))


def _source_readiness(
    profile: dict[str, Any],
    pack: dict[str, Any],
    liturgy: dict[str, Any],
    *,
    church_root: Path | None,
    plugin_root: Path | None,
    weekly_source_keys: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    """Find selected worship text with no shipped or confirmed private source."""
    shipped = pack.get("shipped_sources")
    service_plan = str(liturgy.get("service_plan", "")).strip()
    if service_plan == "lutheran-holy-communion" and church_root is not None:
        files = liturgy.get("files", {})
        files = files if isinstance(files, dict) else {}
        required_units = required_lutheran_units(liturgy)
        unresolved: list[dict[str, str]] = []
        for identifier in required_units:
            raw = files.get(identifier)
            if raw is None:
                unresolved.append({
                    "field": f"liturgy.files.{identifier}",
                    "reason": f"Provide the church-owned Lutheran source file for {identifier} under worship/liturgy/",
                })
                continue
            ok, reason = _private_source_status(raw, choice=identifier, church_root=church_root, field=f"liturgy.files.{identifier}")
            if not ok:
                unresolved.append({
                    "field": f"liturgy.files.{identifier}",
                    "reason": reason or f"Provide the church-owned Lutheran source file for {identifier} under worship/liturgy/",
                })
        return unresolved
    if not isinstance(shipped, dict):
        # Older synthetic packs and Lutheran packs rely on their existing
        # private-file contract. Keep this pure seam backward compatible.
        return []
    plugin = plugin_root or _plugin_root()
    profile_sources = profile.get("sources", {})
    if not isinstance(profile_sources, dict):
        profile_sources = {}
    weekly_sources = liturgy.get("sources", {})
    if not isinstance(weekly_sources, dict):
        weekly_sources = {}
    unresolved: list[dict[str, str]] = []
    for key in SOURCE_CHOICE_KEYS:
        choice = str(liturgy.get(key, "")).strip()
        if not choice:
            if key == "prayers_of_the_people":
                choices = pack.get("choices", {})
                if (
                    isinstance(choices, dict)
                    and key in choices
                    and service_plan == "episcopal-rite-ii"
                ):
                    unresolved.append({
                        "field": f"liturgy.{key}",
                        "reason": "Confirm a Prayers of the People form before producing",
                    })
            continue
        shipped_choice = choice
        if key == "eucharistic_prayer" and choice in ("A", "B", "C", "D") and liturgy.get("print_full_eucharistic_prayer"):
            shipped_choice = f"{choice}_full"
        shipped_id = _shipped_source(pack, key, shipped_choice)
        raw = weekly_sources.get(key) if key in weekly_sources else profile_sources.get(key)
        if isinstance(raw, str) and not raw.strip():
            raw = None
        field = f"liturgy.sources.{key}"
        if raw is not None:
            raw_text = str(raw).strip() if isinstance(raw, str) else ""
            if shipped_id and raw_text == shipped_id:
                source_path = plugin / "skills" / "bulletin" / "renderer" / "liturgy" / f"{shipped_id}.md"
                if source_path.is_file():
                    from .sunday_library import SundayLibraryError, verify_shipped_liturgy
                    try:
                        verify_shipped_liturgy(shipped_id, plugin_root=plugin)
                    except SundayLibraryError as exc:
                        unresolved.append({"field": f"liturgy.{key}", "reason": str(exc)})
                    continue
            if key in profile_sources and key not in weekly_source_keys and str(profile.get("status", "")).strip().lower() != "confirmed":
                ok, reason = False, "Confirm the church-owned liturgy source in the worship profile before producing"
            else:
                ok, reason = _private_source_status(raw, choice=choice, church_root=church_root, field=field)
            if ok:
                continue
        elif shipped_id:
            source_path = plugin / "skills" / "bulletin" / "renderer" / "liturgy" / f"{shipped_id}.md"
            if source_path.is_file():
                from .sunday_library import SundayLibraryError, verify_shipped_liturgy
                try:
                    verify_shipped_liturgy(shipped_id, plugin_root=plugin)
                except SundayLibraryError as exc:
                    unresolved.append({"field": f"liturgy.{key}", "reason": str(exc)})
                continue
            reason = None
        else:
            reason = None
        if reason is None:
            reason = (
                f"No shipped text is available for {key.replace('_', ' ')} {choice}. "
                "The agent should first check the bundled catalog and retrieve a permitted official source. "
                "Ask the pastor only for a local variation or licensed church material that cannot be obtained."
            )
        unresolved.append({"field": f"liturgy.{key}", "reason": reason})
    return unresolved


def _safe_church_path(root: Path, relative: Any, *, field: str) -> Path:
    """Resolve a church-relative path without allowing folder escape."""
    value = str(relative or "").strip()
    if not value:
        raise WorshipResolutionError("variant_missing", f"Choose a church-owned order file for {field}", field=field)
    candidate = Path(value)
    if candidate.is_absolute():
        raise WorshipResolutionError("unsafe_path", f"{field} must be relative to the church folder", field=field)
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise WorshipResolutionError("unsafe_path", f"{field} must stay inside the church folder", field=field) from exc
    return resolved


def _operation_list(value: Any, key: str, *, file_path: Path) -> list[dict[str, Any]]:
    """Accept the JSON order contract and a small YAML-friendly shorthand."""
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        if "unit" in value or "anchor" in value or "after" in value:
            value = [value]
        else:
            value = [
                {"unit": anchor, "with": units} if key == "replace" else {"after": anchor, "units": units}
                for anchor, units in value.items()
            ]
    if not isinstance(value, list):
        raise WorshipResolutionError("variant_invalid", f"{key} in {file_path} must be a list or mapping")
    normalized: list[dict[str, Any]] = []
    for index, operation in enumerate(value):
        if not isinstance(operation, dict):
            raise WorshipResolutionError(
                "variant_invalid", f"{key}[{index}] in {file_path} must be a mapping"
            )
        if key == "replace":
            anchor = operation.get("unit", operation.get("anchor"))
            replacement = operation.get("with", operation.get("steps"))
            if not str(anchor or "").strip() or not isinstance(replacement, list):
                raise WorshipResolutionError(
                    "variant_invalid",
                    f"{key}[{index}] in {file_path} needs an anchor and a list of replacement units",
                )
            normalized.append({"unit": str(anchor), "with": copy.deepcopy(replacement)})
        else:
            anchor = operation.get("after", operation.get("anchor"))
            inserted = operation.get("units", operation.get("steps"))
            if not str(anchor or "").strip() or not isinstance(inserted, list):
                raise WorshipResolutionError(
                    "variant_invalid",
                    f"{key}[{index}] in {file_path} needs an anchor and a list of inserted units",
                )
            normalized.append({"after": str(anchor), "units": copy.deepcopy(inserted)})
    return normalized


def _source_files(value: Any, *, file_path: Path, church_root: Path) -> dict[str, str]:
    """Validate logical-unit source paths and return church-relative paths."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise WorshipResolutionError("variant_invalid", f"files in {file_path} must be a mapping")
    resolved: dict[str, str] = {}
    for logical_unit, raw_path in value.items():
        key = str(logical_unit).strip()
        if not key or not str(raw_path or "").strip():
            raise WorshipResolutionError("variant_invalid", f"files in {file_path} needs unit names and paths")
        candidate = _safe_church_path(church_root, raw_path, field=f"liturgy.files.{key}")
        if not candidate.is_file():
            raise WorshipResolutionError(
                "variant_missing", f"Private source file was not found for {key!r}: {raw_path}", field=VARIANT_FIELD
            )
        resolved[key] = candidate.relative_to(church_root.resolve()).as_posix()
    return resolved


def _merge_operations(chain: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]] | dict[str, str]]:
    """Merge base order operations first, with child operations last."""
    replace: list[dict[str, Any]] = []
    insert: list[dict[str, Any]] = []
    files: dict[str, str] = {}
    for data in chain:
        for operation in data.get("replace", []):
            replace = [item for item in replace if item["unit"] != operation["unit"]]
            replace.append(copy.deepcopy(operation))
        for operation in data.get("insert", []):
            matching = next((item for item in insert if item["after"] == operation["after"]), None)
            if matching is None:
                insert.append(copy.deepcopy(operation))
            else:
                matching["units"].extend(copy.deepcopy(operation["units"]))
        files.update(copy.deepcopy(data.get("files", {})))
    return {"replace": replace, "insert": insert, "files": files}


def _validate_anchors(order: dict[str, Any], service_plan: str, file_path: Path) -> None:
    anchors = SERVICE_PLAN_ANCHORS.get(service_plan)
    if anchors is None:
        raise WorshipResolutionError(
            "variant_invalid", f"No supported service-plan anchors are registered for {service_plan!r} in {file_path}", field=VARIANT_FIELD
        )
    for operation in order.get("replace", []):
        if operation["unit"] not in anchors:
            raise WorshipResolutionError(
                "variant_invalid",
                f"Unknown replace anchor {operation['unit']!r} for {service_plan!r} in {file_path}",
                field=VARIANT_FIELD,
            )
    for operation in order.get("insert", []):
        if operation["after"] not in anchors:
            raise WorshipResolutionError(
                "variant_invalid",
                f"Unknown insert anchor {operation['after']!r} for {service_plan!r} in {file_path}",
                field=VARIANT_FIELD,
            )


def _variant_confirmation(entry: dict[str, Any]) -> Any:
    for key in ("confirmation_policy", "confirmation", "policy"):
        if key in entry:
            return copy.deepcopy(entry[key])
    return None


def _resolve_variant(
    profile: dict[str, Any],
    variant_id: str,
    church_root: Path,
    service_plan: str,
) -> dict[str, Any]:
    variants = profile.get("service_variants", {})
    if not isinstance(variants, dict):
        raise WorshipResolutionError(
            "variant_invalid", "worship.profile.yaml service_variants must be a mapping", field=VARIANT_FIELD
        )
    chain: list[dict[str, Any]] = []
    visited: list[str] = []

    def visit(current_id: str) -> None:
        if current_id in visited:
            cycle = " -> ".join([*visited, current_id])
            raise WorshipResolutionError("variant_cycle", f"Service variant extends cyclically: {cycle}", field=VARIANT_FIELD)
        entry = variants.get(current_id)
        if not isinstance(entry, dict):
            raise WorshipResolutionError(
                "variant_unknown", f"Unknown service variant {current_id!r}. Choose a configured variant.", field=VARIANT_FIELD
            )
        required = {"name", "base_service_plan", "order_file"}
        missing = [key for key in required if not str(entry.get(key, "")).strip()]
        if missing:
            raise WorshipResolutionError(
                "variant_invalid",
                f"Service variant {current_id!r} is missing: {', '.join(missing)}",
                field=VARIANT_FIELD,
            )
        if _variant_confirmation(entry) is None:
            raise WorshipResolutionError(
                "variant_invalid",
                f"Service variant {current_id!r} needs a confirmation policy such as ask_each_week or scheduled",
                field=VARIANT_FIELD,
            )
        entry_plan = str(entry["base_service_plan"]).strip()
        if entry_plan != service_plan:
            raise WorshipResolutionError(
                "variant_service_plan_mismatch",
                f"Service variant {current_id!r} uses base service plan {entry_plan!r}, but the resolved plan is {service_plan!r}",
                field=VARIANT_FIELD,
            )
        visited.append(current_id)
        path = _safe_church_path(church_root, entry["order_file"], field=f"service_variants.{current_id}.order_file")
        order = load_yaml(path)
        for key in ("extends", "replace", "insert"):
            if key in order and key != "extends" and order[key] is not None:
                # Validate while the file path is available for useful errors.
                order[key] = _operation_list(order[key], key, file_path=path)
        _validate_anchors(order, service_plan, path)
        order["files"] = _source_files(order.get("files"), file_path=path, church_root=church_root)
        entry_files = _source_files(entry.get("files"), file_path=path, church_root=church_root)
        if entry_files:
            order["files"].update(entry_files)
        parent = order.get("extends")
        if parent in (None, ""):
            parent = entry.get("extends")
        if isinstance(parent, list):
            if len(parent) != 1:
                raise WorshipResolutionError(
                    "variant_invalid", f"Service variant {current_id!r} may extend one configured variant at a time", field=VARIANT_FIELD
                )
            parent = parent[0]
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            raise WorshipResolutionError(
                "variant_invalid", f"Service variant {current_id!r} has an invalid extends value", field=VARIANT_FIELD
            )
        if parent:
            if parent not in variants:
                raise WorshipResolutionError(
                    "variant_unknown", f"Service variant {current_id!r} extends unknown variant {parent!r}", field=VARIANT_FIELD
                )
            visit(parent)
        chain.append({
            "id": current_id,
            "entry": entry,
            "order": order,
            "order_file": path.relative_to(church_root.resolve()).as_posix(),
        })
        visited.pop()

    visit(variant_id)
    operations = _merge_operations([item["order"] for item in chain])
    selected = chain[-1]
    entry = selected["entry"]
    return {
        "id": variant_id,
        "name": str(entry["name"]).strip(),
        "base_service_plan": str(entry["base_service_plan"]).strip(),
        "replace": operations["replace"],
        "insert": operations["insert"],
        "files": operations["files"],
        "confirmation_policy": _variant_confirmation(entry),
        "order_file_chain": [item["order_file"] for item in chain],
    }


def resolve_profile_data(
    profile: dict[str, Any],
    pack: dict[str, Any],
    weekly: dict[str, Any] | None = None,
    *,
    profile_ref: str = PROFILE_NAME,
    church_root: str | Path | None = None,
    plugin_root: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve already-loaded profile and pack data.

    This pure function is the testable seam. File loading is kept in the
    wrapper below so the merge and validation rules do not depend on a host.
    """
    weekly = weekly or {}
    profile_defaults = profile.get("defaults", {})
    weekly_liturgy = weekly.get("liturgy", {})
    if not isinstance(profile_defaults, dict) or not isinstance(weekly_liturgy, dict):
        raise WorshipResolutionError("profile_invalid", "Profile defaults and weekly liturgy must be mappings")

    liturgy = copy.deepcopy(profile_defaults)
    liturgy.update(copy.deepcopy(weekly_liturgy))
    # These defaults preserve the two-lesson practice for existing profiles.
    # Keep the resolved values explicit so production never infers an omission
    # from missing reading data.
    for key in READING_DISPLAY_CHOICES:
        liturgy.setdefault(key, True)
    if not str(liturgy.get("blessing", "")).strip():
        liturgy["blessing"] = GENERAL_BLESSING
    unresolved: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    for key in READING_DISPLAY_CHOICES:
        if not isinstance(liturgy[key], bool):
            invalid.append({"field": f"liturgy.{key}", "value": liturgy[key]})
    if not liturgy["include_first_reading"] and not liturgy["include_second_reading"]:
        raise WorshipResolutionError(
            "invalid_reading_selection",
            "At least one non-Gospel reading must be included",
            field="liturgy.include_first_reading",
        )
    if "psalm_format" in liturgy and not str(liturgy.get("psalm_format") or "").strip():
        unresolved.append({"field": "liturgy.psalm_format", "reason": "Confirm whether the psalm uses half-verse responses, whole-verse responses, unison, or plain text."})
    choice_keys = [*REQUIRED_CHOICES, "blessing"]
    for key in choice_keys:
        value = str(liturgy.get(key, "")).strip()
        if not value:
            unresolved.append({"field": f"liturgy.{key}", "reason": "pastoral choice required"})
            continue
        if key == "blessing" and value.lower() == "omit":
            continue
        allowed = _choice_values(pack, key)
        if allowed and value not in allowed:
            invalid.append({"field": f"liturgy.{key}", "value": value})
    if invalid:
        raise WorshipResolutionError(
            "unsupported_choice",
            "A worship choice is not supported by the selected tradition pack",
            field=invalid[0]["field"],
        )

    tradition = profile.get("tradition", {})
    if not isinstance(tradition, dict):
        tradition = {}
    service_plan = weekly.get("service_plan") or pack.get("service_plan", "episcopal-rite-ii")
    liturgy["service_plan"] = service_plan
    liturgy["worship_profile_ref"] = profile_ref
    profile_sources = profile.get("sources", {})
    weekly_sources = weekly_liturgy.get("sources", {})
    if not isinstance(profile_sources, dict) or not isinstance(weekly_sources, dict):
        raise WorshipResolutionError("profile_invalid", "Profile and weekly worship sources must be mappings")
    sources = {
        str(key): copy.deepcopy(value)
        for key, value in profile_sources.items()
        if str(value or "").strip()
    }
    sources.update({
        str(key): copy.deepcopy(value)
        for key, value in weekly_sources.items()
        if str(value or "").strip()
    })
    if liturgy.get("doxology", "traditional") != "custom":
        sources.pop("doxology", None)
    liturgy["sources"] = sources
    if service_plan == "lutheran-holy-communion":
        local_files = {key: copy.deepcopy(sources[key]) for key in
                       ("gathering", "prayers", "great-thanksgiving", "lords-prayer", "communion", "sending")
                       if key in sources}
        weekly_files = weekly_liturgy.get("files", {})
        if not isinstance(weekly_files, dict):
            raise WorshipResolutionError("profile_invalid", "Weekly liturgy files must be a mapping")
        local_files.update(copy.deepcopy(weekly_files))
        liturgy["files"] = local_files
    for key in EXPLICIT_PRINT_CHOICES if service_plan == "episcopal-rite-ii" else ():
        if key in liturgy and liturgy[key] is None:
            unresolved.append({
                "field": f"liturgy.{key}",
                "reason": "Confirm whether this part of the service should be printed",
            })
    resolved_church_root = Path(church_root).expanduser().resolve() if church_root is not None else None
    resolved_plugin_root = Path(plugin_root).expanduser().resolve() if plugin_root is not None else None
    variant_unresolved: list[dict[str, str]] = []
    service = weekly.get("service", {})
    variant_id = service.get("variant") if isinstance(service, dict) else None
    variants = profile.get("service_variants", {})
    if variants not in ({}, None) and not isinstance(variants, dict):
        variant_unresolved.append({"field": VARIANT_FIELD, "reason": "service_variants must be a mapping"})
    elif isinstance(variants, dict) and variants:
        if not str(variant_id or "").strip():
            configured = ", ".join(sorted(str(key) for key in variants))
            variant_unresolved.append({
                "field": VARIANT_FIELD,
                "reason": f"Confirm the service variant for this week. Configured choices: {configured}",
            })
        elif str(variant_id).strip().lower() == "none":
            liturgy["service_variant"] = {
                "id": "none",
                "name": "Ordinary service",
                "base_service_plan": str(service_plan),
                "replace": [],
                "insert": [],
            }
            liturgy["service_variant_provenance"] = {
                "variant_id": "none",
                "order_file_chain": [],
                "confirmation_policy": "explicit_none",
            }
        elif church_root is None:
            variant_unresolved.append({
                "field": VARIANT_FIELD,
                "reason": "A church folder is required to load the private service order file",
            })
        else:
            try:
                resolved_variant = _resolve_variant(
                    profile, str(variant_id).strip(), Path(church_root).expanduser().resolve(), str(service_plan)
                )
                liturgy["service_variant"] = {
                    key: value
                    for key, value in resolved_variant.items()
                    if key not in {"files", "confirmation_policy", "order_file_chain"}
                }
                liturgy["service_variant_provenance"] = {
                    "variant_id": resolved_variant["id"],
                    "order_file_chain": resolved_variant["order_file_chain"],
                    "confirmation_policy": resolved_variant["confirmation_policy"],
                }
                variant_files = resolved_variant.get("files", {})
                if variant_files:
                    existing_files = liturgy.get("files", {})
                    if not isinstance(existing_files, dict):
                        existing_files = {}
                    existing_files = copy.deepcopy(existing_files)
                    existing_files.update(copy.deepcopy(variant_files))
                    liturgy["files"] = existing_files
            except WorshipResolutionError as exc:
                # Keep the pastor-facing question stable even when the detail
                # names an order-file or source-file subfield.
                variant_unresolved.append({"field": VARIANT_FIELD, "reason": exc.message})
    unresolved.extend(_source_readiness(
        profile,
        pack,
        liturgy,
        church_root=resolved_church_root,
        plugin_root=resolved_plugin_root,
        weekly_source_keys=frozenset(key for key, value in weekly_sources.items() if str(value or "").strip()),
    ))
    if liturgy.get("doxology") == "custom" and not (sources.get("doxology") or (liturgy.get("files") or {}).get("doxology")):
        unresolved.append({"field": "liturgy.sources.doxology", "reason": "Provide and verify the church's custom doxology text."})
    if liturgy.get("doxology", "traditional") != "custom" and isinstance(liturgy.get("files"), dict):
        liturgy["files"].pop("doxology", None)
    if resolved_church_root is not None:
        from .bulletin_production.interface import _source_is_shipped
        known = {item["field"] for item in unresolved}
        for group_name in ("sources", "files"):
            for key, raw in (liturgy.get(group_name) or {}).items():
                field = f"liturgy.{group_name}.{key}"
                if field in known or _source_is_shipped(raw, resolved_church_root):
                    continue
                ok, reason = _private_source_status(raw, choice=key, church_root=resolved_church_root, field=field)
                if not ok:
                    unresolved.append({"field": field, "reason": reason or "Provide a verified private worship text."})
    result = {
        "schema_version": 1,
        "worship_profile_ref": profile_ref,
        "profile_status": profile.get("status", "needs_onboarding"),
        "tradition_pack": profile.get("tradition_pack", pack.get("id", "")),
        "tradition": {
            "family": tradition.get("family", pack.get("family", "")),
            "denomination": tradition.get("denomination", pack.get("denomination", "")),
            "service_book": tradition.get("service_book", pack.get("service_book", "")),
            "rite_or_setting": tradition.get("rite", pack.get("rite", "")),
        },
        "service_plan": service_plan,
        "liturgy": liturgy,
        "source_references": copy.deepcopy(profile.get("sources", {})),
        "provenance": {
            "profile": profile.get("provenance", {}),
            "weekly_override_supplied": bool(weekly_liturgy),
        },
        "unresolved": [*unresolved, *variant_unresolved],
    }
    result["status"] = "needs_input" if result["unresolved"] else "resolved"
    return result


def resolve_worship_profile(
    church_folder: str | Path,
    weekly: dict[str, Any] | None = None,
    *,
    plugin_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load and resolve the church profile and its tradition pack."""
    profile_path, profile_ref = _profile_path(church_folder)
    profile = load_yaml(profile_path)
    pack_id = str(profile.get("tradition_pack", "")).strip()
    if not pack_id:
        raise WorshipResolutionError("tradition_pack_unresolved", "Choose a tradition pack during onboarding", field="tradition_pack")
    pack = load_yaml(_pack_path(pack_id, Path(plugin_root) if plugin_root else _plugin_root()))
    return resolve_profile_data(
        profile,
        pack,
        weekly,
        profile_ref=profile_ref,
        church_root=Path(church_folder),
        plugin_root=plugin_root,
    )


def as_error(exc: WorshipResolutionError) -> dict[str, Any]:
    error = {"code": exc.code, "message": exc.message}
    if exc.field:
        error["field"] = exc.field
    status = "needs_input" if exc.code == "tradition_pack_unresolved" else "blocked"
    return {"status": status, "errors": [error]}
