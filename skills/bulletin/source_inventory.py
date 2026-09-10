"""Track which sections of a supplied bulletin have been mapped into church
settings, and check that mapping before production relies on it.

:mod:`skills.onboarding.bulletin_import` produces raw evidence: page renders,
page text, and extracted artwork. This module records what an agent or
pastor decided that evidence means for one imported bulletin: which source
page range maps to which supported church setting, private text file, or
private asset, and whether that decision is settled, still open, or
explicitly declined. It is a source-accounting aid, not a claim to
automatically recognize every prayer, prove visual fidelity, or establish
complete coverage from a page count.

Three checks are exported, deliberately kept separate:

- :func:`check_mapping_integrity` is an informative pre-render check for
  onboarding. It confirms the recorded inventory still matches what is on
  disk. It never blocks: an unresolved section is reported for visibility,
  not returned as an error.
- :func:`validate_for_production` is the blocking pre-render check the
  bulletin workflow should invoke before it relies on any import for a
  specific week's bulletin. A relevant unresolved section (standing, or
  weekly with a matching service date), an unreviewed import, a destination
  path the renderer does not actually support, a config path that does not
  resolve in the supplied bulletin or the church's saved standing settings,
  a mapped asset/text file that is not referenced by any supported render
  input, or an omitted section with no recorded reason, all block it. It
  returns a deterministic ``fingerprint`` over the checked source hashes,
  section records, and resolved values, so a caller can detect that nothing
  relevant changed between two calls -- and that it did change when mapped
  content was edited and re-recorded, even if both states are valid.
- :func:`check_rendered_text` is an optional post-render check. Given an
  actual rendered bulletin PDF, it confirms a mapped text excerpt appears in
  that PDF's extracted text, after whitespace normalization. It covers text
  only; a mapped image, logo, or music asset always needs a human visual
  review, reported separately as ``visual_review`` rather than folded into a
  pass/fail status.

Destination paths are checked against a small explicit allowlist of the
fields the renderer and standing setup actually consume (see
``_WEEKLY_DESTINATION_TEMPLATES`` / ``_STANDING_DESTINATION_TEMPLATES``), not
a generic schema framework. A path merely existing in the supplied data is
not enough; it must match one of these known destinations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

IMPORT_ROOT = "onboarding/imports"
DISPOSITIONS = ("mapped", "unresolved", "omitted")
SCOPES = ("standing", "weekly")
_IMPORT_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Hymn slot names are a small closed set the renderer actually reads (see
# render_bulletin.py); the field schema's own additionalProperties is looser
# than what the renderer uses, so the renderer -- not the schema alone -- is
# the source of truth here. service_music slots are closed in the schema
# itself (additionalProperties: false). A key outside either set is never a
# supported destination or reference, no matter what a lookup would find.
_HYMN_SLOTS = ("entrance", "gradual", "offertory", "communion", "closing")
_SERVICE_MUSIC_SLOTS = (
    "prelude", "gloria", "psalm_antiphon", "offertory_anthem", "sursum_corda",
    "sanctus", "fraction_anthem", "doxology", "communion_anthem", "postlude",
)
_HYMN_BLOCK_FIELDS = (
    "number", "title", "tune", "image", "images", "lyrics", "custom_text", "lyric_columns", "composer",
)
_HYMN_DESTINATION_TEMPLATES = tuple(
    f"hymns.{slot}" + (f".{field}" if field else "")
    for slot in _HYMN_SLOTS for field in ("",) + _HYMN_BLOCK_FIELDS
)
_SERVICE_MUSIC_DESTINATION_TEMPLATES = tuple(
    f"service_music.{slot}" + (f".{field}" if field else "")
    for slot in _SERVICE_MUSIC_SLOTS for field in ("",) + _HYMN_BLOCK_FIELDS
)
# Resolved liturgy leaf fields mirror worship_profile.defaults choice keys
# (see skills/onboarding/scripts/church_setup.py _PROFILE_DEFAULTS) as
# worship resolution copies them into the weekly liturgy object.
_LITURGY_RESOLVED_DEFAULTS = (
    "eucharistic_prayer", "lords_prayer", "prayers_of_the_people", "service_setting",
    "divine_service_setting", "include_creed", "include_confession", "print_full_eucharistic_prayer",
    "include_first_reading", "include_second_reading", "blessing",
    "doxology", "psalm_format", "psalm_response_start", "prayer_presentation", "rubric_style",
    "closing_hymn_position",
)

# Destination paths a mapped section's config_path may target. "*" matches
# exactly one open segment (a worship_profile default/source key, itself a
# closed choice validated elsewhere); "#" matches exactly one list index. A
# path must match one of these literally, whether or not the same name
# happens to exist elsewhere in the supplied data -- an ignored or unrelated
# key never passes just because a lookup would succeed.
_WEEKLY_DESTINATION_TEMPLATES = (
    "template",
    "service.date", "service.time", "service.variant", "service.occasion", "service.proper",
    "service.lectionary_track", "service.preacher", "service.celebrant",
    "service.liturgical_color", "service.display_name",
    "collect_of_day", "proper_preface",
    "readings.first", "readings.second", "readings.psalm", "readings.gospel",
    "readings.*.citation", "readings.*.number", "readings.*.text", "readings.*.source",
    "announcements", "announcements.#", "announcements.#.title", "announcements.#.text",
    "announcements.#.image", "announcements.#.images", "announcements.#.caption",
    "options", "options.*",
    "liturgy", "liturgy.service_plan", "liturgy.sources", "liturgy.sources.*",
    "liturgy.files", "liturgy.files.*",
    "liturgy.service_variant_provenance", "liturgy.service_variant_provenance.*",
) + _HYMN_DESTINATION_TEMPLATES + _SERVICE_MUSIC_DESTINATION_TEMPLATES + tuple(
    f"liturgy.{key}" for key in _LITURGY_RESOLVED_DEFAULTS
)
_STANDING_DESTINATION_TEMPLATES = (
    "church.name", "church.short_name", "church.tradition", "church.city", "church.address",
    "church.website", "church.regular_services",
    "leadership.print_in_bulletin", "leadership.clergy_and_staff", "leadership.governing_body",
    "leadership.placement",
    "bulletin.include_serving_today", "bulletin.serving_roles", "bulletin.footer", "bulletin.template",
    "bulletin.doxology_music",
    # Standing, ordered before/after-service sections such as a recurring
    # welcome, accessibility note, pastoral contact, or worship-book
    # explanation -- distinct from a dated weekly announcement.
    "bulletin.parish_information",
    "bulletin.parish_information.before_service.#.title", "bulletin.parish_information.before_service.#.text",
    "bulletin.parish_information.after_service.#.title", "bulletin.parish_information.after_service.#.text",
    "lectionary.system", "lectionary.track", "lectionary.translation", "lectionary.optional_verses",
    "lectionary.authorities",
    "sermon.selection_mode", "sermon.primary_text", "sermon.research_preferences",
    "people.pastor",
    "worship_profile.status", "worship_profile.tradition_pack", "worship_profile.tradition",
    "worship_profile.defaults", "worship_profile.defaults.*", "worship_profile.sources",
    "worship_profile.sources.*", "worship_profile.service_variants", "worship_profile.provenance",
    # The logo and QR image paths live in the church's brand.json, not
    # church.yaml -- a mapped logo/QR section targets these, not a church.*
    # or worship_profile.* path. episcopal_shield is the supported built-in
    # cover-logo fallback alongside mark/banner; see brand_setup.LOGO_FIELDS.
    "brand.logo.mark", "brand.logo.banner", "brand.logo.episcopal_shield",
    "brand.qr.connect.image", "brand.qr.give.image",
)

_MAPPING_INTEGRITY_NOTE = (
    "This checks that the recorded mapping still matches what is on disk: the "
    "retained source snapshot is unchanged, and each mapped text or asset file "
    "still exists with the content recorded when it was mapped. It is purely "
    "informative for onboarding and never blocks; use validate_for_production "
    "for the blocking check a weekly bulletin should pass before it relies on "
    "an import. It does not confirm that an image, logo, or music asset looks "
    "correct -- see visual_review. A page count is never evidence of complete "
    "coverage."
)
_PRODUCTION_VALIDATION_NOTE = (
    "This blocks on a relevant unresolved section, an import with no recorded "
    "sections or without a current mark_review_complete attestation -- "
    "recording only some sections, a logo say, never counts as a pass by "
    "itself -- an omitted section with no recorded reason, a destination the "
    "renderer does not actually support, a config path that does not resolve "
    "in the supplied bulletin or the church's saved standing settings, a "
    "mapped asset/text file not referenced by any supported render input, or "
    "a changed source/target hash. A weekly section only counts when its "
    "recorded service_date matches this bulletin's date; a standing section "
    "always carries forward. Passing confirms mapping integrity, an explicit "
    "review attestation, and reference wiring -- not that a rendered bulletin "
    "looks correct, and not that an image, logo, or music asset was visually "
    "confirmed; see visual_review for those, and it is never proof of "
    "exhaustive semantic coverage. The fingerprint changes whenever a "
    "relevant source hash, section record, target file hash, or resolved "
    "config value changes, even between two states that are both valid."
)
_RENDERED_TEXT_NOTE = (
    "A match confirms the excerpt appears somewhere in the rendered pages, "
    "after whitespace normalization. It does not confirm placement, "
    "formatting, surrounding wording, or that printed music or artwork is "
    "correct."
)


class InventoryError(ValueError):
    """A safe, actionable source-inventory error."""


def _church_root(church_folder: str | Path) -> Path:
    root = Path(church_folder).expanduser().resolve()
    if not all((root / name).is_file() for name in ("church.yaml", "brand.json")) or any(
        (parent / ".codex-plugin" / "plugin.json").is_file() for parent in (root, *root.parents)
    ):
        raise InventoryError("Use an initialized private church folder outside the plugin")
    return root


def _valid_import_id(import_id: str) -> str:
    if not isinstance(import_id, str) or not _IMPORT_ID_RE.match(import_id):
        raise InventoryError("import_id must be the 16-character import identifier from an import result")
    return import_id


def _confined(root: Path, *parts: str) -> Path:
    """Build root/parts, rejecting any existing symlink at or above the target.

    Each ``part`` is split on ``/`` and checked segment by segment -- checking
    only after each whole ``part`` is joined would miss a symlink planted at
    an intermediate segment inside a single caller-supplied part like
    ``"onboarding/imports"``.
    """
    current = root
    for part in parts:
        for segment in Path(part).parts:
            current = current / segment
            if current.is_symlink():
                raise InventoryError(f"{current} must not be a symlink inside the church folder")
    if current.exists():
        resolved = current.resolve()
        if not resolved.is_relative_to(root):
            raise InventoryError("This path would escape the private church folder")
    return current


def _owned(root: Path, raw: str | Path) -> Path:
    """Resolve a relative path recorded as a mapping target. Never accepts an
    absolute path or a stored value that could otherwise escape the root,
    even if that value came from a persisted (and possibly tampered) file."""
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise InventoryError("A mapped target must be a relative path inside the church folder")
    return _confined(root, *candidate.parts)


def _owned_read(root: Path, raw: str | Path) -> Path:
    """Resolve a caller-supplied path (relative or absolute) for reading,
    confined to the church folder either way."""
    candidate = Path(raw)
    parts = candidate.parts if not candidate.is_absolute() else Path(os.path.relpath(candidate, root)).parts
    if ".." in parts:
        raise InventoryError("Path must stay inside the church folder")
    return _confined(root, *parts)


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_path(root: Path, import_id: str) -> Path:
    return _confined(root, IMPORT_ROOT, import_id, "manifest.json")


def _inventory_path(root: Path, import_id: str) -> Path:
    return _confined(root, IMPORT_ROOT, import_id, "inventory.json")


def _valid_manifest(manifest: Any) -> bool:
    if not isinstance(manifest, dict):
        return False
    source = manifest.get("source")
    if not isinstance(source, dict):
        return False
    if not isinstance(source.get("path"), str) or not source["path"]:
        return False
    if not isinstance(source.get("sha256"), str) or not _SHA256_RE.match(source["sha256"]):
        return False
    return isinstance(source.get("page_count"), int) and source["page_count"] >= 0


def _valid_section(section: Any) -> bool:
    if not isinstance(section, dict):
        return False
    if not isinstance(section.get("section_id"), str) or not section["section_id"]:
        return False
    if section.get("disposition") not in DISPOSITIONS or section.get("scope") not in SCOPES:
        return False
    if not isinstance(section.get("target"), dict) or not isinstance(section.get("evidence"), dict):
        return False
    if not isinstance(section.get("page_start"), int) or not isinstance(section.get("page_end"), int):
        return False
    for key in ("text_sha256", "asset_sha256"):
        value = section["evidence"].get(key)
        if value is not None and (not isinstance(value, str) or not _SHA256_RE.match(value)):
            return False
    return True


def _load_manifest(root: Path, import_id: str) -> dict[str, Any]:
    path = _manifest_path(root, import_id)
    if not path.is_file():
        raise InventoryError(f"No import recorded for {import_id}. Run the bulletin import first.")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InventoryError(f"manifest.json for {import_id} is unreadable or not valid JSON") from exc
    if not _valid_manifest(manifest):
        raise InventoryError(f"manifest.json for {import_id} is malformed or has been tampered with")
    return manifest


def _sections_fingerprint(sections: list[dict[str, Any]]) -> str:
    ordered = sorted(sections, key=lambda s: (s["page_start"], s["section_id"]))
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _valid_review(review: Any) -> bool:
    if review is None:
        return True
    return (
        isinstance(review, dict)
        and isinstance(review.get("complete"), bool)
        and (review.get("sections_fingerprint") is None or isinstance(review["sections_fingerprint"], str))
    )


def _load_inventory(root: Path, import_id: str) -> dict[str, Any]:
    path = _inventory_path(root, import_id)
    if path.is_file():
        try:
            inventory = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InventoryError(f"inventory.json for {import_id} is unreadable or not valid JSON") from exc
        if not isinstance(inventory, dict) or not isinstance(inventory.get("sections"), list):
            raise InventoryError(f"inventory.json for {import_id} is malformed or has been tampered with")
        if any(not _valid_section(section) for section in inventory["sections"]):
            raise InventoryError(f"inventory.json for {import_id} contains a malformed section record")
        if not _valid_review(inventory.get("review")):
            raise InventoryError(f"inventory.json for {import_id} has a malformed review record")
        inventory.setdefault("review", {"complete": False})
        return inventory
    manifest = _load_manifest(root, import_id)
    return {
        "schema_version": 1, "import_id": import_id, "source": manifest["source"],
        "sections": [], "review": {"complete": False},
    }


def _save_inventory(root: Path, import_id: str, inventory: dict[str, Any]) -> None:
    path = _inventory_path(root, import_id)
    fd, temporary = tempfile.mkstemp(prefix=".inventory.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(inventory, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _segment_matches(template_segment: str, actual_segment: str) -> bool:
    if template_segment == "*":
        return True
    if template_segment == "#":
        return actual_segment.isdigit()
    return template_segment == actual_segment


def _path_allowed(dotted_path: str, templates: tuple[str, ...]) -> bool:
    segments = dotted_path.split(".")
    for template in templates:
        template_segments = template.split(".")
        if len(template_segments) == len(segments) and all(
            _segment_matches(t, s) for t, s in zip(template_segments, segments)
        ):
            return True
    return False


def _validate_target(target: dict[str, Any], scope: str) -> None:
    unknown = set(target) - {"config_path", "text_file", "asset_path"}
    if unknown:
        raise InventoryError(f"Unsupported target field: {sorted(unknown)[0]}")
    if "config_path" in target:
        config_path = str(target["config_path"])
        templates = _WEEKLY_DESTINATION_TEMPLATES if scope == "weekly" else _STANDING_DESTINATION_TEMPLATES
        if not _path_allowed(config_path, templates):
            raise InventoryError(f"config_path {config_path!r} is not a destination the renderer or setup supports")


def add_section(
    church_folder: str | Path,
    import_id: str,
    *,
    section_id: str,
    page_start: int,
    page_end: int | None = None,
    disposition: str,
    scope: str,
    target: dict[str, str] | None = None,
    service_date: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Record or replace one supplied-section entry for an import.

    ``target`` may name a ``config_path`` (a supported field the value was
    copied into -- checked against a small explicit destination allowlist,
    not merely that some value happens to exist there), a ``text_file`` (a
    private verified text file it produced), an ``asset_path`` (a private
    extracted or staged asset file it produced), or a combination. A mapped
    section needs at least one; its file targets must already exist, and
    their current hash is recorded as the mapping evidence.

    A weekly-scope section needs ``service_date`` (YYYY-MM-DD): the dated
    bulletin it applies to. It is not carried forward to a later week by
    itself. A standing-scope section has no service_date; it applies going
    forward until it is remapped. An omitted section needs a non-blank
    ``notes`` recording why.
    """
    root = _church_root(church_folder)
    import_id = _valid_import_id(import_id)
    if disposition not in DISPOSITIONS:
        raise InventoryError(f"disposition must be one of: {', '.join(DISPOSITIONS)}")
    if scope not in SCOPES:
        raise InventoryError(f"scope must be one of: {', '.join(SCOPES)}")
    if not section_id or not section_id.strip():
        raise InventoryError("section_id is required")
    if disposition == "omitted" and not notes.strip():
        raise InventoryError("An omitted section needs a recorded reason in notes")
    if scope == "weekly":
        if not service_date:
            raise InventoryError("A weekly section needs service_date (YYYY-MM-DD)")
        try:
            date.fromisoformat(service_date)
        except ValueError as exc:
            raise InventoryError("service_date must be YYYY-MM-DD") from exc
    elif service_date is not None:
        raise InventoryError("A standing section has no service_date; it is not tied to one week")

    manifest = _load_manifest(root, import_id)
    page_end = page_end or page_start
    if not (1 <= page_start <= page_end <= manifest["source"]["page_count"]):
        raise InventoryError("page_start/page_end must fall within the imported page range")
    target = dict(target or {})
    _validate_target(target, scope)
    if disposition == "mapped" and not target:
        raise InventoryError("A mapped section needs a target config path, text file, or asset path")

    evidence: dict[str, str] = {}
    if "text_file" in target:
        text_path = _owned(root, target["text_file"])
        if not text_path.is_file():
            raise InventoryError(f"Mapped text file does not exist yet: {target['text_file']}")
        evidence["text_sha256"] = _hash_file(text_path)
    if "asset_path" in target:
        asset_path = _owned(root, target["asset_path"])
        if not asset_path.is_file():
            raise InventoryError(f"Mapped asset file does not exist yet: {target['asset_path']}")
        evidence["asset_sha256"] = _hash_file(asset_path)

    inventory = _load_inventory(root, import_id)
    entry = {
        "section_id": section_id.strip(),
        "page_start": page_start,
        "page_end": page_end,
        "disposition": disposition,
        "scope": scope,
        "service_date": service_date,
        "target": target,
        "evidence": evidence,
        "visual_review_required": "asset_path" in target,
        "notes": notes,
        "recorded_on": date.today().isoformat(),
    }
    remaining = [s for s in inventory["sections"] if s["section_id"] != entry["section_id"]]
    inventory["sections"] = sorted(remaining + [entry], key=lambda s: (s["page_start"], s["section_id"]))
    # Any section write invalidates a prior review-complete attestation --
    # see mark_review_complete.
    inventory["review"] = {"complete": False}
    _save_inventory(root, import_id, inventory)
    return entry


def mark_review_complete(church_folder: str | Path, import_id: str, *, note: str) -> dict[str, Any]:
    """Record that the agent has gone through every page of this import and
    accounted for it as a recorded section.

    This is the agent's own bookkeeping record, not a computed coverage
    proof and not a pastor or church approval of any kind -- individual
    unresolved or omitted decisions still need the pastor's actual answer
    through the normal onboarding/bulletin conversation, and final bulletin
    approval remains the separate `bulletin finalize` step. Recording this
    does not make any individual section correct by itself. It exists so
    that recording only one section -- a logo, say -- can never silently let
    the rest of an imported bulletin pass unreviewed:
    :func:`validate_for_production` requires this record, current for the
    sections actually recorded, before it will pass an import. Any later
    :func:`add_section` call invalidates it until it is recorded again.
    """
    root = _church_root(church_folder)
    import_id = _valid_import_id(import_id)
    if not note or not note.strip():
        raise InventoryError("mark_review_complete needs a note describing what was reviewed")
    inventory = _load_inventory(root, import_id)
    if not inventory["sections"]:
        raise InventoryError("Record at least one section before marking review complete")
    inventory["review"] = {
        "complete": True,
        "note": note.strip(),
        "reviewed_on": date.today().isoformat(),
        "sections_fingerprint": _sections_fingerprint(inventory["sections"]),
    }
    _save_inventory(root, import_id, inventory)
    return inventory["review"]


def read_inventory(church_folder: str | Path, import_id: str) -> dict[str, Any]:
    root = _church_root(church_folder)
    return _load_inventory(root, _valid_import_id(import_id))


def list_inventories(church_folder: str | Path) -> list[dict[str, Any]]:
    root = _church_root(church_folder)
    imports_root = root / IMPORT_ROOT
    if not imports_root.is_dir():
        return []
    results = []
    for import_dir in sorted(p for p in imports_root.iterdir() if p.is_dir() and _IMPORT_ID_RE.match(p.name)):
        if (import_dir / "manifest.json").is_file():
            results.append(_load_inventory(root, import_dir.name))
    return results


def _known_import_ids(root: Path) -> list[str]:
    imports_root = root / IMPORT_ROOT
    if not imports_root.is_dir():
        return []
    return sorted(p.name for p in imports_root.iterdir() if p.is_dir() and _IMPORT_ID_RE.match(p.name))


def _confined_source_path(root: Path, manifest: dict[str, Any]) -> Path | None:
    """Resolve manifest['source']['path'] without ever letting a tampered
    absolute or escaping value bypass the church folder."""
    try:
        return _owned(root, manifest["source"]["path"])
    except InventoryError:
        return None


def _check_target_file(
    root: Path, import_id: str, section: dict[str, Any], relative_path: str,
    recorded_hash: str | None, kind: str, errors: list[dict[str, Any]],
) -> str | None:
    """Check a mapped file still exists and matches its recorded hash.
    Returns the file's current hash (for the production fingerprint), or
    None when the file is missing or unreadable."""
    try:
        path = _owned(root, relative_path)
    except InventoryError:
        path = None
    if path is None or not path.is_file():
        errors.append({
            "import_id": import_id, "section_id": section["section_id"], "code": f"missing_{kind}",
            "message": f"Mapped {kind} file no longer exists: {relative_path}",
        })
        return None
    current_hash = _hash_file(path)
    if recorded_hash and current_hash != recorded_hash:
        errors.append({
            "import_id": import_id, "section_id": section["section_id"], "code": f"{kind}_changed",
            "message": f"Mapped {kind} file changed since it was recorded: {relative_path}",
        })
    return current_hash


def check_mapping_integrity(
    church_folder: str | Path, import_id: str | None = None, *, service_date: str | None = None,
) -> dict[str, Any]:
    """Informative pre-render check for onboarding. Never blocks.

    A church with no supplied bulletin, or one with sections still pending a
    pastor's decision, is never blocked: unresolved sections are reported for
    visibility, not returned as errors. Pass ``service_date`` to also see
    which weekly sections do not apply to that date; omit it to see every
    recorded section regardless of date.
    """
    root = _church_root(church_folder)
    import_ids = [_valid_import_id(import_id)] if import_id is not None else _known_import_ids(root)

    errors: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    visual_review: list[dict[str, Any]] = []
    excluded_other_week: list[dict[str, Any]] = []
    checked = 0

    for iid in import_ids:
        try:
            manifest = _load_manifest(root, iid)
            inventory = _load_inventory(root, iid)
        except InventoryError as exc:
            errors.append({"import_id": iid, "section_id": None, "code": "malformed_record", "message": str(exc)})
            continue
        checked += 1
        source_path = _confined_source_path(root, manifest)
        if source_path is None or not source_path.is_file() or _hash_file(source_path) != manifest["source"]["sha256"]:
            errors.append({
                "import_id": iid, "section_id": None, "code": "source_changed",
                "message": "The retained source snapshot no longer matches its recorded hash",
            })

        for section in inventory["sections"]:
            if service_date is not None and section["scope"] == "weekly" and section.get("service_date") != service_date:
                excluded_other_week.append({"import_id": iid, **section})
                continue
            if section["disposition"] == "unresolved":
                unresolved.append({"import_id": iid, **section})
                continue
            if section["disposition"] == "omitted":
                continue
            target = section.get("target") or {}
            evidence = section.get("evidence") or {}
            if "text_file" in target:
                _check_target_file(root, iid, section, target["text_file"], evidence.get("text_sha256"), "text", errors)
            if "asset_path" in target:
                _check_target_file(root, iid, section, target["asset_path"], evidence.get("asset_sha256"), "asset", errors)
                visual_review.append({
                    "import_id": iid, "section_id": section["section_id"],
                    "page_start": section["page_start"], "page_end": section["page_end"],
                    "asset_path": target["asset_path"],
                })

    return {
        "status": "invalid" if errors else "valid",
        "stage": "pre_render",
        "service_date": service_date,
        "imports_checked": checked,
        "errors": errors,
        "unresolved_sections": unresolved,
        "excluded_other_week": excluded_other_week,
        "visual_review": visual_review,
        "note": _MAPPING_INTEGRITY_NOTE,
    }


# Stable name production code should treat as the informative onboarding check.
validate_inventory = check_mapping_integrity


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    import yaml
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _load_standing_config(root: Path) -> dict[str, Any]:
    church = _load_yaml_dict(root / "church.yaml")
    pointer = str(church.get("worship_profile") or "worship/profile.yaml")
    try:
        profile = _load_yaml_dict(_owned(root, pointer))
    except InventoryError:
        profile = {}
    brand_path = root / "brand.json"
    brand: dict[str, Any] = {}
    if brand_path.is_file():
        try:
            loaded = json.loads(brand_path.read_text(encoding="utf-8"))
            brand = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            brand = {}
    merged = dict(church)
    merged["worship_profile"] = profile
    merged["brand"] = brand
    return merged


def _resolve_value(container: Any, dotted_path: str) -> tuple[bool, Any]:
    current = container
    for segment in dotted_path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return False, None
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit() or int(segment) >= len(current):
                return False, None
            current = current[int(segment)]
        else:
            return False, None
    return True, current


def _confined_relative(root: Path, value: Any) -> str | None:
    """Resolve a reference value (relative or absolute) to its church-root-
    relative POSIX form, so an absolute and a relative spelling of the same
    file compare equal. Pure path arithmetic for comparison only -- it never
    touches the filesystem and is not a substitute for the symlink-safe
    confinement a read or write goes through elsewhere. Returns None for a
    value that isn't a usable path or doesn't resolve inside the church."""
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    try:
        parts = candidate.parts if not candidate.is_absolute() else Path(os.path.relpath(candidate, root)).parts
    except ValueError:
        return None
    if ".." in parts:
        return None
    return Path(*parts).as_posix() if parts else None


def _collect_hymn_like_references(root: Path, container: dict[str, Any]) -> set[str]:
    """Image/images references from the renderer's actual bounded hymn and
    service_music slots only. A key outside those slots (a typo, or a fake
    slot invented to sneak a path past this check) is never inspected, even
    if the JSON otherwise looks plausible."""
    values: set[str] = set()
    for group_key, slots in (("hymns", _HYMN_SLOTS), ("service_music", _SERVICE_MUSIC_SLOTS)):
        group = container.get(group_key)
        if not isinstance(group, dict):
            continue
        for slot_name in slots:
            slot = group.get(slot_name)
            if not isinstance(slot, dict):
                continue
            candidates = [slot.get("image")] + list(slot.get("images") or [])
            for item in candidates:
                normalized = _confined_relative(root, item)
                if normalized:
                    values.add(normalized)
    announcements = container.get("announcements")
    if isinstance(announcements, list):
        for entry in announcements:
            if not isinstance(entry, dict):
                continue
            candidates = [entry.get("image")] + list(entry.get("images") or [])
            for item in candidates:
                normalized = _confined_relative(root, item)
                if normalized:
                    values.add(normalized)
    return values


def _collect_source_paths(root: Path, container: dict[str, Any]) -> set[str]:
    """Liturgy/worship-profile source file references: weekly resolved
    liturgy.sources/liturgy.files (private service-variant or Lutheran unit
    files), or standing worship_profile.sources."""
    values: set[str] = set()
    for holder_key in ("liturgy", "worship_profile"):
        holder = container.get(holder_key)
        if not isinstance(holder, dict):
            continue
        for group_key in ("sources", "files"):
            group = holder.get(group_key)
            if isinstance(group, dict):
                for value in group.values():
                    normalized = _confined_relative(root, value)
                    if normalized:
                        values.add(normalized)
    return values


def _collect_brand_references(root: Path, brand: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    logo = brand.get("logo")
    if isinstance(logo, dict):
        for value in logo.values():
            normalized = _confined_relative(root, value)
            if normalized:
                values.add(normalized)
    qr = brand.get("qr")
    if isinstance(qr, dict):
        for entry in qr.values():
            if isinstance(entry, dict):
                normalized = _confined_relative(root, entry.get("image"))
                if normalized:
                    values.add(normalized)
    return values


def validate_for_production(church_folder: str | Path, bulletin: dict[str, Any]) -> dict[str, Any]:
    """The blocking pre-render check the bulletin workflow should invoke
    before it relies on any imported source for ``bulletin``.

    Unlike :func:`check_mapping_integrity`, a relevant unresolved section --
    standing scope, or weekly scope with ``service_date`` matching
    ``bulletin['service']['date']`` -- blocks (status ``invalid``), as does
    an import with no recorded sections at all, an omitted section with no
    recorded reason, a destination path outside the small explicit allowlist
    this module supports, a ``config_path`` that does not resolve in the
    supplied bulletin (weekly scope) or the church's saved standing settings
    including brand.json (standing scope), or a mapped ``text_file``/
    ``asset_path`` not referenced by any supported render input (hymn or
    service_music image fields, liturgy/worship_profile source files, or the
    brand logo/QR image fields) in either the weekly bulletin or the standing
    configuration. A church with no supplied bulletin is never blocked: with
    zero imports, status is valid.

    Returns ``status``, ``errors``, ``unresolved_sections``, ``visual_review``,
    and a deterministic ``fingerprint`` over the relevant source hashes,
    section records, current target hashes, and resolved config values, so a
    caller can detect that nothing relevant changed between two calls -- and
    that it did change when mapped content was edited and re-recorded, even
    if both states are valid.
    """
    root = _church_root(church_folder)
    if not isinstance(bulletin, dict):
        raise InventoryError("bulletin must be the effective weekly bulletin object")
    service_date = str(((bulletin.get("service") or {}).get("date")) or "").strip()
    if not service_date:
        raise InventoryError("bulletin['service']['date'] is required to scope weekly sections")

    import_ids = _known_import_ids(root)
    errors: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    visual_review: list[dict[str, Any]] = []
    fingerprint_sources: list[dict[str, Any]] = []
    fingerprint_sections: list[dict[str, Any]] = []

    standing_config = _load_standing_config(root)
    brand = standing_config.get("brand") if isinstance(standing_config.get("brand"), dict) else {}
    reference_values = (
        _collect_hymn_like_references(root, bulletin)
        | _collect_source_paths(root, bulletin)
        | _collect_brand_references(root, brand)
        | _collect_source_paths(root, standing_config)
    )

    for iid in import_ids:
        try:
            manifest = _load_manifest(root, iid)
            inventory = _load_inventory(root, iid)
        except InventoryError as exc:
            errors.append({"import_id": iid, "section_id": None, "code": "malformed_record", "message": str(exc)})
            continue
        source_path = _confined_source_path(root, manifest)
        if source_path is None or not source_path.is_file() or _hash_file(source_path) != manifest["source"]["sha256"]:
            errors.append({
                "import_id": iid, "section_id": None, "code": "source_changed",
                "message": "The retained source snapshot no longer matches its recorded hash",
            })

        sections = inventory["sections"]
        review = inventory.get("review") or {"complete": False}
        review_complete = bool(review.get("complete")) and review.get("sections_fingerprint") == _sections_fingerprint(sections)
        if not sections:
            unresolved.append({
                "import_id": iid, "section_id": None, "code": "import_not_reviewed",
                "message": "This import has no recorded sections yet; review its pages before production relies on it",
            })
            continue
        if not review_complete:
            unresolved.append({
                "import_id": iid, "section_id": None, "code": "review_not_complete",
                "message": (
                    "This import has recorded sections but review has not been marked complete, "
                    "or a section changed since; call mark_review_complete after every page has "
                    "been accounted for. Recording only some sections (a logo, say) is not enough."
                ),
            })
            # Still check the recorded sections below so every problem
            # surfaces at once; review_not_complete already guarantees
            # status "invalid" regardless of what else is found.

        relevant_sections = [
            section for section in sections
            if section["scope"] == "standing" or section.get("service_date") == service_date
        ]
        if relevant_sections:
            fingerprint_sources.append({"import_id": iid, "source_sha256": manifest["source"]["sha256"]})

        for section in relevant_sections:
            fingerprint_entry: dict[str, Any] = {
                "import_id": iid, "section_id": section["section_id"], "disposition": section["disposition"],
                "scope": section["scope"], "service_date": section.get("service_date"),
                "target": section.get("target") or {}, "notes": section.get("notes") or "",
            }
            fingerprint_sections.append(fingerprint_entry)

            if section["disposition"] == "unresolved":
                unresolved.append({"import_id": iid, **section})
                continue
            if section["disposition"] == "omitted":
                if not str(section.get("notes") or "").strip():
                    errors.append({
                        "import_id": iid, "section_id": section["section_id"], "code": "omitted_without_reason",
                        "message": "An omitted section needs a recorded reason",
                    })
                continue

            target = section.get("target") or {}
            evidence = section.get("evidence") or {}
            if not target:
                errors.append({
                    "import_id": iid, "section_id": section["section_id"], "code": "missing_target",
                    "message": "A mapped section has no target",
                })
            if "config_path" in target:
                templates = _WEEKLY_DESTINATION_TEMPLATES if section["scope"] == "weekly" else _STANDING_DESTINATION_TEMPLATES
                container = bulletin if section["scope"] == "weekly" else standing_config
                config_path = target["config_path"]
                if not _path_allowed(config_path, templates):
                    errors.append({
                        "import_id": iid, "section_id": section["section_id"], "code": "unsupported_destination",
                        "message": f"{config_path} is not a destination the renderer or setup supports",
                    })
                else:
                    found, value = _resolve_value(container, config_path)
                    if not found:
                        errors.append({
                            "import_id": iid, "section_id": section["section_id"], "code": "config_path_not_found",
                            "message": f"{config_path} does not resolve in the supplied {section['scope']} configuration",
                        })
                    fingerprint_entry["config_resolved_value"] = value if found else None
            if "text_file" in target:
                current_hash = _check_target_file(root, iid, section, target["text_file"], evidence.get("text_sha256"), "text", errors)
                fingerprint_entry["text_current_sha256"] = current_hash
                if _confined_relative(root, target["text_file"]) not in reference_values:
                    errors.append({
                        "import_id": iid, "section_id": section["section_id"], "code": "text_not_referenced",
                        "message": f"{target['text_file']} is mapped but not referenced by any supported render input",
                    })
            if "asset_path" in target:
                current_hash = _check_target_file(root, iid, section, target["asset_path"], evidence.get("asset_sha256"), "asset", errors)
                fingerprint_entry["asset_current_sha256"] = current_hash
                if _confined_relative(root, target["asset_path"]) not in reference_values:
                    errors.append({
                        "import_id": iid, "section_id": section["section_id"], "code": "asset_not_referenced",
                        "message": f"{target['asset_path']} is mapped but not referenced by any supported render input",
                    })
                visual_review.append({
                    "import_id": iid, "section_id": section["section_id"],
                    "page_start": section["page_start"], "page_end": section["page_end"],
                    "asset_path": target["asset_path"],
                })

    fingerprint = hashlib.sha256(json.dumps(
        {
            "service_date": service_date,
            "sources": sorted(fingerprint_sources, key=lambda s: s["import_id"]),
            "sections": sorted(fingerprint_sections, key=lambda s: (s["import_id"], s["section_id"])),
        },
        sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()

    return {
        "status": "invalid" if errors or unresolved else "valid",
        "stage": "pre_render",
        "service_date": service_date,
        "imports_checked": len(import_ids),
        "errors": errors,
        "unresolved_sections": unresolved,
        "visual_review": visual_review,
        "fingerprint": fingerprint,
        "note": _PRODUCTION_VALIDATION_NOTE,
    }


def _native_pdftotext() -> str:
    found = shutil.which("pdftotext")
    if not found:
        raise InventoryError("pdftotext is not on PATH; run the runtime doctor's native install plan")
    return found


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.replace("*", "").replace("_", "").split())


def _first_nonblank_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("<!--"):
            return stripped
    return ""


def check_rendered_text(
    church_folder: str | Path,
    import_id: str,
    section_id: str,
    rendered_pdf: str | Path,
    *,
    excerpt: str | None = None,
) -> dict[str, Any]:
    """Optional post-render check: does a rendered bulletin PDF contain a
    mapped section's expected text?

    Text only, and never a substitute for :func:`validate_for_production`. A
    match does not by itself prove correct placement, and it never covers a
    mapped image, logo, or music asset; those stay a required human visual
    review (see the ``visual_review`` list returned by
    :func:`validate_for_production`).
    """
    root = _church_root(church_folder)
    import_id = _valid_import_id(import_id)
    inventory = _load_inventory(root, import_id)
    section = next((s for s in inventory["sections"] if s["section_id"] == section_id), None)
    if section is None:
        raise InventoryError(f"No recorded section {section_id!r} for import {import_id}")
    target = section.get("target") or {}
    if section["disposition"] != "mapped" or "text_file" not in target:
        raise InventoryError("check_rendered_text applies only to a mapped section with a text_file target")
    text_path = _owned(root, target["text_file"])
    candidate = _normalize_whitespace(excerpt or _first_nonblank_line(text_path.read_text(encoding="utf-8")))
    if not candidate:
        raise InventoryError("Supply excerpt; the mapped text file has no usable first line")
    rendered_path = _owned_read(root, rendered_pdf)
    if not rendered_path.is_file():
        raise InventoryError(f"Rendered bulletin not found: {rendered_pdf}")
    completed = subprocess.run(
        [_native_pdftotext(), str(rendered_path), "-"], capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise InventoryError(f"pdftotext failed: {completed.stderr.strip()}")
    found = candidate in _normalize_whitespace(completed.stdout)
    return {
        "status": "found" if found else "not_found",
        "stage": "post_render",
        "import_id": import_id,
        "section_id": section_id,
        "excerpt": candidate,
        "note": _RENDERED_TEXT_NOTE,
    }
