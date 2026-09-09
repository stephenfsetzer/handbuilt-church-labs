from __future__ import annotations

import importlib.util
import tempfile
import unittest
from tests.helpers import verify_liturgy_source
from pathlib import Path

from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce
from skills.bulletin.worship_resolution import resolve_profile_data, resolve_worship_profile
from tests.helpers import bulletin_input, make_church


EPISCOPAL_PACK = {
    "id": "episcopal-bcp-rite-ii",
    "family": "Anglican",
    "denomination": "Episcopal",
    "service_book": "Book of Common Prayer 1979",
    "rite": "Rite II",
    "service_plan": "episcopal-rite-ii",
    "choices": {
        "eucharistic_prayer": {"values": ["A", "B", "C", "D"]},
        "lords_prayer": {"values": ["traditional", "contemporary"]},
    },
}

LUTHERAN_PACK = {
    "id": "lutheran-elca-elw",
    "family": "Lutheran",
    "denomination": "Evangelical Lutheran Church in America",
    "service_book": "Evangelical Lutheran Worship",
    "rite": "Holy Communion",
    "service_plan": "lutheran-holy-communion",
    "choices": {
        "eucharistic_prayer": {"values": ["appointed", "local", "custom"]},
        "lords_prayer": {"values": ["traditional", "contemporary", "custom"]},
    },
}


def local_lutheran_sources(root: Path) -> dict[str, str]:
    source_dir = root / "worship" / "liturgy"
    source_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "gathering": "Local gathering text for the congregation.",
        "prayers": "Local prayers of the church for the congregation.",
        "great-thanksgiving": "Local Lutheran Great Thanksgiving text.",
        "lords-prayer": "Local Lord's Prayer text.",
        "communion": "Local Holy Communion invitation and distribution text.",
        "sending": "Local sending text for the congregation.",
    }
    paths = {}
    for identifier, sentence in sources.items():
        path = source_dir / f"{identifier}.md"
        path.write_text(
            f"# {identifier.replace('-', ' ').title()}\n\n"
            f"Priest\t{sentence}\n\n"
            "**People\tAmen.**\n",
            encoding="utf-8",
        )
        verify_liturgy_source(root, path)
        paths[identifier] = str(path.relative_to(root))
    return paths


class FirstTimeFlowTest(unittest.TestCase):
    def test_fresh_episcopal_profile_resolves_into_bulletin_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            resolved = resolve_profile_data(
                {
                    "status": "confirmed",
                    "tradition_pack": "episcopal-bcp-rite-ii",
                    "tradition": {"family": "Anglican", "denomination": "Episcopal"},
                    "defaults": {
                        "eucharistic_prayer": "A",
                        "lords_prayer": "traditional",
                        "prayers_of_the_people": "III",
                        "blessing": "omit",
                    },
                },
                EPISCOPAL_PACK,
            )
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = resolved["liturgy"]
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review")
            self.assertEqual(resolved["unresolved"], [])

    def test_fresh_lutheran_profile_uses_local_service_plan_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            files = local_lutheran_sources(church)
            resolved = resolve_profile_data(
                {
                    "status": "confirmed",
                    "tradition_pack": "lutheran-elca-elw",
                    "tradition": {
                        "family": "Lutheran",
                        "denomination": "Evangelical Lutheran Church in America",
                        "service_book": "Evangelical Lutheran Worship",
                        "rite": "Holy Communion",
                    },
                    "defaults": {"blessing": "omit"},
                },
                LUTHERAN_PACK,
                {
                    "liturgy": {
                        "eucharistic_prayer": "local",
                        "lords_prayer": "custom",
                        "files": files,
                    }
                },
            )
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = resolved["liturgy"]
            bulletin["service"]["occasion"] = "A Lutheran Sunday in September"
            bulletin["service"]["liturgical_color"] = "green"
            bulletin["service"]["lectionary_track"] = "Local lectionary"
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review")
            pdf_path = Path(result["week_folder"]) / "bulletin-2026-09-20-classic.pdf"
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
            self.assertIn("Local Lutheran Great Thanksgiving text.", text)
            self.assertIn("Local Holy Communion invitation", text)

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is required for the filesystem rehearsal")
    def test_yaml_loaded_fresh_profiles_pass_episcopal_and_lutheran_paths(self) -> None:
        episcopal_profile = "\n".join([
            "schema_version: 1", "status: confirmed",
            "tradition_pack: episcopal-bcp-rite-ii", "tradition:",
            "  family: Anglican", "  denomination: Episcopal",
            "  service_book: Book of Common Prayer 1979", "  rite: Rite II",
            "defaults:", "  eucharistic_prayer: A", "  lords_prayer: traditional",
            "  prayers_of_the_people: III", "  blessing: omit",
            "sources: {}", "provenance: {}", "",
        ])
        lutheran_profile = "\n".join([
            "schema_version: 1", "status: confirmed",
            "tradition_pack: lutheran-elca-elw", "tradition:",
            "  family: Lutheran", "  denomination: Evangelical Lutheran Church in America",
            "  service_book: Evangelical Lutheran Worship", "  rite: Holy Communion",
            "defaults:", "  blessing: omit", "sources: {}", "provenance: {}", "",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            episcopal = make_church(root / "episcopal-yaml")
            (episcopal / "worship" / "profile.yaml").write_text(episcopal_profile, encoding="utf-8")
            ep = resolve_worship_profile(episcopal)
            bulletin = bulletin_input(); bulletin["options"] = {}; bulletin["liturgy"] = ep["liturgy"]
            self.assertEqual(produce(episcopal, bulletin)["status"], "ready_for_review")

            lutheran = make_church(root / "lutheran-yaml")
            (lutheran / "worship" / "profile.yaml").write_text(lutheran_profile, encoding="utf-8")
            files = local_lutheran_sources(lutheran)
            lu = resolve_worship_profile(lutheran, {"liturgy": {
                "eucharistic_prayer": "local", "lords_prayer": "custom", "files": files,
            }})
            bulletin = bulletin_input(); bulletin["options"] = {}; bulletin["liturgy"] = lu["liturgy"]
            bulletin["service"]["occasion"] = "A Lutheran Sunday in September"
            bulletin["service"]["lectionary_track"] = "Local lectionary"
            self.assertEqual(produce(lutheran, bulletin)["status"], "ready_for_review")


if __name__ == "__main__":
    unittest.main()
