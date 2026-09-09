from __future__ import annotations

import tempfile
import unittest
from tests.helpers import verify_liturgy_source
from pathlib import Path

import yaml
from pypdf import PdfReader

from skills.bulletin.bulletin_production import produce
from skills.bulletin.worship_resolution import resolve_profile_data, resolve_worship_profile
from tests.helpers import bulletin_input, make_church
from tests.test_first_time_flow import local_lutheran_sources


class BulletinSourceReadinessTest(unittest.TestCase):
    def _pack(self) -> dict:
        return yaml.safe_load(Path("skills/bulletin/traditions/episcopal-bcp-rite-ii.yaml").read_text(encoding="utf-8"))

    def _profile(self, prayer: str = "A", people: str = "III") -> dict:
        return {
            "status": "confirmed",
            "tradition_pack": "episcopal-bcp-rite-ii",
            "defaults": {
                "eucharistic_prayer": prayer,
                "lords_prayer": "traditional",
                "prayers_of_the_people": people,
                "blessing": "omit",
            },
        }

    def test_resolver_reports_missing_episcopal_source_as_needs_input(self) -> None:
        pack = self._pack()
        pack["shipped_sources"]["eucharistic_prayer"]["B"] = "missing-standard-source"
        result = resolve_profile_data(self._profile("B"), pack)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["unresolved"][0]["field"], "liturgy.eucharistic_prayer")
        self.assertIn("agent should first", result["unresolved"][0]["reason"])

    def test_modern_profile_without_prayers_form_needs_input(self) -> None:
        profile = self._profile()
        del profile["defaults"]["prayers_of_the_people"]
        result = resolve_profile_data(profile, self._pack())
        self.assertEqual(result["status"], "needs_input")
        self.assertTrue(any(item["field"] == "liturgy.prayers_of_the_people" for item in result["unresolved"]))

    def test_direct_production_blocks_missing_source_before_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = {
                "service_plan": "episcopal-rite-ii",
                "worship_profile_ref": "worship/profile.yaml",
                "eucharistic_prayer": "missing-standard-prayer",
                "lords_prayer": "traditional",
                "prayers_of_the_people": "III",
                "blessing": "omit",
            }
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["code"], "missing_liturgy_source")
            self.assertEqual(result["errors"][0]["field"], "liturgy.eucharistic_prayer")
            self.assertFalse((church / "bulletins" / ".staging").exists())

    def test_modern_production_blocks_missing_prayers_form_before_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = {
                "service_plan": "episcopal-rite-ii",
                "worship_profile_ref": "worship/profile.yaml",
                "eucharistic_prayer": "A",
                "lords_prayer": "traditional",
                "blessing": "omit",
            }
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["field"], "liturgy.prayers_of_the_people")

    def test_private_episcopal_source_renders_review_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            source = church / "worship" / "liturgy" / "prayer-b.md"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "# Synthetic Eucharistic Prayer B\n\n"
                "Priest\tThis is the church-owned Prayer B text.\n\n"
                "**People\tAmen.**\n",
                encoding="utf-8",
            )
            verify_liturgy_source(church, source)
            bulletin = bulletin_input()
            bulletin["options"] = {}
            bulletin["liturgy"] = {
                "service_plan": "episcopal-rite-ii",
                "worship_profile_ref": "worship/profile.yaml",
                "eucharistic_prayer": "B",
                "lords_prayer": "traditional",
                "prayers_of_the_people": "III",
                "blessing": "omit",
                "sources": {"eucharistic_prayer": "worship/liturgy/prayer-b.md"},
            }
            result = produce(church, bulletin)
            self.assertEqual(result["status"], "ready_for_review")
            pdf = Path(result["week_folder"]) / "bulletin-2026-09-20-classic.pdf"
            self.assertTrue(pdf.is_file())
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
            self.assertIn("This is the church-owned Prayer B text.", text)

    def test_resolver_loads_standard_prayer_forms_without_private_sources(self) -> None:
        for key, value in (("lords_prayer", "contemporary"), ("prayers_of_the_people", "II")):
            with self.subTest(key=key):
                profile = self._profile()
                profile["defaults"][key] = value
                result = resolve_profile_data(profile, self._pack())
                self.assertEqual(result["status"], "resolved", result)
                self.assertEqual(result["unresolved"], [])

    def test_explicit_null_print_choice_needs_confirmation(self) -> None:
        for key in ("include_creed", "include_confession", "print_full_eucharistic_prayer"):
            with self.subTest(key=key):
                profile = self._profile()
                profile["defaults"][key] = None
                result = resolve_profile_data(profile, self._pack())
                self.assertEqual(result["status"], "needs_input")
                self.assertTrue(any(item["field"] == f"liturgy.{key}" for item in result["unresolved"]))

    def test_fresh_lutheran_profile_reports_missing_private_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            (church / "worship" / "profile.yaml").write_text(
                "schema_version: 1\n"
                "status: confirmed\n"
                "tradition_pack: lutheran-elca-elw\n"
                "defaults:\n"
                "  eucharistic_prayer: local\n"
                "  lords_prayer: custom\n"
                "  blessing: omit\n"
                "sources: {}\n",
                encoding="utf-8",
            )
            result = resolve_worship_profile(church)
            self.assertEqual(result["status"], "needs_input")
            self.assertTrue(any(item["field"] == "liturgy.files.gathering" for item in result["unresolved"]))

    def test_lutheran_standing_sources_survive_a_new_week(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            files = local_lutheran_sources(church)
            profile = {"status": "confirmed", "tradition_pack": "lutheran-elca-elw",
                       "defaults": {"eucharistic_prayer": "local", "lords_prayer": "custom", "blessing": "omit"},
                       "sources": files}
            (church / "worship" / "profile.yaml").write_text(yaml.safe_dump(profile))
            result = resolve_worship_profile(church)
            self.assertEqual(result["status"], "resolved", result)
            self.assertEqual(result["liturgy"]["files"], files)
            weekly = bulletin_input()
            weekly["options"] = {}
            weekly["liturgy"] = result["liturgy"]
            self.assertEqual(produce(church, weekly)["status"], "ready_for_review")

    def test_unconfirmed_private_source_is_not_treated_as_a_weekly_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            source = church / "worship" / "liturgy" / "private-prayer.md"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("Synthetic private prayer for testing.")
            profile = self._profile("B")
            profile["status"] = "needs_onboarding"
            profile["sources"] = {"eucharistic_prayer": "worship/liturgy/private-prayer.md"}
            result = resolve_profile_data(profile, self._pack(), church_root=church)
            self.assertEqual(result["status"], "needs_input")
            self.assertTrue(any("Confirm the church-owned" in row["reason"] for row in result["unresolved"]))
            blank_weekly = resolve_profile_data(
                profile, self._pack(),
                {"liturgy": {"sources": {"eucharistic_prayer": ""}}}, church_root=church,
            )
            self.assertEqual(blank_weekly["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
