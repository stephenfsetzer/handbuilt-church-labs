from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_church(root: Path) -> Path:
    church = root / "public-test-parish"
    shutil.copytree(REPO_ROOT / "scaffold" / "church-folder", church)
    (church / "church.yaml").write_text(
        """church:
  name: Public Test Parish
  short_name: Test Parish
  tradition: Episcopal
  city: Example City
  address: 10 Test Lane
  website: test.invalid
  regular_services:
    - day: Sunday
      time: "10:00"
lectionary:
  system: RCL
  track: Track 2
  translation: Synthetic Test Translation
  optional_verses: appointed
  authorities:
    - name: Synthetic Lectionary Calendar A
      url: https://lectionary-a.invalid/
    - name: Synthetic Lectionary Calendar B
      url: https://lectionary-b.invalid/
sermon:
  selection_mode: lectionary
  primary_text: gospel
  research_preferences:
    priority_voices: []
    preferred_resources: []
    voices_to_avoid: []
    language_depth: plain
    human_sciences: true
    contemporary_context: true
    additional_domain: ""
people:
  pastor: The Rev. Test Pastor
  celebrant: The Rev. Test Pastor
setup:
  schema_version: 3
  onboarded_on: "2026-08-26"
  plugin: handbuilt-church-labs
""",
        encoding="utf-8",
    )
    brand = json.loads((church / "brand.json").read_text(encoding="utf-8"))
    brand.update({
        "logo_status": "none",
        "colors_status": "confirmed",
        "church": {
            "name": "Public Test Parish",
            "public_name": "Public Test Parish",
            "short_name": "Test Parish",
            "address": "10 Test Lane, Example City",
            "website": "test.invalid",
            "service_line": "Holy Eucharist, Rite II",
            "service_time": "Sundays at 10:00 am",
        },
        "logo": {},
        "colors": {
            "ink": "#1a1a1a",
            "accent": "#425b76",
            "accent_deep": "#27384a",
            "paper": "#ffffff",
            "rubric_red": "#7f3030",
        },
        "texts": {},
    })
    (church / "brand.json").write_text(json.dumps(brand, indent=2) + "\n", encoding="utf-8")
    return church


def make_nonlectionary_church(root: Path) -> Path:
    church = make_church(root)
    config = church / "church.yaml"
    text = config.read_text(encoding="utf-8")
    text = text.replace("  system: RCL", "  system: none")
    text = text.replace("  selection_mode: lectionary", "  selection_mode: pastor_selected")
    text = text.replace("  primary_text: gospel", "  primary_text: selected")
    config.write_text(text, encoding="utf-8")
    return church


def verified_source() -> dict[str, str]:
    return {
        "label": "Synthetic workflow fixture",
        "location": "tests/fixtures/september-20",
        "verified_on": "2026-08-26",
    }


def reading_selection() -> dict:
    return {
        "selection_mode": "lectionary",
        "service_date": "2026-09-20",
        "occasion": "Synthetic Proper",
        "lectionary_system": "RCL",
        "year": "A",
        "track": "Track 2",
        "optional_verses_policy": "appointed",
        "optional_verses": "none",
        "translation": "Synthetic Test Translation",
        "readings": {
            "first": "Test Book 1:1-3",
            "psalm": "Test Psalm 1",
            "second": "Test Letter 2:1-4",
            "gospel": "Test Gospel 3:1-5",
        },
    }


def pastor_selected_reading_selection() -> dict:
    return {
        "selection_mode": "pastor_selected",
        "service_date": "2026-09-20",
        "occasion": "Sunday worship",
        "translation": "Synthetic Test Translation",
        "readings": {
            "selected": "Test Gospel 4:1-8",
        },
    }


def reading_sources(selection: dict | None = None) -> list[dict]:
    selection = selection or reading_selection()
    return [
        {
            "label": "Synthetic Lectionary Calendar A",
            "url": f"https://lectionary-a.invalid/{selection['service_date']}",
            "host": "lectionary-a.invalid",
            "retrieved_at": "2026-08-26T12:00:00+00:00",
            "verified_on": "2026-08-26",
            "result": "verified",
            "supports": "service date, occasion, year, track, and readings",
            "observed_selection": selection,
        },
        {
            "label": "Synthetic Lectionary Calendar B",
            "url": f"https://lectionary-b.invalid/{selection['service_date']}",
            "host": "lectionary-b.invalid",
            "retrieved_at": "2026-08-26T12:01:00+00:00",
            "verified_on": "2026-08-26",
            "result": "verified",
            "supports": "service date, occasion, year, track, and readings",
            "observed_selection": selection,
        },
    ]


def reading_metadata(selection: dict | None = None) -> dict:
    selection = selection or reading_selection()
    return {"selection": selection, "sources": reading_sources(selection)}


def pastor_selected_reading_sources(selection: dict | None = None) -> list[dict]:
    selection = selection or pastor_selected_reading_selection()
    return [
        {
            "label": "Synthetic Published Bible",
            "url": "https://bible.invalid/test-gospel-4",
            "host": "bible.invalid",
            "retrieved_at": "2026-08-26T12:00:00+00:00",
            "verified_on": "2026-08-26",
            "result": "verified",
            "supports": "selected passage citation and translation",
            "observed_text": selection["readings"]["selected"],
            "observed_translation": selection["translation"],
        }
    ]


def pastor_selected_reading_metadata(selection: dict | None = None) -> dict:
    selection = selection or pastor_selected_reading_selection()
    return {
        "selection": selection,
        "selection_confirmation": {
            "authorship": "pastor_supplied",
            "confirmed_at": "2026-08-25T11:55:00+00:00",
            "service_date": selection["service_date"],
            "selected_text": selection["readings"]["selected"],
        },
        "sources": pastor_selected_reading_sources(selection),
    }


def research_sources() -> list[dict[str, str]]:
    return [
        {
            "source_id": f"source-{index}",
            "title": f"Synthetic Research Source {index}",
            "author": f"Fixture Author {index}",
            "publisher": f"Fixture Publisher {index}",
            "url_or_citation": f"https://research-{index}.invalid/source",
            "source_type": "synthetic primary fixture",
            "retrieved_at": f"2026-08-26T12:0{index}:00+00:00",
            "access_result": "verified",
            "claim_support": f"supports synthetic claim family {index}",
            "currency_note": "timeless synthetic fixture",
        }
        for index in range(1, 5)
    ]


def readings_content(revision: str = "one", selection: dict | None = None) -> str:
    selection = selection or reading_selection()
    service_date = datetime.fromisoformat(selection["service_date"]).strftime("%B %d, %Y")
    readings = selection["readings"]
    sources = reading_sources(selection)
    return f"""# Readings

**Service date:** {service_date}
**Occasion:** {selection['occasion']}
**Selection mode:** Lectionary
**Lectionary:** {selection['lectionary_system']}
**Year:** {selection['year']}
**Track:** {selection['track']}
**Optional verse approach:** Use appointed options
**Optional verses this week:** {selection['optional_verses']}
**Translation:** {selection['translation']}
**Primary research text:** Gospel, {readings['gospel']}
**Revision:** {revision}

- First Reading: {readings['first']}
- Psalm: {readings['psalm']}
- Second Reading: {readings['second']}
- Gospel: {readings['gospel']}

Verified against [Synthetic Lectionary Calendar A]({sources[0]['url']})
and [Synthetic Lectionary Calendar B]({sources[1]['url']}).
"""


def pastor_selected_readings_content(
    revision: str = "one",
    selection: dict | None = None,
) -> str:
    selection = selection or pastor_selected_reading_selection()
    service_date = datetime.fromisoformat(selection["service_date"]).strftime("%B %d, %Y")
    citation = selection["readings"]["selected"]
    source = pastor_selected_reading_sources(selection)[0]
    return f"""# Readings

**Service date:** {service_date}
**Occasion:** {selection['occasion']}
**Selection mode:** Pastor-selected passage
**Translation:** {selection['translation']}
**Primary research text:** Selected, {citation}
**Selection confirmation:** Pastor confirmed this passage for this service.
**Revision:** {revision}

- Selected Text: {citation}

Verified against [Synthetic Published Bible]({source['url']}).
"""


def research_brief(
    revision: str = "one",
    *,
    citation: str = "Test Gospel 3:1-5",
    selection_mode: str = "lectionary",
) -> str:
    paragraph = (
        "This synthetic analysis tests whether the workflow preserves a developed argument. "
        "It distinguishes textual observation from inference, identifies the source family "
        "supporting each claim, and leaves the pastor free to choose a center. The fixture "
        "also records a meaningful cost attached to the reading, so a complete heading alone "
        "cannot stand in for actual research. "
    )
    sections = [
        ("Research orientation", 5),
        ("Language and Historical Context", 3),
        ("Interpretive Conversations", 6),
        ("Contemporary Convergence", 2),
        ("Pastoral Applications", 2),
        ("Possible Preaching Centers", 2),
    ]
    body = [
        "# Research Brief: Synthetic Gospel",
        "",
        "**Preaching date:** September 20, 2026",
        (
            "**Liturgical setting:** Synthetic Proper"
            if selection_mode == "lectionary"
            else "**Liturgical setting:** Sunday worship"
        ),
        f"**Text:** {citation}",
        (
            "**Selection mode:** Lectionary"
            if selection_mode == "lectionary"
            else "**Selection mode:** Pastor-selected passage"
        ),
        "**Translation:** Synthetic Test Translation",
    ]
    if selection_mode == "lectionary":
        body.extend([
            "**Lectionary:** RCL, Year A",
            "**Track:** Track 2",
            "**Optional verses:** none",
            "**Reading verification:** https://lectionary-a.invalid/2026-09-20 and https://lectionary-b.invalid/2026-09-20",
        ])
    else:
        body.extend([
            "**Selection provenance:** Pastor confirmed for this service",
        ])
    body.extend([
        f"**Revision:** {revision}",
        "",
    ])
    for heading, repeats in sections:
        body.extend([f"## {heading}", ""])
        if heading == "Interpretive Conversations":
            body.extend([
                "### What does the passage ask a disciple to surrender?",
                "",
                paragraph * 2,
                "",
                "### How do judgment and promise remain together?",
                "",
                paragraph * 4,
                "",
            ])
        else:
            body.extend([paragraph * repeats, ""])
    body.extend([
        "## References",
        "",
        "- [Synthetic source 1](https://research-1.invalid/source)",
        "- [Synthetic source 2](https://research-2.invalid/source)",
        "- [Synthetic source 3](https://research-3.invalid/source)",
        "- [Synthetic source 4](https://research-4.invalid/source)",
        "",
        "## Questions for reflection",
        "",
        "Which interpretive cost deserves the most attention in the sermon?",
        "",
        "What does the pastor believe the congregation most needs to hear?",
    ])
    return "\n".join(body)


def research_metadata() -> dict:
    return {
        "research_target": {
            "role": "gospel",
            "citation": "Test Gospel 3:1-5",
            "selection_basis": "church_profile",
        },
        "sources": research_sources(),
        "scope_note": "The synthetic passage is narrow and the fixture tests contract depth only.",
    }


def pastor_selected_research_metadata() -> dict:
    metadata = research_metadata()
    metadata["research_target"] = {
        "role": "selected",
        "citation": "Test Gospel 4:1-8",
        "selection_basis": "pastor_selection",
    }
    return metadata


def bulletin_input() -> dict:
    source = verified_source()
    return {
        "template": "classic",
        "service": {
            "date": "2026-09-20",
            "occasion": "A Test Sunday in September",
            "proper": "Synthetic fixture",
            "lectionary_track": "Track 2",
            "preacher": "The Rev. Test Pastor",
            "celebrant": "The Rev. Test Pastor",
            "liturgical_color": "green",
        },
        "hymns": {
            "entrance": {"number": 1, "title": "Test Entrance", "tune": "TEST TUNE"},
            "gradual": {"number": 2, "title": "Test Gradual", "tune": "TEST TUNE"},
            "offertory": {"number": 3, "title": "Test Offertory", "tune": "TEST TUNE"},
            "communion": {"number": 4, "title": "Test Communion", "tune": "TEST TUNE"},
            "closing": {"number": 5, "title": "Test Closing", "tune": "TEST TUNE"},
        },
        "service_music": {},
        "readings": {
            "first": {
                "citation": "Test Book 1:1-3",
                "text": "The first reader speaks a short synthetic passage for layout testing.",
                "source": source,
            },
            "psalm": {
                "number": "Test Psalm 1",
                "latin_title": "Probatio",
                "text": "1 The leader reads the first half, * **and the people answer.**\n\n2 The leader continues, * **and the people respond again.**",
                "source": source,
            },
            "second": {
                "citation": "Test Letter 2:1-4",
                "text": "The second reader offers another synthetic passage for workflow testing.",
                "source": source,
            },
            "gospel": {
                "citation": "Test Gospel 3:1-5",
                "text": "The Gospel fixture is deliberately brief and contains no real liturgical claim.",
                "source": source,
            },
        },
        "collect_of_day": "Guide this test community in truthful work and careful review. Amen.",
        "proper_preface": "A synthetic preface used only to exercise pagination.",
        "announcements": [
            {"title": "Workflow Review", "text": "Please review this synthetic bulletin package."}
        ],
        "options": {
            "include_creed": True,
            "include_confession": True,
            "eucharistic_prayer": "A",
            "lords_prayer": "traditional",
        },
        "liturgy": {
            "service_plan": "episcopal-rite-ii",
            "blessing": "omit",
        },
    }


def verify_liturgy_source(church: Path, path: Path) -> None:
    """Record a synthetic church-supplied fixture as its own retained original."""
    from skills.bulletin.liturgy_sources import record_source
    record_source(church, path, source_file=path, label="Synthetic supplied worship text",
                  location="synthetic fixture", verified_on="2026-09-08", method="church_supplied")
