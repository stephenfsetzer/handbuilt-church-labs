from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from skills.onboarding.scripts.qr_setup import install_qr


class QrOnboardingTest(unittest.TestCase):
    def test_plan_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = Path(tmp) / "synthetic-church"
            church.mkdir()
            brand = church / "brand.json"
            brand.write_text(json.dumps({"qr": {}}), encoding="utf-8")
            result = install_qr(church, "connect", "https://example.test/connect")
            self.assertEqual(result["status"], "planned")
            self.assertFalse((church / result["image"]).exists())
            self.assertEqual(json.loads(brand.read_text(encoding="utf-8")), {"qr": {}})

    def test_supplied_image_is_copied_and_saved_church_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church = root / "synthetic-church"
            church.mkdir()
            brand = church / "brand.json"
            brand.write_text(json.dumps({"qr": {}}), encoding="utf-8")
            supplied = root / "supplied.png"
            Image.new("1", (21, 21), color=1).save(supplied)
            result = install_qr(
                church,
                "give",
                "https://example.test/give",
                image=str(supplied),
                apply=True,
            )
            saved = json.loads(brand.read_text(encoding="utf-8"))["qr"]["give"]
            self.assertEqual(saved, {
                "image": "brand/qr/give.png",
                "url": "https://example.test/give",
            })
            self.assertTrue((church / saved["image"]).is_file())
            self.assertEqual(result["status"], "updated")

    def test_confirmed_url_can_create_a_private_qr_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = Path(tmp) / "synthetic-church"
            church.mkdir()
            brand = church / "brand.json"
            brand.write_text(json.dumps({"qr": {}}), encoding="utf-8")
            result = install_qr(
                church,
                "connect",
                "https://example.test/connect",
                apply=True,
            )
            target = church / result["image"]
            with Image.open(target) as generated:
                generated.verify()
            saved = json.loads(brand.read_text(encoding="utf-8"))["qr"]["connect"]
            self.assertEqual(saved["url"], "https://example.test/connect")
            self.assertEqual(saved["image"], "brand/qr/connect.png")

    def test_rejects_non_web_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            church = Path(tmp)
            (church / "brand.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_qr(church, "connect", "javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
