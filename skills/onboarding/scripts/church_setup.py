#!/usr/bin/env python3
"""Small, deterministic writer and status reader for a private church folder.

Onboarding is conversational, but its writes are deliberately boring.  This
module owns only the profile values that the shipped workflows consume.  It
does not write weekly bulletin inputs, approved history, sermon files, or
brand assets.  Those remain the responsibility of their own workflows.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


REQUIRED_FILES = ("AGENTS.md", "CLAUDE.md", "START-HERE.md", "ONBOARDING.md", "church.yaml", "brand.json")
PROFILE_DEFAULT = "worship/profile.yaml"
_SCALAR_SECTIONS = {
    "church": {"name", "short_name", "tradition", "city", "address", "website", "regular_services"},
    "leadership": {"print_in_bulletin", "clergy_and_staff", "governing_body"},
    "bulletin": {"include_serving_today", "serving_roles", "footer", "template"},
    "lectionary": {"system", "track", "translation", "optional_verses", "authorities"},
    "sermon": {"selection_mode", "primary_text", "research_preferences"},
    "people": {"pastor"},
    "worship_profile": set(),
}
_LEADERSHIP_FIELDS = {"print_in_bulletin", "clergy_and_staff", "governing_body", "placement"}
_LEADERSHIP_PLACEMENT_CHOICES = {"auto", "footer", "body"}
_GOVERNING_FIELDS = {"label", "member_label", "officers", "members"}
_BULLETIN_FIELDS = {"include_serving_today", "serving_roles", "footer", "template", "doxology_music", "parish_information"}
_FOOTER_FIELDS = {"contact_name", "address", "phone", "email", "website"}
_PARISH_INFORMATION_SCOPES = {"before_service", "after_service"}
_PARISH_INFORMATION_SECTION_FIELDS = {"title", "text", "source"}
_MUSIC_FIELDS = {"number", "title", "tune", "image", "images", "lyrics", "custom_text", "lyric_columns"}
_LYRIC_GROUP_FIELDS = {"speaker", "part", "lines", "bold", "people"}
_SERMON_FIELDS = {"selection_mode", "primary_text", "research_preferences"}
_RESEARCH_FIELDS = {
    "priority_voices", "preferred_resources", "voices_to_avoid", "language_depth",
    "human_sciences", "contemporary_context", "additional_domain",
}
_PROFILE_SECTIONS = {"status", "tradition_pack", "tradition", "defaults", "sources", "service_variants", "provenance", "source_overrides"}
# Fields the source-choice guard (skills/onboarding/source_choices.py) can
# observe from a retained bulletin import and therefore accepts an override
# record for. Keep in sync with source_choices.OBSERVERS.
_SOURCE_OVERRIDE_FIELDS = {"eucharistic_prayer", "closing_hymn_position", "gospel_acclamation"}
_SOURCE_OVERRIDE_RECORD_FIELDS = {"source_sha256", "value", "reason", "acknowledged_at"}
_SOURCE_OVERRIDE_VALUE_CHOICES = {
    "eucharistic_prayer": {"A", "B", "C", "D"},
    "closing_hymn_position": {"before_dismissal", "after_dismissal"},
    "gospel_acclamation": {"lord", "savior"},
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_TRADITION = {"family", "denomination", "service_book", "rite"}
_PROFILE_DEFAULTS = {
    "eucharistic_prayer", "lords_prayer", "prayers_of_the_people", "service_setting",
    "divine_service_setting", "include_creed", "include_confession", "print_full_eucharistic_prayer",
    "include_first_reading", "include_second_reading", "blessing",
    "doxology", "psalm_format", "psalm_response_start", "prayer_presentation", "rubric_style",
    "closing_hymn_position", "gospel_acclamation",
}
_PROFILE_SOURCES = {
    "eucharistic_prayer", "lords_prayer", "prayers_of_the_people", "blessing", "communion_welcome",
    "gathering", "prayers", "great-thanksgiving", "communion", "sending", "lords-prayer", "doxology",
}
_PROFILE_PATH_SOURCES = _PROFILE_SOURCES
_PROFILE_PROVENANCE = {"last_reviewed_on", "reviewed_by"}
_PREFERENCE_CHOICES = {
    "doxology": {"traditional", "custom", "omit"},
    "psalm_format": {"responsive_half_verse", "responsive_whole_verse", "unison", "plain"},
    "psalm_response_start": {"first", "second"},
    "prayer_presentation": {"continuous", "repeated_labels"},
    "rubric_style": {"concise", "source"},
    "closing_hymn_position": {"before_dismissal", "after_dismissal"},
    "gospel_acclamation": {"lord", "savior"},
}


class SetupError(ValueError):
    """A safe, actionable setup error."""


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _public_repo(path: Path) -> bool:
    return any(
        (ancestor / ".codex-plugin" / "plugin.json").is_file()
        or ((ancestor / ".git").is_dir() and (ancestor / "skills" / "onboarding").is_dir())
        for ancestor in (path, *path.parents)
    )


def _assert_private_root(path: str | Path) -> Path:
    """Resolve a church root and reject public repo/cache and symlink escapes."""
    original = Path(path).expanduser()
    if original.is_symlink():
        raise SetupError("Church folder symlinks are not allowed")
    root = _resolved(path)
    if not root.is_dir():
        raise SetupError(f"Church folder does not exist: {root}")
    plugin = _plugin_root()
    cache_roots = [
        plugin / ".codex" / "plugins" / "cache",
        Path.home() / ".codex" / "plugins" / "cache",
        Path.home() / ".claude" / "plugins" / "cache",
    ]
    public_repo = _public_repo(root)
    if _inside(root, plugin) or public_repo or any(_inside(root, cache) for cache in cache_roots):
        raise SetupError("Church data must live in a private folder outside the Labs repository and plugin cache")
    return root


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SetupError("The managed Python runtime needs PyYAML to update church settings") from exc
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SetupError(f"Could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SetupError(f"Expected a mapping in {path.name}")
    return value


def _dump_yaml(path: Path, value: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise SetupError("The managed Python runtime needs PyYAML to update church settings") from exc
    text = yaml.safe_dump(value, sort_keys=False, allow_unicode=False)
    _atomic_write(path, text)


def _atomic_write(path: Path, text: str) -> None:
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


def _profile_pointer(root: Path, config: dict[str, Any]) -> tuple[Path, str]:
    pointer = str(config.get("worship_profile") or PROFILE_DEFAULT).strip()
    candidate = Path(pointer)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SetupError("worship_profile must be a relative path inside the church folder")
    if (root / candidate).is_symlink():
        raise SetupError("The worship profile must be a regular file inside the church folder")
    profile = (root / candidate).resolve()
    if not _inside(profile, root):
        raise SetupError("worship_profile must stay inside the church folder")
    return profile, pointer


def _owned_file(root: Path, path: Path, label: str) -> Path:
    if path.is_symlink():
        raise SetupError(f"{label} must be a regular file inside the church folder")
    resolved = path.resolve()
    if not _inside(resolved, root):
        raise SetupError(f"{label} must stay inside the church folder")
    return resolved


def _registered_pack(pack_id: str) -> dict[str, Any]:
    if not pack_id:
        return {}
    try:
        import yaml
        catalog = yaml.safe_load((_plugin_root() / "skills" / "bulletin" / "traditions" / "catalog.yaml").read_text(encoding="utf-8"))
        packs = catalog.get("packs", []) if isinstance(catalog, dict) else []
        if not any(isinstance(item, dict) and item.get("id") == pack_id for item in packs):
            raise SetupError(f"Unknown worship tradition pack: {pack_id}")
        pack_path = _plugin_root() / "skills" / "bulletin" / "traditions" / f"{pack_id}.yaml"
        value = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except OSError as exc:
        raise SetupError(f"Could not inspect worship tradition pack: {exc}") from exc


def _validate_profile_values(profile_patch: dict[str, Any], current: dict[str, Any]) -> None:
    effective = copy.deepcopy(current)
    _deep_merge(effective, profile_patch)
    pack_id = str(effective.get("tradition_pack") or "").strip()
    pack = _registered_pack(pack_id) if pack_id else {}
    for key in ("status", "tradition_pack"):
        if key in profile_patch and profile_patch[key] is not None and not isinstance(profile_patch[key], str):
            raise SetupError(f"worship_profile.{key} must be text")
    if "status" in profile_patch and profile_patch["status"] not in ("needs_onboarding", "confirmed"):
        raise SetupError("worship_profile.status must be needs_onboarding or confirmed")
    for key in ("tradition", "sources", "provenance"):
        values = profile_patch.get(key)
        if values is not None:
            for child, value in values.items():
                if not isinstance(value, str):
                    raise SetupError(f"worship_profile.{key}.{child} must be text")
                if key == "sources" and child in _PROFILE_PATH_SOURCES and value:
                    source_path = Path(value)
                    if source_path.is_absolute() or ".." in source_path.parts:
                        raise SetupError(f"worship_profile.sources.{child} must stay inside the church folder")
    overrides = profile_patch.get("source_overrides")
    if overrides is not None:
        for field, record in overrides.items():
            if field not in _SOURCE_OVERRIDE_FIELDS:
                raise SetupError(f"worship_profile.source_overrides.{field} is not a source-checked field")
            if not isinstance(record, dict) or set(record) - _SOURCE_OVERRIDE_RECORD_FIELDS:
                raise SetupError(f"worship_profile.source_overrides.{field} has an unsupported shape")
            for required in ("source_sha256", "value", "reason"):
                if not str(record.get(required) or "").strip():
                    raise SetupError(f"worship_profile.source_overrides.{field}.{required} is required")
            if not _SHA256_RE.match(str(record.get("source_sha256"))):
                raise SetupError(f"worship_profile.source_overrides.{field}.source_sha256 must be a 64-character hex sha256")
            if record.get("value") not in _SOURCE_OVERRIDE_VALUE_CHOICES[field]:
                choices = ", ".join(sorted(_SOURCE_OVERRIDE_VALUE_CHOICES[field]))
                raise SetupError(f"worship_profile.source_overrides.{field}.value must be one of: {choices}")
            if "acknowledged_at" in record and record["acknowledged_at"] is not None and not isinstance(record["acknowledged_at"], str):
                raise SetupError(f"worship_profile.source_overrides.{field}.acknowledged_at must be text")
    defaults = profile_patch.get("defaults")
    if defaults is None:
        return
    for key, value in defaults.items():
        if key in {"include_creed", "include_confession", "print_full_eucharistic_prayer",
                   "include_first_reading", "include_second_reading"}:
            _bool_or_blank(value, f"worship_profile.defaults.{key}")
        elif value is not None and not isinstance(value, str):
            raise SetupError(f"worship_profile.defaults.{key} must be text or blank")
        if key in _PREFERENCE_CHOICES and value not in ("", None) and value not in _PREFERENCE_CHOICES[key]:
            choices = ", ".join(sorted(_PREFERENCE_CHOICES[key]))
            raise SetupError(f"worship_profile.defaults.{key} must be one of: {choices}")
        choices = ((pack.get("choices") or {}).get(key, {}) if isinstance(pack, dict) else {}).get("values", [])
        if key in {"eucharistic_prayer", "lords_prayer", "prayers_of_the_people"} and value and not pack_id:
            raise SetupError(f"Choose a tradition pack before setting worship_profile.defaults.{key}")
        if choices and isinstance(value, str) and value and value not in choices:
            raise SetupError(f"worship_profile.defaults.{key} is not a choice in {pack_id}")
    effective_defaults = effective.get("defaults") if isinstance(effective.get("defaults"), dict) else {}
    if effective_defaults.get("include_first_reading", True) is False and effective_defaults.get("include_second_reading", True) is False:
        raise SetupError("At least one non-Gospel reading must be included")
    variants = profile_patch.get("service_variants")
    if variants is not None and any(not isinstance(value, dict) for value in variants.values()):
        raise SetupError("worship_profile.service_variants entries must be objects")


def _validate_person_list(value: Any, path: str) -> None:
    if not isinstance(value, list):
        raise SetupError(f"{path} must be a list of people")
    for index, person in enumerate(value):
        if not isinstance(person, dict) or not str(person.get("name", "")).strip() or not str(person.get("role", "")).strip():
            raise SetupError(f"{path}[{index}] needs a name and role")
        if set(person) - {"name", "role"}:
            raise SetupError(f"{path}[{index}] may contain only name and role")


def _validate_music_entry(value: Any, path: str) -> None:
    """Validate the reusable hymn_block shape used for standing music."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise SetupError(f"{path} must be a music entry or blank")
    unknown = set(value) - _MUSIC_FIELDS
    if unknown:
        raise SetupError(f"Unsupported setting path under {path}: {sorted(unknown)[0]}")
    if "number" in value and (not isinstance(value["number"], (str, int)) or isinstance(value["number"], bool)):
        raise SetupError(f"{path}.number must be text or a number")
    for field in ("title", "tune", "image", "custom_text"):
        if field in value:
            _text_or_blank(value[field], f"{path}.{field}")
    for field in ("image",):
        raw = value.get(field)
        if isinstance(raw, str) and raw.strip():
            candidate = Path(raw)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise SetupError(f"{path}.{field} must stay inside the church folder")
    if "images" in value:
        _string_list(value["images"], f"{path}.images")
        for raw in value["images"]:
            candidate = Path(raw)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise SetupError(f"{path}.images must stay inside the church folder")
    if "lyrics" in value:
        lyrics = value["lyrics"]
        if not isinstance(lyrics, list):
            raise SetupError(f"{path}.lyrics must be a list")
        for index, group in enumerate(lyrics):
            if isinstance(group, str):
                continue
            if not isinstance(group, dict) or set(group) - _LYRIC_GROUP_FIELDS:
                raise SetupError(f"{path}.lyrics[{index}] has an unsupported shape")
            if "lines" in group and not isinstance(group["lines"], (str, list)):
                raise SetupError(f"{path}.lyrics[{index}].lines must be text or a list")
            if isinstance(group.get("lines"), list) and any(not isinstance(line, str) for line in group["lines"]):
                raise SetupError(f"{path}.lyrics[{index}].lines must contain text values")
            for field in ("speaker", "part"):
                if field in group:
                    _text_or_blank(group[field], f"{path}.lyrics[{index}].{field}")
            for field in ("bold", "people"):
                if field in group and not isinstance(group[field], bool):
                    raise SetupError(f"{path}.lyrics[{index}].{field} must be true or false")
    if "lyric_columns" in value and value["lyric_columns"] not in (None, 1, 2):
        raise SetupError(f"{path}.lyric_columns must be 1, 2, or blank")


def _validate_parish_information(value: Any, path: str) -> None:
    """Validate the standing before/after-service parish-information sections.

    Simple ordered title-and-text sections, distinct from dated
    announcements: a recurring welcome, accessibility note, pastoral
    contact, or worship-book explanation. Reuses the reading source-record
    shape when a section names one.
    """
    if not isinstance(value, dict) or set(value) - _PARISH_INFORMATION_SCOPES:
        choices = ", ".join(sorted(_PARISH_INFORMATION_SCOPES))
        raise SetupError(f"{path} may only use: {choices}")
    for scope, sections in value.items():
        scope_path = f"{path}.{scope}"
        if not isinstance(sections, list):
            raise SetupError(f"{scope_path} must be a list")
        for index, entry in enumerate(sections):
            entry_path = f"{scope_path}[{index}]"
            if not isinstance(entry, dict) or set(entry) - _PARISH_INFORMATION_SECTION_FIELDS:
                raise SetupError(f"{entry_path} may contain only title, text, and an optional source")
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                raise SetupError(f"{entry_path}.title must be nonblank text")
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                raise SetupError(f"{entry_path}.text must be nonblank text")
            if "source" in entry:
                source = entry["source"]
                if not isinstance(source, dict) or any(
                    not isinstance(source.get(field), str) or not source[field].strip()
                    for field in ("label", "location", "verified_on")
                ):
                    raise SetupError(f"{entry_path}.source needs label, location, and verified_on")


def _text_or_blank(value: Any, path: str) -> None:
    if value is not None and not isinstance(value, str):
        raise SetupError(f"{path} must be text")


def _bool_or_blank(value: Any, path: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise SetupError(f"{path} must be true, false, or blank")


def _string_list(value: Any, path: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SetupError(f"{path} must be a list of text values")


def _validate_patch(patch: Any, *, profile: bool = False, prefix: str = "") -> None:
    if not isinstance(patch, dict) or not patch:
        raise SetupError("A settings update must be a non-empty object")
    allowed = _PROFILE_SECTIONS if profile and not prefix else None
    if not profile and not prefix:
        allowed = set(_SCALAR_SECTIONS)
    if allowed is not None:
        unknown = set(patch) - allowed
        if unknown:
            raise SetupError(f"Unsupported setting path: {prefix + '.' if prefix else ''}{sorted(unknown)[0]}")
    for key, value in patch.items():
        path = f"{prefix}.{key}" if prefix else key
        if profile:
            child_allowed = {
                "tradition": _PROFILE_TRADITION,
                "defaults": _PROFILE_DEFAULTS,
                "sources": _PROFILE_SOURCES,
                "provenance": _PROFILE_PROVENANCE,
            }.get(key)
            if child_allowed is not None:
                if not isinstance(value, dict) or set(value) - child_allowed:
                    raise SetupError(f"Unsupported setting path under {path}")
            elif key in {"service_variants", "source_overrides"}:
                if not isinstance(value, dict):
                    raise SetupError(f"{path} must be a mapping")
            elif key in {"status", "tradition_pack"} and not isinstance(value, (str, type(None))):
                raise SetupError(f"{path} must be text")
        elif key == "leadership":
            if not isinstance(value, dict) or set(value) - _LEADERSHIP_FIELDS:
                raise SetupError(f"Unsupported setting path under {path}")
            if "clergy_and_staff" in value:
                _validate_person_list(value["clergy_and_staff"], f"{path}.clergy_and_staff")
            if "print_in_bulletin" in value:
                _bool_or_blank(value["print_in_bulletin"], f"{path}.print_in_bulletin")
            if "placement" in value and value["placement"] not in _LEADERSHIP_PLACEMENT_CHOICES:
                choices = ", ".join(sorted(_LEADERSHIP_PLACEMENT_CHOICES))
                raise SetupError(f"{path}.placement must be one of: {choices}")
            if "governing_body" in value:
                body = value["governing_body"]
                if not isinstance(body, dict) or set(body) - _GOVERNING_FIELDS:
                    raise SetupError(f"Unsupported setting path under {path}.governing_body")
                for group in ("officers", "members"):
                    if group in body:
                        _validate_person_list(body[group], f"{path}.governing_body.{group}")
                for field in ("label", "member_label"):
                    if field in body:
                        _text_or_blank(body[field], f"{path}.governing_body.{field}")
        elif key == "bulletin":
            if not isinstance(value, dict) or set(value) - _BULLETIN_FIELDS:
                raise SetupError(f"Unsupported setting path under {path}")
            if "footer" in value and (not isinstance(value["footer"], dict) or set(value["footer"]) - _FOOTER_FIELDS):
                raise SetupError(f"Unsupported setting path under {path}.footer")
            if "include_serving_today" in value:
                _bool_or_blank(value["include_serving_today"], f"{path}.include_serving_today")
            if "serving_roles" in value:
                _string_list(value["serving_roles"], f"{path}.serving_roles")
            if "template" in value and value["template"] not in ("classic", "modern"):
                raise SetupError(f"{path}.template must be classic or modern")
            if "footer" in value:
                for field, item in value["footer"].items():
                    _text_or_blank(item, f"{path}.footer.{field}")
            if "doxology_music" in value:
                _validate_music_entry(value["doxology_music"], f"{path}.doxology_music")
            if "parish_information" in value:
                _validate_parish_information(value["parish_information"], f"{path}.parish_information")
        elif key == "lectionary":
            if not isinstance(value, dict) or set(value) - {"system", "track", "translation", "optional_verses", "authorities"}:
                raise SetupError(f"Unsupported setting path under {path}")
            for field in ("system", "track", "translation", "optional_verses"):
                if field in value:
                    _text_or_blank(value[field], f"{path}.{field}")
            if "optional_verses" in value and value["optional_verses"] not in ("", None, "appointed", "include_all", "omit_optional", "ask_each_week"):
                raise SetupError(f"{path}.optional_verses is not a supported option")
            if "authorities" in value and not isinstance(value["authorities"], list):
                raise SetupError(f"{path}.authorities must be a list")
        elif key == "sermon":
            if not isinstance(value, dict) or set(value) - _SERMON_FIELDS:
                raise SetupError(f"Unsupported setting path under {path}")
            if "research_preferences" in value:
                prefs = value["research_preferences"]
                if not isinstance(prefs, dict) or set(prefs) - _RESEARCH_FIELDS:
                    raise SetupError(f"Unsupported setting path under {path}.research_preferences")
                for field in ("priority_voices", "preferred_resources", "voices_to_avoid"):
                    if field in prefs:
                        _string_list(prefs[field], f"{path}.research_preferences.{field}")
                if "language_depth" in prefs and prefs["language_depth"] not in ("plain", "moderate", "technical"):
                    raise SetupError(f"{path}.research_preferences.language_depth must be plain, moderate, or technical")
                for field in ("human_sciences", "contemporary_context"):
                    if field in prefs and not isinstance(prefs[field], bool):
                        raise SetupError(f"{path}.research_preferences.{field} must be true or false")
                if "additional_domain" in prefs:
                    _text_or_blank(prefs["additional_domain"], f"{path}.research_preferences.additional_domain")
            if "selection_mode" in value and value["selection_mode"] not in ("", None, "lectionary", "pastor_selected"):
                raise SetupError(f"{path}.selection_mode must be lectionary or pastor_selected")
            if "primary_text" in value and value["primary_text"] not in ("", None, "first", "psalm", "second", "gospel", "selected"):
                raise SetupError(f"{path}.primary_text is not a supported reading role")
        elif key == "people":
            if not isinstance(value, dict) or set(value) - {"pastor"}:
                raise SetupError("Only people.pastor is a standing setting; weekly assignments stay with the bulletin")
            _text_or_blank(value.get("pastor"), f"{path}.pastor")
        elif key == "church":
            if not isinstance(value, dict) or set(value) - (_SCALAR_SECTIONS["church"]):
                raise SetupError(f"Unsupported setting path under {path}")
            for field in ("name", "short_name", "tradition", "city", "address", "website"):
                if field in value:
                    _text_or_blank(value[field], f"{path}.{field}")
            if "regular_services" in value:
                if not isinstance(value["regular_services"], list):
                    raise SetupError(f"{path}.regular_services must be a list")
                for index, service in enumerate(value["regular_services"]):
                    if not isinstance(service, dict) or set(service) - {"day", "time", "label"}:
                        raise SetupError(f"{path}.regular_services[{index}] must contain day, time, and optional label")
                    if not isinstance(service.get("day"), str) or not isinstance(service.get("time"), str):
                        raise SetupError(f"{path}.regular_services[{index}] needs text day and time")


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            for child in _deep_merge(target[key], value):
                changed.append(f"{key}.{child}")
        else:
            if target.get(key) != value:
                changed.append(key)
            target[key] = copy.deepcopy(value)
    return changed


def _roster(config: dict[str, Any]) -> list[dict[str, str]]:
    leadership = config.get("leadership")
    people = leadership.get("clergy_and_staff", []) if isinstance(leadership, dict) else []
    return [
        {"name": str(item["name"]).strip(), "role": str(item["role"]).strip()}
        for item in people if isinstance(item, dict) and str(item.get("name", "")).strip() and str(item.get("role", "")).strip()
    ]


def _name_tokens(name: str) -> list[str]:
    tokens = str(name).strip().casefold().replace(",", "").split()
    while tokens and tokens[0].rstrip(".") in {"the", "rev", "reverend", "fr", "father", "dr", "mr", "mrs", "ms"}:
        tokens.pop(0)
    return tokens


def resolve_person(church_folder: str | Path, role: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Resolve a person from the maintained roster, or return needs_input.

    Role matching is exact and case-insensitive.  A first-name query is
    accepted only when it identifies one roster entry.  This read-only helper
    never turns a dated assignment into a standing person.
    """
    root = _assert_private_root(church_folder)
    config = _load_yaml(_owned_file(root, root / "church.yaml", "church.yaml"))
    roster = _roster(config)
    role_query = str(role or "").strip().casefold()
    name_query = " ".join(_name_tokens(str(name or "")))
    candidates = [person for person in roster if not role_query or person["role"].casefold() == role_query]
    if name_query:
        exact = [person for person in candidates if " ".join(_name_tokens(person["name"])) == name_query]
        if exact:
            candidates = exact
        else:
            candidates = [person for person in candidates if _name_tokens(person["name"]) and _name_tokens(person["name"])[0] == name_query]
    if len(candidates) == 1:
        return {"status": "resolved", "person": candidates[0], "matches": candidates, "scope": "standing_roster"}
    return {
        "status": "needs_input" if len(candidates) > 1 else "not_found",
        "person": None,
        "matches": candidates,
        "scope": "standing_roster",
        "message": "Choose a name from the maintained clergy and staff roster" if len(candidates) != 1 else "",
    }


def update_standing(church_folder: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a narrow standing-profile patch to church.yaml/profile.yaml."""
    root = _assert_private_root(church_folder)
    patch = copy.deepcopy(patch)
    if isinstance(patch, dict) and isinstance(patch.get("lectionary"), dict):
        track = patch["lectionary"].get("track")
        normalized = str(track).strip().casefold().replace(" ", "")
        if normalized in {"1", "track1", "2", "track2"}:
            patch["lectionary"]["track"] = "Track " + normalized[-1]
    _validate_patch(patch)
    config_path = _owned_file(root, root / "church.yaml", "church.yaml")
    config = _load_yaml(config_path)
    profile_path, profile_pointer = _profile_pointer(root, config)
    profile_path = _owned_file(root, profile_path, "worship profile") if profile_path.exists() else profile_path
    config_patch = {key: value for key, value in patch.items() if key != "worship_profile"}
    profile_patch = patch.get("worship_profile")
    # The profile has its own top-level file.  Require it explicitly so a
    # typo cannot silently create a second settings database.
    if profile_patch is not None:
        _validate_patch(profile_patch, profile=True)
        _validate_profile_values(profile_patch, _load_yaml(profile_path))
        profile = _load_yaml(profile_path)
    else:
        profile = None
    changed = _deep_merge(config, config_patch)
    lectionary = config.get("lectionary", {})
    if str(lectionary.get("system", "")).casefold() in {"rcl", "revised common lectionary"}:
        track = str(lectionary.get("track") or "").strip()
        if track and track.casefold() not in {"track 1", "track 2"}:
            raise SetupError("Save the confirmed RCL track as Track 1 or Track 2; do not ask again when the pastor has already selected it")
    if changed:
        _dump_yaml(config_path, config)
    if profile_patch is not None:
        profile_changed = _deep_merge(profile, profile_patch)
        if profile_changed:
            _dump_yaml(profile_path, profile)
        changed.extend([f"worship_profile.{item}" for item in profile_changed])
    return {"status": "updated", "scope": "standing", "changed": changed, "worship_profile": profile_pointer, "readiness": status(root)}


def update(church_folder: str | Path, patch: dict[str, Any], *, scope: str) -> dict[str, Any]:
    """Route an explicit scope without allowing weekly data into config."""
    if scope != "standing":
        raise SetupError("One-week changes belong in the dated bulletin or sermon input; they are never saved as standing settings")
    return update_standing(church_folder, patch)


def status(church_folder: str | Path) -> dict[str, Any]:
    """Return readiness based on actual files and the worship resolver."""
    root = _assert_private_root(church_folder)
    present = {name: (root / name).is_file() for name in REQUIRED_FILES}
    scaffold_ready = all(present.values())
    config: dict[str, Any] = {}
    profile: dict[str, Any] = {}
    brand: dict[str, Any] = {"status": "unavailable", "ready": False, "unresolved": [{"field": "brand.json", "reason": "Create the private church folder first"}]}
    resolver: dict[str, Any]
    if scaffold_ready:
        config = _load_yaml(_owned_file(root, root / "church.yaml", "church.yaml"))
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from brand_setup import status as brand_status
            brand = brand_status(root)
        except Exception as exc:
            brand = {"status": "error", "ready": False, "unresolved": [{"field": "brand.json", "reason": str(exc)}]}
        profile_path, _ = _profile_pointer(root, config)
        if profile_path.is_file():
            profile = _load_yaml(_owned_file(root, profile_path, "worship profile"))
    try:
        sys.path.insert(0, str(_plugin_root()))
        from skills.bulletin.worship_resolution import resolve_worship_profile
        # Standing readiness never has this week's context, so a configured
        # service variant with no selection yet must not block it. Weekly
        # production resolves without standing_only and still requires an
        # explicit choice.
        resolver = resolve_worship_profile(root, standing_only=True)
    except Exception as exc:
        resolver = {"status": "needs_input", "errors": [{"message": str(exc)}]}
    sermon = config.get("sermon") if isinstance(config.get("sermon"), dict) else {}
    lectionary = config.get("lectionary") if isinstance(config.get("lectionary"), dict) else {}
    selection_mode = str(sermon.get("selection_mode") or "").strip().casefold()
    primary_text = str(sermon.get("primary_text") or "").strip().casefold()
    translation_ready = bool(str(lectionary.get("translation") or "").strip())
    system = str(lectionary.get("system") or "").strip()
    uses_rcl = system.casefold() in {"rcl", "revised common lectionary"}
    track_ready = not uses_rcl or str(lectionary.get("track") or "").strip().casefold() in {"track 1", "track 2"}
    lectionary_defaults_ready = translation_ready and bool(system) and track_ready
    optional_verses_ready = str(lectionary.get("optional_verses") or "").strip() in {
        "appointed", "include_all", "omit_optional", "ask_each_week",
    }
    reading_defaults_ready = translation_ready and (
        selection_mode == "pastor_selected"
        or (lectionary_defaults_ready and optional_verses_ready)
    )
    sermon_ready = (
        selection_mode in {"lectionary", "pastor_selected"}
        and primary_text in ({"selected"} if selection_mode == "pastor_selected" else {"first", "psalm", "second", "gospel"})
        and reading_defaults_ready
    )
    defaults = profile.get("defaults") if isinstance(profile.get("defaults"), dict) else {}
    uses_episcopal_order = resolver.get("liturgy", {}).get("service_plan") == "episcopal-rite-ii"
    # A retained bulletin import is an optional, additional check, and its
    # anchors (Eucharistic Prayer letters, BCP page numbers) are Episcopal
    # Rite II specific, so it only ever runs once the resolved service plan
    # is confirmed as episcopal-rite-ii. No import present never blocks
    # readiness. An unexpected failure while running the guard itself is
    # surfaced as an explicit "unavailable" diagnostic rather than silently
    # treated as a clean pass -- it must not read as "checked, no problems".
    source_contradictions: list[dict[str, Any]] = []
    source_observations: dict[str, Any] = {}
    source_check_status = "not_applicable"
    if scaffold_ready and uses_episcopal_order:
        try:
            sys.path.insert(0, str(_plugin_root()))
            from skills.onboarding.bulletin_import import IMPORT_ROOT, list_imports
            from skills.onboarding.source_choices import aggregate_imports, find_contradictions, observe_manifest
            imports = [item for item in list_imports(root) if isinstance(item, dict) and item.get("import_id")]
            if not imports:
                # list_imports() silently skips a directory whose
                # manifest.json is missing or unparseable, so an empty
                # result here is ambiguous between "nothing was ever
                # imported" and "an import exists but could not be read."
                # Only the first is genuinely no_import.
                imports_root = root / IMPORT_ROOT
                has_import_paths = imports_root.is_dir() and any(imports_root.iterdir())
                source_check_status = "unavailable" if has_import_paths else "no_import"
            else:
                observations_by_import = {item["import_id"]: observe_manifest(root, item) for item in imports}
                sha256_by_import = {
                    item["import_id"]: item.get("source", {}).get("sha256")
                    for item in imports
                    if isinstance(item.get("source"), dict)
                }
                source_observations = aggregate_imports(observations_by_import, sha256_by_import)
                overrides = profile.get("source_overrides") if isinstance(profile.get("source_overrides"), dict) else {}
                source_contradictions = find_contradictions(source_observations, defaults, overrides)
                source_check_status = "checked"
        except Exception:
            source_check_status = "unavailable"
            source_contradictions = []
            source_observations = {}
    print_defaults_ready = not uses_episcopal_order or (
        all(isinstance(defaults.get(key), bool)
            for key in ("include_creed", "include_confession", "print_full_eucharistic_prayer"))
        and all(isinstance(defaults.get(key, True), bool)
                for key in ("include_first_reading", "include_second_reading"))
    )
    church = config.get("church") if isinstance(config.get("church"), dict) else {}
    identity_ready = bool(str(church.get("name") or "").strip())
    folder_ready = scaffold_ready and identity_ready
    bulletin_ready = (
        folder_ready and brand.get("ready", False) and resolver.get("status") == "resolved"
        and lectionary_defaults_ready and print_defaults_ready and not source_contradictions
    )
    research_ready = folder_ready and sermon_ready
    workflow_ready = bulletin_ready or research_ready
    first_results = _first_results(root)
    first_result = bool(first_results)
    state = "actual_first_result" if first_result else "workflow_ready" if workflow_ready else "folder_ready" if folder_ready else "scaffold_ready" if scaffold_ready else "not_ready"
    unresolved: list[Any] = []
    if scaffold_ready and not folder_ready:
        unresolved.append({"field": "church.name", "reason": "Confirm the church's formal name"})
    if scaffold_ready and resolver.get("status") != "resolved":
        unresolved.extend(resolver.get("unresolved", []))
        unresolved.extend(resolver.get("errors", []))
    if folder_ready and not brand.get("ready", False):
        unresolved.extend(brand.get("unresolved", []))
    if folder_ready and not print_defaults_ready:
        for field in ("include_creed", "include_confession", "print_full_eucharistic_prayer"):
            if defaults.get(field) is None:
                unresolved.append({"field": f"worship_profile.defaults.{field}", "reason": "Confirm whether the service prints this part of the liturgy"})
    if folder_ready and not str(sermon.get("selection_mode") or "").strip():
        unresolved.append({"field": "sermon.selection_mode", "reason": "Choose lectionary or pastor-selected preaching"})
    if folder_ready and not str(sermon.get("primary_text") or "").strip():
        unresolved.append({"field": "sermon.primary_text", "reason": "Choose the usual primary sermon reading"})
    if folder_ready and not translation_ready:
        unresolved.append({"field": "lectionary.translation", "reason": "Choose the usual preaching translation"})
    if folder_ready and selection_mode == "lectionary" and not optional_verses_ready:
        unresolved.append({"field": "lectionary.optional_verses", "reason": "Confirm whether optional verses follow the published appointment, always use the longer or shorter form, or are chosen each week"})
    if folder_ready and not system:
        unresolved.append({"field": "lectionary.system", "reason": "Choose the lectionary used for regular preaching"})
    if folder_ready and uses_rcl and not track_ready:
        unresolved.append({"field": "lectionary.track", "reason": "Use Track 1 or Track 2 for the Revised Common Lectionary"})
    if folder_ready and selection_mode and selection_mode not in {"lectionary", "pastor_selected"}:
        unresolved.append({"field": "sermon.selection_mode", "reason": "Choose lectionary or pastor-selected preaching"})
    if folder_ready and primary_text and primary_text not in ({"selected"} if selection_mode == "pastor_selected" else {"first", "psalm", "second", "gospel"}):
        unresolved.append({"field": "sermon.primary_text", "reason": "Choose a primary reading that matches the preaching practice"})
    for item in source_contradictions:
        page_note = f" (page {item['page']})" if item.get("page") else ""
        unresolved.append({
            "field": f"worship_profile.defaults.{item['field']}",
            "reason": (
                f"The imported bulletin shows {item['field_label']} as {item['source_value']}{page_note}, "
                f"but the saved standing choice is {item['standing_value']}. Confirm this is intentional and "
                "record it, or update the saved choice to match the source."
            ),
        })
    readiness_status = "ready" if bulletin_ready and research_ready else "partially_ready" if workflow_ready else "needs_input"
    next_action = _next_action(scaffold_ready, folder_ready, bulletin_ready, research_ready, print_defaults_ready, first_result, resolver, brand)
    if folder_ready and uses_rcl and not track_ready:
        next_action = "Save the confirmed lectionary.track as Track 1 or Track 2 through onboarding update; do not repeat an answered question"
    if source_contradictions:
        fields = ", ".join(item["field_label"] for item in source_contradictions)
        next_action = (
            f"Resolve {len(source_contradictions)} source-backed worship choice mismatch"
            f"{'es' if len(source_contradictions) != 1 else ''} against the imported bulletin ({fields}) "
            "before trusting bulletin_ready"
        )
    return {
        "status": readiness_status,
        "message": "Both workflows are ready for their first result" if readiness_status == "ready" else "Report each workflow separately; setup remains incomplete for the workflows marked false. Correct saved values from confirmed answers before asking again.",
        "church_folder": str(root),
        "state": state,
        "scaffold_ready": scaffold_ready,
        "folder_ready": folder_ready,
        "workflow_ready": workflow_ready,
        "bulletin_ready": bulletin_ready,
        "research_ready": research_ready,
        "workflow_readiness": {"bulletin": bulletin_ready, "research": research_ready},
        "actual_first_result": first_result,
        "first_results": first_results,
        "unresolved": unresolved,
        "present": present,
        "worship": {
            "status": resolver.get("status"),
            "profile_status": resolver.get("profile_status"),
            "service_variant_pending": resolver.get("service_variant_pending", False),
        },
        "brand": brand,
        "source_choices": {
            "status": source_check_status,
            "observations": source_observations,
            "contradictions": source_contradictions,
        },
        "next_action": next_action,
    }


def _first_results(root: Path) -> list[dict[str, Any]]:
    """Return only receipt-backed results, using each workflow's state rules."""
    results: list[dict[str, Any]] = []
    receipt_paths = sorted((root / "bulletins").glob("**/bulletin-production-receipt.json")) if (root / "bulletins").is_dir() else []
    for receipt_path in receipt_paths:
        try:
            sys.path.insert(0, str(_plugin_root()))
            from skills.bulletin.bulletin_production.interface import _receipt_artifact_path, _sha256 as production_sha256
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            valid = receipt.get("status") in {"ready_for_review", "approved"}
            artifacts = receipt.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                valid = False
                artifacts = []
            roles = {item.get("role") for item in artifacts if isinstance(item, dict)}
            if not {"config", "sequential_pdf", "booklet_pdf"} <= roles or receipt.get("blocking_failures"):
                valid = False
            for artifact in artifacts:
                relative = Path(str(artifact.get("path", "")))
                artifact_path = _receipt_artifact_path(root, receipt_path, receipt, artifact.get("path", ""))
                if relative.is_absolute() or not _inside(artifact_path, root) or not artifact_path.is_file() or artifact.get("sha256") != production_sha256(artifact_path):
                    valid = False
            if valid:
                results.append({"kind": "bulletin", "receipt": str(receipt_path), "status": receipt.get("status")})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    if (root / "sermons").is_dir():
        try:
            sermon_orient = _load_sermon_orient()
            for sermon_dir in sorted(path for path in (root / "sermons").iterdir() if path.is_dir() and path.name[:4].isdigit()):
                result = sermon_orient(root, sermon_dir.name)
                if result.get("workflow_state") == "research_complete":
                    results.append({"kind": "sermon_research", "date": sermon_dir.name, "status": "research_complete"})
        except (ImportError, OSError, ValueError):
            pass
    return results


def _load_sermon_orient() -> Any:
    """Load the hyphenated skill package through its supported workflow API."""
    package = _plugin_root() / "skills" / "sermon-research" / "sermon_workflow" / "__init__.py"
    spec = importlib.util.spec_from_file_location("handbuilt_sermon_workflow", package)
    if spec is None or spec.loader is None:
        raise ImportError("Sermon workflow is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.orient


def _next_action(scaffold_ready: bool, folder_ready: bool, bulletin_ready: bool, research_ready: bool, print_defaults_ready: bool, first_result: bool, resolver: dict[str, Any], brand: dict[str, Any] | None = None) -> str:
    if not scaffold_ready:
        return "Finish creating the private church folder"
    if not folder_ready:
        return "Confirm the church identity before continuing setup"
    if not bulletin_ready and (resolver.get("status") != "resolved" or not print_defaults_ready):
        return "Finish the standing worship choices, then check the worship profile"
    if not (brand or {}).get("ready", False):
        return "Resolve the church logo and color choices before building a bulletin"
    if not research_ready:
        return "Choose the usual sermon text and preaching translation"
    if not bulletin_ready:
        return "Confirm the standing lectionary and translation for bulletin readings"
    if not first_result:
        return "Build the first bulletin or start sermon research"
    return "Use the next weekly bulletin or sermon request"


def _connect_folder(root: Path) -> dict[str, Any]:
    path = _plugin_root() / "tools" / "church_workflow.py"
    spec = importlib.util.spec_from_file_location("handbuilt_connection", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.connect(root)


def create(destination: str | Path, name: str) -> dict[str, Any]:
    parent = _resolved(destination)
    if not parent.is_dir():
        raise SetupError(f"Destination does not exist: {parent}")
    if not name or name != name.strip() or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in name):
        raise SetupError("Folder name must use lowercase letters, numbers, and hyphens")
    target = parent / name
    if target.exists():
        return {"status": "returning", "church_folder": str(_assert_private_root(target)), "connection": _connect_folder(target), "readiness": status(target)}
    # Resolve the target before copying, so a symlinked parent cannot redirect
    # private church data into the public repository or plugin cache.
    resolved_target = target.resolve()
    _assert_private_parent(parent)
    if _inside(resolved_target, _plugin_root()) or _public_repo(resolved_target) or any(
        _inside(resolved_target, cache) for cache in (
            Path.home() / ".codex" / "plugins" / "cache",
            Path.home() / ".claude" / "plugins" / "cache",
        )
    ):
        raise SetupError("Church data must live in a private folder outside the Labs repository and plugin cache")
    shutil.copytree(_plugin_root() / "scaffold" / "church-folder", resolved_target)
    return {"status": "created", "church_folder": str(resolved_target), "connection": _connect_folder(resolved_target), "readiness": status(resolved_target)}


def _assert_private_parent(parent: Path) -> None:
    if parent.is_symlink():
        raise SetupError("The church folder destination cannot be a symlink")
    if _inside(parent, _plugin_root()) or _public_repo(parent) or any(
        _inside(parent, cache) for cache in (
            Path.home() / ".codex" / "plugins" / "cache",
            Path.home() / ".claude" / "plugins" / "cache",
        )
    ):
        raise SetupError("Church data must live in a private folder outside the Labs repository and plugin cache")


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Safely create, update, or inspect a private church setup")
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--destination", required=True)
    create_parser.add_argument("--name", required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--church-folder", required=True)
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--church-folder", required=True)
    update_parser.add_argument("--scope", choices=("standing", "weekly"), required=True)
    update_parser.add_argument("--patch-file", required=True)
    resolve_parser = sub.add_parser("resolve-person")
    resolve_parser.add_argument("--church-folder", required=True)
    resolve_parser.add_argument("--role")
    resolve_parser.add_argument("--name")
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create(args.destination, args.name)
        elif args.command == "status":
            result = status(args.church_folder)
        elif args.command == "resolve-person":
            result = resolve_person(args.church_folder, args.role, args.name)
        else:
            if args.scope != "standing":
                raise SetupError("One-week changes belong in the dated bulletin or sermon input; they are never saved as standing settings")
            patch = json.loads(Path(args.patch_file).read_text(encoding="utf-8"))
            result = update(args.church_folder, patch, scope=args.scope)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (SetupError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
