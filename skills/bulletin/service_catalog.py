"""Declarative recurring-service catalog validation and selection.

The catalog deliberately contains references and choices only.  It never
loads executable material or resolves a source outside the church folder.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any


CATALOG_VERSION = 1
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
OPTIONAL_UNITS = frozenset({
    "nicene-creed", "confession-of-sin", "doxology", "blessing", "communion_welcome",
})
DEFAULT_UNITS = frozenset({
    "opening-acclamation", "collect-for-purity", "collect-of-day", "nicene-creed",
    "prayers-of-the-people", "confession-of-sin", "peace", "doxology",
    "eucharistic-prayer", "lords-prayer", "breaking-of-bread", "post-communion-prayer",
    "dismissal", "gathering", "word", "creed", "prayers", "meal", "great-thanksgiving", "communion", "sending",
}) | OPTIONAL_UNITS
KNOWN_DEFAULTS = frozenset({
    "eucharistic_prayer", "lords_prayer", "prayers_of_the_people", "doxology",
    "closing_hymn_position", "gospel_acclamation", "psalm_format", "psalm_response_start",
    "prayer_presentation", "rubric_style", "service_setting", "divine_service_setting",
    "include_creed", "include_confession", "print_full_eucharistic_prayer",
    "include_first_reading", "include_second_reading", "blessing", "communion_welcome",
})
KNOWN_SOURCES = frozenset({
    "eucharistic_prayer", "lords_prayer", "prayers_of_the_people", "gathering", "prayers",
    "great-thanksgiving", "lords-prayer", "communion", "sending", "doxology", "blessing",
    "communion_welcome",
})
SOURCE_UNIT_ALIASES = {
    "eucharistic_prayer": "eucharistic-prayer",
    "lords_prayer": "lords-prayer",
    "prayers_of_the_people": "prayers-of-the-people",
}
_SERVICE_FIELDS = frozenset({
    "name", "service_plan", "defaults", "sources", "files", "part_selections",
    "default_variant", "time", "display_name",
})
_PART_FIELDS = frozenset({"name", "unit", "file", "description"})


class ServiceCatalogError(ValueError):
    """A catalog record is not safe or complete enough to resolve."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def _error(code: str, message: str, field: str) -> None:
    raise ServiceCatalogError(code, message, field=field)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error("catalog_invalid", f"{field} must be a mapping", field)
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        _error("catalog_invalid_id", f"{field} must use a stable lowercase identifier", field)
    identifier = value
    if not ID_RE.fullmatch(identifier):
        _error("catalog_invalid_id", f"{field} must use a stable lowercase identifier", field)
    return identifier


def _relative_path(value: Any, field: str, church_root: Path | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        _error("catalog_invalid", f"{field} needs a church-relative source file", field)
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        _error("unsafe_path", f"{field} must stay inside the church folder", field)
    if church_root is None:
        return path.as_posix()
    candidate = (church_root / path).resolve()
    try:
        candidate.relative_to(church_root)
    except ValueError:
        _error("unsafe_path", f"{field} must stay inside the church folder", field)
    if not candidate.is_file():
        _error("catalog_missing_source", f"Source file was not found for {field}: {raw}", field)
    from .liturgy_sources import LiturgySourceError, require_verified_source
    try:
        require_verified_source(church_root, candidate)
    except LiturgySourceError as exc:
        _error("catalog_unverified_source", str(exc), field)
    return candidate.relative_to(church_root).as_posix()


def _validate_layer(layer: dict[str, Any], field: str, *, allowed_units: set[str], church_root: Path | None,
                    parts: dict[str, dict[str, Any]]) -> None:
    for key in ("defaults", "sources", "files", "part_selections"):
        if key in layer and not isinstance(layer[key], dict):
            _error("catalog_invalid", f"{field}.{key} must be a mapping", f"{field}.{key}")
    files = layer.get("files", {})
    sources = layer.get("sources", {})
    selections = layer.get("part_selections", {})
    for key in layer.get("defaults", {}):
        if str(key) not in KNOWN_DEFAULTS:
            _error("catalog_unknown_default", f"{field}.defaults.{key} is not a supported worship choice", f"{field}.defaults.{key}")
        value = layer["defaults"][key]
        if value is not None and not isinstance(value, (str, bool)):
            _error("catalog_invalid", f"{field}.defaults.{key} must be a string, boolean, or null", f"{field}.defaults.{key}")
    for unit, raw in files.items():
        unit = str(unit)
        if unit in selections:
            _error("catalog_layer_conflict", f"{field} names both a direct source and a selected part for {unit}", field)
        _relative_path(raw, f"{field}.{unit}", church_root)
    for unit, raw in sources.items():
        unit = str(unit)
        if unit not in KNOWN_SOURCES:
            _error("catalog_unknown_source", f"{field}.sources.{unit} is not a supported worship source", f"{field}.sources.{unit}")
        if SOURCE_UNIT_ALIASES.get(unit, unit) in selections:
            _error("catalog_layer_conflict", f"{field} names both a direct source and a selected part for {unit}", field)
        if not isinstance(raw, str) or not raw.strip():
            _error("catalog_invalid", f"{field}.sources.{unit} must be a nonblank source identifier or path", f"{field}.sources.{unit}")
        # Shipped source identifiers are not files.  Private references are
        # validated by the common source-readiness pass after precedence.
        if Path(raw).is_absolute() or ".." in Path(raw).parts:
            _error("unsafe_path", f"{field}.sources.{unit} must stay inside the church folder", f"{field}.sources.{unit}")
    for raw_unit, selected in selections.items():
        unit = str(raw_unit)
        selection_field = f"{field}.part_selections.{unit}"
        if unit not in allowed_units:
            _error("catalog_unknown_unit", f"{selection_field} is not a supported service-plan unit", selection_field)
        if selected is None:
            continue
        if selected == "omit":
            if unit not in OPTIONAL_UNITS:
                _error("catalog_required_unit", f"{unit} is required and cannot be omitted", selection_field)
            continue
        part_id = _identifier(selected, selection_field)
        part = parts.get(part_id)
        if part is None:
            _error("catalog_unknown_part", f"{selection_field} names an unknown part {part_id!r}", selection_field)
        if part["unit"] != unit:
            _error("catalog_part_unit_mismatch", f"Part {part_id!r} is for {part['unit']!r}, not {unit!r}", selection_field)


def validate_catalog(profile: dict[str, Any], *, church_root: str | Path | None = None,
                     allowed_units: set[str] | None = None) -> dict[str, Any] | None:
    """Validate and normalize an optional catalog without writing church data.

    Pass ``church_root`` for source existence and sidecar verification.  The
    returned value is a safe copy suitable for a settings writer or resolver.
    """
    raw = profile.get("catalog")
    if raw is None:
        return None
    catalog = _mapping(raw, "catalog")
    if set(catalog) - {"schema_version", "default_service", "legacy_service", "services", "parts", "part_selections"}:
        _error("catalog_invalid", "catalog contains an unsupported field", "catalog")
    if catalog.get("schema_version") != CATALOG_VERSION:
        _error("catalog_version", "catalog.schema_version must be 1", "catalog.schema_version")
    root = Path(church_root).expanduser().resolve() if church_root is not None else None
    units = set(allowed_units or DEFAULT_UNITS) | set(OPTIONAL_UNITS)
    services_raw = _mapping(catalog.get("services", {}), "catalog.services")
    parts_raw = _mapping(catalog.get("parts", {}), "catalog.parts")
    parts: dict[str, dict[str, Any]] = {}
    for raw_id, entry in parts_raw.items():
        part_id = _identifier(raw_id, f"catalog.parts.{raw_id}")
        value = _mapping(entry, f"catalog.parts.{part_id}")
        if set(value) - _PART_FIELDS:
            _error("catalog_invalid", f"catalog.parts.{part_id} contains an unsupported field", f"catalog.parts.{part_id}")
        for required in ("name", "unit", "file"):
            if not isinstance(value.get(required), str) or not value[required].strip():
                _error("catalog_invalid", f"catalog.parts.{part_id}.{required} is required", f"catalog.parts.{part_id}.{required}")
        unit = str(value["unit"]).strip()
        if unit not in units:
            _error("catalog_unknown_unit", f"catalog.parts.{part_id}.unit is not a supported service-plan unit", f"catalog.parts.{part_id}.unit")
        parts[part_id] = {**copy.deepcopy(value), "unit": unit,
                          "file": _relative_path(value["file"], f"catalog.parts.{part_id}.file", root)}
    for raw_id, entry in services_raw.items():
        service_id = _identifier(raw_id, f"catalog.services.{raw_id}")
        value = _mapping(entry, f"catalog.services.{service_id}")
        if set(value) - _SERVICE_FIELDS:
            _error("catalog_invalid", f"catalog.services.{service_id} contains an unsupported field", f"catalog.services.{service_id}")
        if not isinstance(value.get("name"), str) or not value["name"].strip():
            _error("catalog_invalid", f"catalog.services.{service_id}.name is required", f"catalog.services.{service_id}.name")
        if "default_variant" in value and value["default_variant"] is not None:
            _identifier(value["default_variant"], f"catalog.services.{service_id}.default_variant")
        for key in ("service_plan", "time", "display_name"):
            if key in value and (not isinstance(value[key], str) or not value[key].strip()):
                _error("catalog_invalid", f"catalog.services.{service_id}.{key} must be a nonblank string", f"catalog.services.{service_id}.{key}")
        _validate_layer(value, f"catalog.services.{service_id}", allowed_units=units, church_root=root, parts=parts)
    profile_sources = profile.get("sources", {})
    if not isinstance(profile_sources, dict):
        _error("catalog_invalid", "sources must be a mapping", "sources")
    # Existing profiles use blank source placeholders during onboarding. They
    # do not select direct text and remain valid when a catalog is added.
    top = {"part_selections": catalog.get("part_selections", {}),
           "files": profile.get("files", {}),
           "sources": {key: value for key, value in profile_sources.items() if str(value or "").strip()}}
    _validate_layer(top, "catalog", allowed_units=units, church_root=root, parts=parts)
    default_service = catalog.get("default_service")
    if default_service is not None:
        default_service = _identifier(default_service, "catalog.default_service")
        if default_service not in services_raw:
            _error("catalog_unknown_service", "catalog.default_service must name a configured service", "catalog.default_service")
    legacy_service = catalog.get("legacy_service")
    if legacy_service is not None:
        legacy_service = _identifier(legacy_service, "catalog.legacy_service")
        if legacy_service not in services_raw:
            _error("catalog_unknown_service", "catalog.legacy_service must name a configured service", "catalog.legacy_service")
    variants = profile.get("service_variants", {})
    if variants not in ({}, None) and not isinstance(variants, dict):
        _error("catalog_invalid", "service_variants must be a mapping", "service_variants")
    if isinstance(variants, dict):
        for variant_id, variant in variants.items():
            variant_id = _identifier(variant_id, f"service_variants.{variant_id}")
            value = _mapping(variant, f"service_variants.{variant_id}")
            _validate_layer(value, f"service_variants.{variant_id}", allowed_units=units, church_root=root, parts=parts)
            service_ids = value.get("service_ids")
            if service_ids is not None:
                if not isinstance(service_ids, list):
                    _error("catalog_invalid", f"service_variants.{variant_id}.service_ids must be a list", f"service_variants.{variant_id}.service_ids")
                for index, service_id in enumerate(service_ids):
                    service_id = _identifier(service_id, f"service_variants.{variant_id}.service_ids.{index}")
                    if service_id not in services_raw:
                        _error("catalog_unknown_service", f"service_variants.{variant_id} names unknown service {service_id!r}", f"service_variants.{variant_id}.service_ids.{index}")
    for service_id, service in services_raw.items():
        default_variant = service.get("default_variant") if isinstance(service, dict) else None
        if default_variant not in (None, "none") and default_variant not in (variants or {}):
            _error("catalog_unknown_variant", f"catalog.services.{service_id}.default_variant must name a configured variant", f"catalog.services.{service_id}.default_variant")
    return {**copy.deepcopy(catalog), "default_service": default_service,
            "legacy_service": legacy_service, "parts": parts}


def resolve_catalog(profile: dict[str, Any], weekly: dict[str, Any], *, allowed_units: set[str],
                    church_root: str | Path | None = None) -> dict[str, Any]:
    """Select a recurring service and retain scope layers for the resolver."""
    catalog = validate_catalog(profile, church_root=church_root, allowed_units=allowed_units)
    service_input = weekly.get("service", {})
    if service_input is None:
        service_input = {}
    if not isinstance(service_input, dict):
        _error("catalog_invalid", "service must be a mapping", "service")
    occurrence = service_input.get("occurrence_id", "main")
    occurrence_id = _identifier(occurrence, "service.occurrence_id")
    if catalog is None:
        requested = service_input.get("service_id")
        if requested is not None:
            requested = _identifier(requested, "service.service_id")
            if requested != "ordinary":
                _error("catalog_unknown_service", f"Legacy worship profiles support only the ordinary service, not {requested!r}", "service.service_id")
        return {"legacy": True, "service": {}, "service_id": "ordinary", "occurrence_id": occurrence_id,
                "catalog_version": None, "service_context": {"service_id": "ordinary", "name": "Ordinary service",
                "occurrence_id": occurrence_id, "catalog_version": None, "legacy": True}}
    requested = service_input.get("service_id")
    if requested is None:
        requested = catalog.get("default_service")
    if requested is None:
        return {"legacy": False, "service": {}, "service_id": None, "occurrence_id": occurrence_id,
                "catalog_version": CATALOG_VERSION, "service_context": None,
                "unresolved": {"field": "service.service_id", "reason": "Choose the recurring service for this bulletin."}}
    service_id = _identifier(requested, "service.service_id")
    services = catalog["services"]
    if service_id not in services:
        _error("catalog_unknown_service", f"Unknown recurring service {service_id!r}", "service.service_id")
    service = copy.deepcopy(services[service_id])
    context = {"service_id": service_id, "name": service["name"], "occurrence_id": occurrence_id,
               "catalog_version": CATALOG_VERSION, "legacy": False,
               "inherits_legacy_history": service_id == catalog.get("legacy_service") and occurrence_id == "main"}
    for key in ("time", "display_name"):
        if key in service:
            context[key] = service[key]
    return {"legacy": False, "service": service, "service_id": service_id, "occurrence_id": occurrence_id,
            "catalog_version": CATALOG_VERSION, "catalog": catalog,
            "service_context": context}
