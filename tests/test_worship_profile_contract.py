from __future__ import annotations

import json
import tempfile
import unittest
from tests.helpers import verify_liturgy_source
from pathlib import Path

from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce
from tests.helpers import bulletin_input, make_church


class WorshipProfileContractTest(unittest.TestCase):
    def test_scaffold_has_one_editable_worship_profile(self) -> None:
        profile = Path("scaffold/church-folder/worship/profile.yaml")
        church_yaml = Path("scaffold/church-folder/church.yaml").read_text(encoding="utf-8")
        self.assertTrue(profile.is_file())
        self.assertIn("worship_profile: worship/profile.yaml", church_yaml)
        self.assertIn("status: needs_onboarding", profile.read_text(encoding="utf-8"))
        self.assertIn("blessing: general-blessing", profile.read_text(encoding="utf-8"))

    def test_scaffold_places_bulletin_preferences_and_qr_contract_in_their_owners(self) -> None:
        church_yaml = Path("scaffold/church-folder/church.yaml").read_text(encoding="utf-8")
        brand = json.loads(Path("scaffold/church-folder/brand.json").read_text(encoding="utf-8"))
        profile = Path("scaffold/church-folder/worship/profile.yaml").read_text(encoding="utf-8")
        self.assertIn("print_in_bulletin: null", church_yaml)
        self.assertIn("clergy_and_staff: []", church_yaml)
        self.assertIn("governing_body:", church_yaml)
        self.assertIn("    label: \"\"", church_yaml)
        self.assertIn("    member_label: \"\"", church_yaml)
        self.assertIn("    officers: []", church_yaml)
        self.assertIn("    members: []", church_yaml)
        self.assertIn("include_serving_today: null", church_yaml)
        self.assertIn("serving_roles: []", church_yaml)
        self.assertNotIn("printed_lyrics:", church_yaml)
        self.assertNotIn("lyrics_source", church_yaml)
        self.assertNotIn("lyrics_permission", church_yaml)
        self.assertIn("service_variants: {}", profile)
        self.assertIsNone(brand["qr"]["standard_copy_accepted"])
        self.assertIn("relative to the church folder", brand["qr"]["_comment"])
        self.assertEqual(set(brand["qr"]["connect"]), {"image", "url"})
        self.assertEqual(set(brand["qr"]["give"]), {"image", "url"})
        self.assertEqual(
            set(brand["qr"]["copy"]),
            {"heading", "connect_head", "give_head", "connect_body", "give_body"},
        )
        self.assertIn("communion_welcome: \"\"", profile)

    def test_missing_worship_choice_blocks_instead_of_assuming_prayer_a(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["options"] = {}
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["code"], "unresolved_liturgy")
            self.assertEqual(result["errors"][0]["field"], "liturgy.eucharistic_prayer")

    def test_resolved_liturgy_is_serialized_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = {
                "service_plan": "episcopal-rite-ii",
                "eucharistic_prayer": "A",
                "lords_prayer": "traditional",
                "prayers_of_the_people": "III",
                "blessing": "May the peace of God guard your hearts and minds.",
                "communion_welcome": "All are welcome at Christ's table.",
            }
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review")
            config_path = Path(result["week_folder"]) / "bulletin-config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["liturgy"]["eucharistic_prayer"], "A")
            self.assertEqual(config["liturgy"]["prayers_of_the_people"], "III")
            pdf_path = Path(result["week_folder"]) / "bulletin-2026-09-20-classic.pdf"
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
            self.assertIn("All are welcome at Christ’s table.", text)
            self.assertIn("May the peace of God guard your hearts and minds.", text)

    def test_church_owned_liturgy_source_is_staged_without_becoming_public(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            local_dir = church / "worship" / "liturgy"
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / "thanksgiving.md").write_text(
                "# Local Great Thanksgiving\n\n"
                "Priest\tThis local Thanksgiving is used by the congregation.\n\n"
                "**People\tAnd also with you.**\n",
                encoding="utf-8",
            )
            verify_liturgy_source(church, local_dir / "thanksgiving.md")
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = {
                "service_plan": "episcopal-rite-ii",
                "eucharistic_prayer": "local-thanksgiving",
                "lords_prayer": "traditional",
                "prayers_of_the_people": "III",
                "blessing": "omit",
                "sources": {
                    "eucharistic_prayer": "worship/liturgy/thanksgiving.md",
                },
            }
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review")
            config_path = Path(result["week_folder"]) / "bulletin-config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["liturgy"]["eucharistic_prayer"], "local-thanksgiving")
            self.assertFalse((Path(result["week_folder"]) / "liturgy").exists())
            pdf_path = Path(result["week_folder"]) / "bulletin-2026-09-20-classic.pdf"
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
            self.assertIn("This local Thanksgiving is used by the congregation.", text)

    def test_tradition_packs_are_declarative_and_public_safe(self) -> None:
        packs = [path for path in Path("skills/bulletin/traditions").glob("*.yaml")
                 if path.name != "catalog.yaml"]
        self.assertEqual({path.stem for path in packs}, {
            "episcopal-bcp-rite-ii",
            "lutheran-elca-elw",
            "lutheran-lcms-lsb",
        })
        for path in packs:
            text = path.read_text(encoding="utf-8")
            self.assertIn("choices:", text)
            self.assertNotIn("Example Pastor", text)
        catalog = Path("skills/bulletin/traditions/catalog.yaml").read_text(encoding="utf-8")
        for pack_id in ("episcopal-bcp-rite-ii", "lutheran-elca-elw", "lutheran-lcms-lsb"):
            self.assertIn(f"id: {pack_id}", catalog)


if __name__ == "__main__":
    unittest.main()
