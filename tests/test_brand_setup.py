from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parents[1]
import sys
sys.path.insert(0, str(ROOT / "skills" / "onboarding" / "scripts"))
import brand_setup


class BrandSetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.church = Path(self.temp.name) / "parish"
        shutil.copytree(ROOT / "scaffold" / "church-folder", self.church)

    def tearDown(self):
        self.temp.cleanup()

    def test_scaffold_is_pending_and_explicit_choices_make_ready(self):
        self.assertFalse(brand_setup.status(self.church)["ready"])
        result = brand_setup.update(self.church, {"logo_status": "none", "colors_status": "neutral"})
        self.assertTrue(result["readiness"]["ready"])

    def test_supplied_logo_is_validated_and_custom_values_preserved(self):
        logo = self.church / "brand" / "mark.png"
        logo.parent.mkdir()
        Image.new("RGB", (20, 20), "white").save(logo)
        path = self.church / "brand.json"
        brand = json.loads(path.read_text())
        brand["texts"] = {"welcome": "Custom"}
        brand["qr"] = {"connect": {"url": "https://example.test"}}
        path.write_text(json.dumps(brand))
        brand_setup.update(self.church, {"logo": {"mark": "brand/mark.png"}, "colors_status": "neutral"})
        saved = json.loads(path.read_text())
        self.assertEqual(saved["logo_status"], "provided")
        self.assertEqual(saved["texts"], {"welcome": "Custom"})
        self.assertEqual(saved["qr"]["connect"]["url"], "https://example.test")

    def test_bad_logo_and_escape_fail_without_writes(self):
        path = self.church / "brand.json"
        before = path.read_bytes()
        for patch in ({"logo": {"banner": "https://example.test/logo.png"}}, {"logo": {"banner": "../logo.png"}}):
            with self.assertRaises(brand_setup.BrandSetupError):
                brand_setup.update(self.church, patch)
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_nonempty_logo_infers_provided_but_empty_does_not_infer_none(self):
        path = self.church / "brand.json"
        saved = json.loads(path.read_text())
        saved.pop("logo_status", None)
        saved.pop("colors_status", None)
        path.write_text(json.dumps(saved))
        self.assertEqual(brand_setup.status(self.church)["logo"]["status"], "pending")
        logo = self.church / "old.png"
        Image.new("RGB", (4, 4), "white").save(logo)
        saved["logo"]["banner"] = "old.png"
        path.write_text(json.dumps(saved))
        self.assertEqual(brand_setup.status(self.church)["logo"]["status"], "provided")

    def test_unknown_fields_and_invalid_colors_are_rejected(self):
        with self.assertRaises(brand_setup.BrandSetupError):
            brand_setup.update(self.church, {"colors": {"unknown": "#ffffff"}})
        with self.assertRaises(brand_setup.BrandSetupError):
            brand_setup.update(self.church, {"colors_status": "confirmed", "colors": {"ink": "red"}})

    def test_malformed_hand_edited_status_cannot_bypass_logo_validation(self):
        path = self.church / "brand.json"
        saved = json.loads(path.read_text())
        saved["logo_status"] = "none"
        saved["logo"]["banner"] = "missing.png"
        path.write_text(json.dumps(saved))
        result = brand_setup.status(self.church)
        self.assertFalse(result["ready"])
        self.assertFalse(result["logo"]["ready"])

        before = path.read_bytes()
        with self.assertRaises(brand_setup.BrandSetupError):
            brand_setup.update(self.church, {"logo_status": ["none"]})
        self.assertEqual(path.read_bytes(), before)

    def test_malformed_svg_and_non_string_logo_are_rejected(self):
        svg = self.church / "bad.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.invalid/x"/></svg>')
        with self.assertRaises(brand_setup.BrandSetupError):
            brand_setup.update(self.church, {"logo": {"banner": "bad.svg"}})
        path = self.church / "brand.json"
        saved = json.loads(path.read_text())
        saved["logo_status"] = "provided"
        saved["logo"]["banner"] = {"path": "bad.svg"}
        path.write_text(json.dumps(saved))
        self.assertFalse(brand_setup.status(self.church)["ready"])

    def test_public_repository_root_is_rejected(self):
        with self.assertRaises(brand_setup.BrandSetupError):
            brand_setup.status(ROOT)


if __name__ == "__main__":
    unittest.main()
