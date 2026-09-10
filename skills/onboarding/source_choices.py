"""Deterministic, source-backed checks for a few high-stakes worship choices.

Reads the retained import manifest's per-page text (already extracted by
bulletin_import.py) for a narrow set of unambiguous, deterministic anchors:
an explicit Eucharistic Prayer letter, a Book of Common Prayer Great
Thanksgiving page anchor, the closing hymn's position relative to the final
Dismissal heading, and the Gospel acclamation's "Lord" or "Savior" wording.
Episcopal Rite II conventions only.

This module never decides an unclear case. A page with no anchor, two
disagreeing anchors, or no clean closing-hymn candidate stays "unknown" or
"ambiguous"; it is never turned into a guessed value. It also never compares
against or writes standing configuration; callers (church_setup.py) own that.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


EP_LABEL_RE = re.compile(r"\bEucharistic\s+Prayer\s*([ABCD])\b", re.I)
EP_PAGE_ANCHOR_RE = re.compile(r"\b(?:BCP|Book of Common Prayer|page|p\.)\s*,?\s*(361|367|369|372)\b", re.I)
GREAT_THANKSGIVING_RE = re.compile(r"\bGreat\s+Thanksgiving\b", re.I)
EP_PAGE_MAP = {"361": "A", "367": "B", "369": "C", "372": "D"}
# A label like "next week's Eucharistic Prayer will be B" is a narrative
# reference, not the actual service; excluded so it cannot outrank the real
# celebration on the same page. This exclusion does not require Great
# Thanksgiving context: an explicit letter is credible on its own (some
# bulletins print "Eucharistic Prayer C" without ever printing the words
# "Great Thanksgiving"), and the narrative filter alone guards against a
# future-reference false positive.
EP_NARRATIVE_RE = re.compile(r"\b(next week|coming week|will (?:be|use)|upcoming)\b", re.I)
# A pdftotext column reflow can place the printed BCP page citation many
# lines after the "Great Thanksgiving" heading, past the whole Sursum Corda
# dialogue -- confirmed against a real retained import. A fixed nearby-line
# window cannot both catch that and reject an unrelated page-number mention
# elsewhere on the page, so the anchor instead requires the Sursum Corda's
# own distinctive response line as corroboration that the page anchor
# actually belongs to the Great Thanksgiving, not proximity to the heading.
# \s+ (not a literal space) between every word: pdftotext line-wraps a
# phrase mid-sentence, so a literal space would miss it exactly where the
# real column reflow happens.
EP_SURSUM_CORDA_RESPONSE_RE = re.compile(
    r"\bit\s+is\s+right\s+to\s+give\s+(?:god\s+|him\s+|our\s+)?thanks\s+and\s+praise\b", re.I
)
# Body text unique to one prayer, verified against a real retained sample
# where pdftotext extracted no "Eucharistic Prayer" label or page number at
# all for that page (the printed heading is evidently not selectable text).
# Only Prayer C's opening is included: it is confirmed unique BCP 1979
# wording. A/B/D are deliberately not fingerprinted here, since getting an
# unverified liturgical phrase wrong would be worse than staying unknown.
EP_BODY_FINGERPRINTS = {
    "C": re.compile(r"\bthe\s+vast\s+expanse\s+of\s+interstellar\s+space\b", re.I),
}

GOSPEL_RE = re.compile(r"\bThe\s+Holy\s+Gospel\s+of\s+our\s+(Lord|Savior)\s+Jesus\s+Christ\b", re.I)

DISMISSAL_RE = re.compile(r"^\s*(?:THE\s+)?DISMISSAL\b", re.I)
# Unambiguous on their own: a bulletin never uses these words for the
# opening hymn. "Hymn in Procession" is genuinely ambiguous (commonly used
# for both the opening and closing hymn), so it additionally needs evidence
# of final-service context; see _closing_hymn_position_observation.
UNAMBIGUOUS_CLOSING_HYMN_RE = re.compile(r"^\s*(Closing Hymn|Recessional Hymn|Retiring Hymn)\b(.*)$", re.I)
AMBIGUOUS_PROCESSIONAL_HYMN_RE = re.compile(r"^\s*(Hymn in Procession|Hymn at the Procession)\b(.*)$", re.I)
LATE_SERVICE_ANCHOR_RE = re.compile(r"\b(Post[- ]?Communion Prayer|The Blessing|Blessing)\b", re.I)

FIELD_LABELS = {
    "eucharistic_prayer": "the Eucharistic Prayer",
    "closing_hymn_position": "whether the closing hymn is sung before or after the dismissal",
    "gospel_acclamation": "the Gospel acclamation wording (Lord or Savior)",
}


def _snippet(text: str, limit: int = 90) -> str:
    value = " ".join(text.split())
    return value if len(value) <= limit else value[:limit].rstrip() + "..."


def _page_text(root: Path, page: dict[str, Any]) -> str:
    """Read one page's retained text, refusing a path escape or a mismatch
    against the manifest's own recorded text_sha256 (when present) rather
    than trusting file content that no longer matches what was extracted."""
    if not isinstance(page, dict):
        return ""
    text_path = page.get("text_path")
    if not isinstance(text_path, str) or not text_path:
        return ""
    candidate = Path(text_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return ""
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return ""
    if not resolved.is_file():
        return ""
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    expected_hash = page.get("text_sha256")
    if isinstance(expected_hash, str) and expected_hash:
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_hash:
            return ""
    return text


def _manifest_pages(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict) and isinstance(page.get("page"), int)]


def _aggregate(candidates: list[tuple[int, str, str]]) -> dict[str, Any]:
    """Combine (page, value, evidence) candidates into one field observation."""
    if not candidates:
        return {"value": None, "confidence": "unknown"}
    distinct = {value for _, value, _ in candidates}
    if len(distinct) > 1:
        return {
            "value": None,
            "confidence": "ambiguous",
            "evidence": "; ".join(f"page {page}: {value} ({evidence})" for page, value, evidence in candidates),
        }
    page, value, evidence = candidates[0]
    return {"value": value, "confidence": "high", "page": page, "evidence": evidence}


def _eucharistic_prayer_observation(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    candidates: list[tuple[int, str, str]] = []
    for page in _manifest_pages(manifest):
        page_number = page["page"]
        text = _page_text(root, page)
        if not text:
            continue
        found: list[tuple[str, str]] = []
        # An explicit letter is credible on its own; only a narrative aside
        # ("next week's Eucharistic Prayer will be B") is excluded, so it
        # cannot outrank the service actually being celebrated.
        for match in EP_LABEL_RE.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            line = text[line_start: line_end if line_end != -1 else len(text)]
            if EP_NARRATIVE_RE.search(line):
                continue
            found.append((match.group(1).upper(), f"labeled 'Eucharistic Prayer {match.group(1).upper()}'"))
        # A BCP page anchor only counts alongside the Sursum Corda's own
        # response line ("It is right to give... thanks and praise"), which
        # corroborates the anchor actually belongs to this Great Thanksgiving
        # rather than being an unrelated page-number mention elsewhere.
        if GREAT_THANKSGIVING_RE.search(text) and EP_SURSUM_CORDA_RESPONSE_RE.search(text):
            for anchor in EP_PAGE_ANCHOR_RE.finditer(text):
                letter = EP_PAGE_MAP.get(anchor.group(1))
                if letter:
                    found.append((letter, f"Great Thanksgiving with a BCP {anchor.group(1)} page anchor"))
        for letter, fingerprint in EP_BODY_FINGERPRINTS.items():
            match = fingerprint.search(text)
            if match:
                found.append((letter, f"prayer body text unique to Prayer {letter}: '{_snippet(match.group(0))}'"))
        for value, evidence in found:
            candidates.append((page_number, value, evidence))
    return _aggregate(candidates)


def _gospel_acclamation_observation(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    candidates: list[tuple[int, str, str]] = []
    for page in _manifest_pages(manifest):
        page_number = page["page"]
        text = _page_text(root, page)
        if not text:
            continue
        for match in GOSPEL_RE.finditer(text):
            value = match.group(1).lower()
            candidates.append((page_number, value, _snippet(match.group(0))))
    return _aggregate(candidates)


def _closing_hymn_position_observation(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    ordered_lines: list[tuple[int, str]] = []  # (page, line)
    for page in sorted(_manifest_pages(manifest), key=lambda item: item["page"]):
        text = _page_text(root, page)
        if not text:
            continue
        for line in text.splitlines():
            if line.strip():
                ordered_lines.append((page["page"], line))

    dismissal_indexes = [index for index, (_, line) in enumerate(ordered_lines) if DISMISSAL_RE.match(line)]
    if not dismissal_indexes:
        return {"value": None, "confidence": "unknown"}
    final_dismissal_index = dismissal_indexes[-1]
    final_dismissal_page = ordered_lines[final_dismissal_index][0]
    late_service_indexes = [
        index for index, (_, line) in enumerate(ordered_lines) if LATE_SERVICE_ANCHOR_RE.search(line)
    ]

    all_candidates: list[tuple[int, int, re.Match[str]]] = []
    for index, (page, line) in enumerate(ordered_lines):
        match = UNAMBIGUOUS_CLOSING_HYMN_RE.match(line)
        if match:
            all_candidates.append((index, page, match))
            continue
        match = AMBIGUOUS_PROCESSIONAL_HYMN_RE.match(line)
        # "Hymn in Procession" only counts as the closing hymn when a
        # late-service anchor (the Blessing or Post-Communion Prayer)
        # already occurred before it; otherwise a compact one-page service
        # would mistake its own opening processional for the closing one.
        if match and any(anchor_index < index for anchor_index in late_service_indexes):
            all_candidates.append((index, page, match))

    # A candidate on the same page as the final Dismissal heading, or the
    # page immediately before or after it, is close enough to be that
    # heading's actual closing hymn; a candidate many pages away is not a
    # signal for this field and must not be guessed.
    hymn_candidates = [item for item in all_candidates if abs(item[1] - final_dismissal_page) <= 1]
    if not hymn_candidates:
        return {"value": None, "confidence": "unknown"}

    nearest = min(hymn_candidates, key=lambda item: abs(item[0] - final_dismissal_index))
    tied = [item for item in hymn_candidates if abs(item[0] - final_dismissal_index) == abs(nearest[0] - final_dismissal_index)]
    if len(tied) > 1:
        return {
            "value": None,
            "confidence": "ambiguous",
            "evidence": f"{len(tied)} equally likely closing-hymn headings near the final dismissal on page {final_dismissal_page}",
        }
    hymn_index, hymn_page, hymn_match = nearest
    value = "before_dismissal" if hymn_index < final_dismissal_index else "after_dismissal"
    return {
        "value": value,
        "confidence": "high",
        "page": hymn_page,
        "evidence": f"'{_snippet(hymn_match.group(0))}' on page {hymn_page}, final Dismissal heading on page {final_dismissal_page}",
    }


OBSERVERS = {
    "eucharistic_prayer": _eucharistic_prayer_observation,
    "closing_hymn_position": _closing_hymn_position_observation,
    "gospel_acclamation": _gospel_acclamation_observation,
}


def observe_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return one observation per known field for a single retained import."""
    return {field: observer(root, manifest) for field, observer in OBSERVERS.items()}


def aggregate_imports(
    observations_by_import: dict[str, dict[str, dict[str, Any]]],
    sha256_by_import: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Combine per-import observations across every retained import.

    Two imports that both give the same high-confidence value for a field
    agree. Two imports that disagree make that field ambiguous rather than
    picking whichever import happens to sort first. ``sha256_by_import``
    maps each import_id to its full source PDF sha256, since an override is
    tied to the actual source hash, not the shortened import_id.
    """
    aggregated: dict[str, dict[str, Any]] = {}
    for field in OBSERVERS:
        per_import = [
            (import_id, observations.get(field, {}))
            for import_id, observations in observations_by_import.items()
        ]
        high_confidence = [
            (import_id, item) for import_id, item in per_import if item.get("confidence") == "high"
        ]
        has_ambiguous_import = any(item.get("confidence") == "ambiguous" for _, item in per_import)
        if not high_confidence:
            aggregated[field] = {"value": None, "confidence": "ambiguous" if has_ambiguous_import else "unknown"}
            continue
        distinct = {item["value"] for _, item in high_confidence}
        # A contrary sample stays a reason to distrust the field even when
        # it is itself internally ambiguous rather than a clean disagreeing
        # value; it must not be silently dropped in favor of an agreeing one.
        if len(distinct) > 1 or has_ambiguous_import:
            aggregated[field] = {
                "value": None,
                "confidence": "ambiguous",
                "evidence": "; ".join(
                    f"import {import_id[:8]} page {item.get('page')}: {item.get('value')}"
                    for import_id, item in high_confidence
                ) or "a contrary or internally ambiguous sample was also retained",
            }
            continue
        _, item = high_confidence[0]
        source_sha256s = [
            sha256_by_import[import_id] for import_id, _ in high_confidence if import_id in sha256_by_import
        ]
        aggregated[field] = {**item, "source_sha256s": source_sha256s}
    return aggregated


def find_contradictions(
    aggregated: dict[str, dict[str, Any]],
    standing_defaults: dict[str, Any],
    overrides: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare unambiguous source observations against the saved standing choice.

    An override suppresses one contradiction only while it is current: its
    recorded source_sha256 must be one of the imports that produced the
    agreed observation, and its recorded value must equal the standing value
    being defended. Either changing means the acknowledgement is stale.

    This function re-checks an override's own shape at read time (not just
    at the update_standing write time in church_setup.py) -- profile.yaml is
    a plain file a hand edit or a bug could leave malformed, and a malformed
    or reason-less record must never be trusted to silently suppress a real
    contradiction.
    """
    contradictions = []
    for field, observation in aggregated.items():
        if observation.get("confidence") != "high":
            continue
        source_value = observation["value"]
        standing_value = standing_defaults.get(field)
        if not standing_value or str(standing_value).strip() == str(source_value).strip():
            continue
        override = overrides.get(field) if isinstance(overrides, dict) else None
        if (
            isinstance(override, dict)
            and isinstance(override.get("source_sha256"), str)
            and isinstance(override.get("value"), str)
            and isinstance(override.get("reason"), str)
            and override["reason"].strip()
        ):
            observed_sha256s = observation.get("source_sha256s", [])
            if (
                override["source_sha256"] in observed_sha256s
                and override["value"].strip() == str(standing_value).strip()
            ):
                continue
        contradictions.append({
            "field": field,
            "field_label": FIELD_LABELS.get(field, field),
            "source_value": source_value,
            "standing_value": standing_value,
            "page": observation.get("page"),
            "evidence": observation.get("evidence"),
        })
    return contradictions


__all__ = ["observe_manifest", "aggregate_imports", "find_contradictions", "OBSERVERS", "FIELD_LABELS"]
