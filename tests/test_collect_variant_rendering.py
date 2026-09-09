from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from skills.bulletin.bulletin_production import produce
from tests.helpers import bulletin_input, make_church, verify_liturgy_source


class CollectVariantRenderingTest(unittest.TestCase):
    def test_produce_renders_verified_collect_after_collect_of_day_in_classic_and_modern(self):
        with tempfile.TemporaryDirectory() as tmp:
            church = make_church(Path(tmp))
            source = church / "worship" / "liturgy" / "labor-day-collect.md"
            order = church / "worship" / "orders" / "labor-day.yaml"
            source.parent.mkdir(parents=True, exist_ok=True)
            order.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# Labor Day Collect\n\nPriest\tSynthetic labor collect text.\n", encoding="utf-8")
            order.write_text("files:\n  labor-day-collect: worship/liturgy/labor-day-collect.md\n", encoding="utf-8")
            verify_liturgy_source(church, source)
            for template, service_date in (("classic", "2026-09-20"), ("modern", "2026-09-27")):
                request = bulletin_input()
                request["template"] = template
                request["service"]["date"] = service_date
                request["liturgy"].update({
                    "eucharistic_prayer": "A",
                    "lords_prayer": "traditional",
                    "prayers_of_the_people": "III",
                    "blessing": "omit",
                    "worship_profile_ref": "worship/profile.yaml",
                    "sources": {},
                    "files": {"labor-day-collect": "worship/liturgy/labor-day-collect.md"},
                    "service_variant": {
                        "id": "labor-day",
                        "name": "Labor Day",
                        "base_service_plan": "episcopal-rite-ii",
                        "replace": [],
                        "insert": [{"after": "collect-of-day", "units": ["labor-day-collect"]}],
                    },
                    "service_variant_provenance": {
                        "variant_id": "labor-day",
                        "order_file_chain": ["worship/orders/labor-day.yaml"],
                        "confirmation_policy": "scheduled",
                    },
                })
                result = produce(church, request)
                self.assertEqual(result["status"], "ready_for_review", result)
                config = json.loads((Path(result["week_folder"]) / "bulletin-config.json").read_text(encoding="utf-8"))
                html = next(Path(result["week_folder"]).glob(f"*{template}.html")).read_text(encoding="utf-8")
                self.assertIn("Synthetic labor collect text.", html)
                self.assertLess(html.index("The Collect of the Day"), html.index("Synthetic labor collect text."))
                self.assertLess(html.index("Synthetic labor collect text."), html.index("Test Book 1:1-3"))
                self.assertEqual(config["liturgy"]["service_variant"]["insert"][0]["after"], "collect-of-day")


if __name__ == "__main__":
    unittest.main()
