from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml
from pypdf import PdfReader

from skills.bulletin.bulletin_production.interface import _copy_liturgy_sources, produce
from tests.helpers import bulletin_input, make_church, verify_liturgy_source
from tests.test_bulletin_saved_worship import _configured_profile


class BulletinFieldSourceTest(unittest.TestCase):
    def _source(self, church: Path, filename: str, text: str) -> Path:
        path = church / "worship" / "liturgy" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        verify_liturgy_source(church, path)
        return path

    def test_logical_fields_with_the_same_custom_choice_get_distinct_staged_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            prayers = self._source(
                church, "prayers.md",
                "# Synthetic Prayers\n\nCelebrant\tField prayers unique text.\n",
            )
            doxology = self._source(
                church, "doxology.md",
                "# Synthetic Doxology\n\n**All\tField doxology unique text.**\n",
            )
            original_prayers = prayers.read_bytes()
            original_doxology = doxology.read_bytes()
            bulletin = {"liturgy": {
                "prayers_of_the_people": "custom",
                "doxology": "custom",
                "sources": {
                    "prayers_of_the_people": str(prayers.relative_to(church)),
                    "doxology": str(doxology.relative_to(church)),
                },
            }}
            stage = church / "stage"
            stage.mkdir()
            staged = _copy_liturgy_sources(bulletin, church, stage)

            self.assertIsNotNone(staged)
            files = bulletin["liturgy"]["files"]
            self.assertNotEqual(files["prayers_of_the_people"], files["doxology"])
            self.assertTrue(files["prayers_of_the_people"].startswith("church-prayers_of_the_people-"))
            self.assertTrue(files["doxology"].startswith("church-doxology-"))
            self.assertIn("Field prayers unique text.", (staged / f'{files["prayers_of_the_people"]}.md').read_text())
            self.assertIn("Field doxology unique text.", (staged / f'{files["doxology"]}.md').read_text())
            self.assertEqual(prayers.read_bytes(), original_prayers)
            self.assertEqual(doxology.read_bytes(), original_doxology)

    def test_explicit_unit_file_wins_over_generated_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            generated = self._source(
                church, "generated-prayers.md",
                "# Generated\n\nCelebrant\tGenerated field text.\n",
            )
            explicit = self._source(
                church, "explicit-prayers.md",
                "# Explicit\n\nCelebrant\tExplicit unit text.\n",
            )
            bulletin = {"liturgy": {
                "prayers_of_the_people": "III",
                "sources": {"prayers_of_the_people": str(generated.relative_to(church))},
                "files": {"prayers-of-the-people": str(explicit.relative_to(church))},
            }}
            stage = church / "stage"
            stage.mkdir()
            staged = _copy_liturgy_sources(bulletin, church, stage)

            self.assertIsNotNone(staged)
            files = bulletin["liturgy"]["files"]
            self.assertNotEqual(files["prayers_of_the_people"], files["prayers-of-the-people"])
            self.assertIn("Generated field text.", (staged / f'{files["prayers_of_the_people"]}.md').read_text())
            self.assertIn("Explicit unit text.", (staged / f'{files["prayers-of-the-people"]}.md').read_text())

    def test_sanitized_logical_keys_cannot_collide_in_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            first = self._source(church, "first.md", "# First\n\nFirst text.\n")
            second = self._source(church, "second.md", "# Second\n\nSecond text.\n")
            bulletin = {"liturgy": {"files": {
                "field/one": str(first.relative_to(church)),
                "field:one": str(second.relative_to(church)),
            }}}
            stage = church / "stage"
            stage.mkdir()
            staged = _copy_liturgy_sources(bulletin, church, stage)

            self.assertIsNotNone(staged)
            files = bulletin["liturgy"]["files"]
            self.assertNotEqual(files["field/one"], files["field:one"])
            self.assertIn("First text.", (staged / f'{files["field/one"]}.md').read_text())
            self.assertIn("Second text.", (staged / f'{files["field:one"]}.md').read_text())

    def test_custom_prayers_and_doxology_render_once_in_html_and_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church, prayers_of_the_people="custom", doxology="custom")
            prayers = self._source(
                church, "custom-prayers.md",
                "# Synthetic Prayers\n\nCelebrant\tCustom prayers appear once.\n",
            )
            doxology = self._source(
                church, "custom-doxology.md",
                "# Synthetic Doxology\n\n**All\tCustom doxology appears once.**\n",
            )
            profile_path = church / "worship" / "profile.yaml"
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            profile["sources"].update({
                "prayers_of_the_people": str(prayers.relative_to(church)),
                "doxology": str(doxology.relative_to(church)),
            })
            profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
            request = bulletin_input()
            request["liturgy"] = {}

            result = produce(church, request)
            self.assertEqual(result["status"], "ready_for_review", result)
            folder = Path(result["week_folder"])
            html = next(folder.glob("*.html")).read_text(encoding="utf-8")
            pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(next(folder.glob("*classic.pdf"))).pages)
            for rendered in (html, pdf_text):
                self.assertEqual(rendered.count("Custom prayers appear once."), 1)
                self.assertEqual(rendered.count("Custom doxology appears once."), 1)
                self.assertLess(rendered.index("Custom prayers appear once."), rendered.index("Custom doxology appears once."))

            source_config = json.loads((folder / "bulletin-config.json").read_text(encoding="utf-8"))
            self.assertEqual(source_config["liturgy"]["sources"]["prayers_of_the_people"], str(prayers.relative_to(church)))
            self.assertEqual(source_config["liturgy"]["sources"]["doxology"], str(doxology.relative_to(church)))

    def test_profile_communion_welcome_prints_without_a_default_and_persists_next_week(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            _configured_profile(church)
            welcome = self._source(
                church, "communion-welcome.md",
                "# Communion Welcome\n\nAll visitors may receive this synthetic welcome.\n",
            )
            profile_path = church / "worship" / "profile.yaml"
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            profile["sources"]["communion_welcome"] = str(welcome.relative_to(church))
            profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")

            first = bulletin_input()
            first["liturgy"] = {}
            one = produce(church, first)
            self.assertEqual(one["status"], "ready_for_review", one)
            first_html = next(Path(one["week_folder"]).glob("*.html")).read_text(encoding="utf-8")
            self.assertIn("All visitors may receive this synthetic welcome.", first_html)

            second = copy.deepcopy(first)
            second["service"]["date"] = "2026-09-27"
            two = produce(church, second)
            self.assertEqual(two["status"], "ready_for_review", two)
            second_html = next(Path(two["week_folder"]).glob("*.html")).read_text(encoding="utf-8")
            self.assertIn("All visitors may receive this synthetic welcome.", second_html)


if __name__ == "__main__":
    unittest.main()
