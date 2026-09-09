from __future__ import annotations

import json
import tempfile
import unittest
from tests.helpers import verify_liturgy_source
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from skills.bulletin.bulletin_production import finalize, produce, revise
from skills.bulletin.bulletin_production import interface
from tests.helpers import bulletin_input, make_church


def fake_run(command, *, stage, env=None, reject_warnings=False):
    if stage == "render":
        output = Path(command[command.index("--out") + 1])
        (output / "bulletin-2026-09-20-classic.html").write_text("synthetic", encoding="utf-8")
        writer = PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=612, height=792)
        writer.write(output / "bulletin-2026-09-20-classic.pdf")
    elif stage == "imposition":
        writer = PdfWriter()
        for _ in range(2):
            writer.add_blank_page(width=1224, height=792)
        writer.write(command[-1])
    return ""


class BulletinRevisionTest(unittest.TestCase):
    def _patch_production(self):
        brand = {
            "church": {"name": "Public Test Parish"},
            "logo": {},
            "colors": {"rubric_red": "#7f3030"},
            "qr": {},
        }
        return patch.multiple(
            interface,
            _load_church_configuration= lambda root: ({}, brand),
            _run=fake_run,
            _quality_gate=lambda *args: [],
        )

    def test_revision_preserves_sources_archives_predecessor_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            (church / "music").mkdir(exist_ok=True)
            (church / "music" / "scan.png").write_bytes(b"synthetic scan")
            liturgy = church / "worship" / "liturgy"
            liturgy.mkdir(parents=True)
            (liturgy / "local.md").write_text("# Local\n\nLocal text.\n", encoding="utf-8")
            verify_liturgy_source(church, liturgy / "local.md")
            bulletin = bulletin_input()
            bulletin["hymns"]["entrance"]["images"] = ["music/scan.png"]
            bulletin["liturgy"] = {
                "service_plan": "episcopal-rite-ii",
                "eucharistic_prayer": "A",
                "lords_prayer": "traditional",
                "blessing": "local",
                "sources": {"blessing": "worship/liturgy/local.md"},
            }
            with self._patch_production():
                first = produce(church, bulletin)
                prior_receipt = Path(first["receipt_path"])
                prior_run_id = json.loads(prior_receipt.read_text(encoding="utf-8"))["run_id"]
                revised = revise(
                    church,
                    prior_receipt,
                    {"announcements": [{"title": "Changed", "text": "Changed text."}]},
                )
                repeated = revise(
                    church,
                    prior_receipt,
                    {"announcements": [{"title": "Changed", "text": "Changed text."}]},
                )
            self.assertEqual(revised["status"], "ready_for_review", revised)
            self.assertFalse(revised["idempotent"])
            self.assertTrue(repeated["idempotent"])
            active = Path(revised["receipt_path"])
            receipt = json.loads(active.read_text(encoding="utf-8"))
            self.assertEqual(receipt["receipt_version"], 2)
            self.assertEqual(receipt["revision_of"]["run_id"], prior_run_id)
            source_config = json.loads((active.parent / "bulletin-config.json").read_text(encoding="utf-8"))
            self.assertEqual(source_config["hymns"]["entrance"]["images"], ["music/scan.png"])
            self.assertEqual(source_config["liturgy"]["sources"]["blessing"], "worship/liturgy/local.md")
            archive_receipt = church / receipt["revision_of"]["receipt_path"]
            self.assertTrue(archive_receipt.is_file())
            self.assertEqual(len(list((church / "bulletins" / "2026" / "09" / ".revisions").rglob("bulletin-production-receipt.json"))), 1)

    def test_failed_revision_leaves_active_review_package_and_no_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            bulletin = bulletin_input()
            with self._patch_production():
                first = produce(church, bulletin)
            prior_receipt = Path(first["receipt_path"])

            def fail_render(command, *, stage, env=None, reject_warnings=False):
                if stage == "render":
                    raise interface.StageFailure("render_failed", "render", "synthetic render failure")
                return fake_run(command, stage=stage, env=env, reject_warnings=reject_warnings)

            with patch.multiple(interface, _load_church_configuration=lambda root: ({}, json.loads((church / "brand.json").read_text())), _run=fail_render, _quality_gate=lambda *args: []):
                failed = revise(church, prior_receipt, {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(failed["status"], "blocked")
            self.assertEqual(failed["errors"][0]["code"], "render_failed")
            self.assertTrue(prior_receipt.is_file())
            self.assertFalse((church / "bulletins" / "2026" / "09" / ".revisions").exists())

    def test_lutheran_private_liturgy_source_survives_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            liturgy = church / "worship" / "liturgy"
            liturgy.mkdir(parents=True)
            (liturgy / "gathering.md").write_text("# Gathering\n\nLocal Lutheran text.\n", encoding="utf-8")
            verify_liturgy_source(church, liturgy / "gathering.md")
            bulletin = bulletin_input()
            bulletin["service"]["occasion"] = "A Lutheran Sunday in September"
            bulletin["liturgy"] = {
                "service_plan": "lutheran-holy-communion",
                "eucharistic_prayer": "local",
                "lords_prayer": "custom",
                "blessing": "omit",
                "files": {"gathering": "worship/liturgy/gathering.md"},
            }
            with self._patch_production():
                first = produce(church, bulletin)
                revised = revise(church, first["receipt_path"], {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(revised["status"], "ready_for_review", revised)
            config = json.loads((Path(revised["week_folder"]) / "bulletin-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["liturgy"]["files"]["gathering"], "worship/liturgy/gathering.md")

    def test_approved_prior_is_not_revisable_and_history_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            with self._patch_production():
                first = produce(church, bulletin_input())
            receipt_path = Path(first["receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            hashes = {item["role"]: item["sha256"] for item in receipt["artifacts"]}
            approval = finalize(receipt_path, {"production_run_id": receipt["run_id"], "approved_by": "Test", "reviewed_artifact_hashes": hashes})
            self.assertEqual(approval["status"], "approved")
            with self._patch_production():
                revised = revise(church, receipt_path, {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(revised["status"], "blocked")
            self.assertEqual(revised["errors"][0]["code"], "prior_run_approved")
            history = json.loads((church / "bulletins" / "bulletin-log.json").read_text(encoding="utf-8"))
            self.assertEqual(history["2026-09-20"]["templates"]["classic"]["production_run_id"], receipt["run_id"])

    def test_finalize_refuses_a_second_approved_package_for_the_same_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            with self._patch_production():
                first = produce(church, bulletin_input())
            first_receipt = Path(first["receipt_path"])
            first_data = json.loads(first_receipt.read_text(encoding="utf-8"))
            first_hashes = {item["role"]: item["sha256"] for item in first_data["artifacts"]}
            self.assertEqual(finalize(first_receipt, {"production_run_id": first_data["run_id"], "approved_by": "Test", "reviewed_artifact_hashes": first_hashes})["status"], "approved")
            second_input = bulletin_input()
            second_input["service"]["occasion"] = "Another Test Sunday in September"
            with self._patch_production():
                second = produce(church, second_input)
            second_receipt = Path(second["receipt_path"])
            second_data = json.loads(second_receipt.read_text(encoding="utf-8"))
            second_hashes = {item["role"]: item["sha256"] for item in second_data["artifacts"]}
            result = finalize(second_receipt, {"production_run_id": second_data["run_id"], "approved_by": "Test", "reviewed_artifact_hashes": second_hashes})
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["errors"][0]["code"], "approved_history_conflict")

    def test_finalize_migrates_legacy_render_history_into_approval_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            with self._patch_production():
                produced = produce(church, bulletin_input())
            receipt_path = Path(produced["receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            hashes = {item["role"]: item["sha256"] for item in receipt["artifacts"]}
            legacy = {
                "date": "2026-09-20",
                "occasion": "A Test Sunday in September",
                "templates": {"classic": {"rendered_at": "2026-09-01T12:00:00", "pages": 4}},
            }
            history_path = church / "bulletins" / "bulletin-log.json"
            history_path.write_text(json.dumps({"2026-09-20": legacy}), encoding="utf-8")

            result = finalize(
                receipt_path,
                {
                    "production_run_id": receipt["run_id"],
                    "approved_by": "Test",
                    "reviewed_artifact_hashes": hashes,
                },
            )

            self.assertEqual(result["status"], "approved", result)
            approval = json.loads((receipt_path.parent / "bulletin-approval-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(approval["history_update"], "migrated_legacy_render_history")
            self.assertEqual(approval["legacy_unapproved_history_replaced"]["entry"], legacy)
            approved_history = json.loads(history_path.read_text(encoding="utf-8"))["2026-09-20"]
            self.assertEqual(approved_history["approval_id"], approval["approval_id"])
            self.assertEqual(approved_history["templates"]["classic"]["production_run_id"], receipt["run_id"])

    def test_v1_ambiguous_staged_music_source_blocks_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            church = make_church(Path(temporary))
            (church / "music" / "one").mkdir(parents=True)
            (church / "music" / "two").mkdir(parents=True)
            (church / "music" / "one" / "scan.png").write_bytes(b"same")
            (church / "music" / "two" / "scan.png").write_bytes(b"same")
            with self._patch_production():
                first = produce(church, bulletin_input())
            receipt_path = Path(first["receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            config_path = receipt_path.parent / "bulletin-config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["hymns"]["entrance"]["images"] = ["hymn-images/scan.png"]
            config_path.write_text(json.dumps(config), encoding="utf-8")
            (receipt_path.parent / "hymn-images").mkdir(exist_ok=True)
            (receipt_path.parent / "hymn-images" / "scan.png").write_bytes(b"same")
            receipt["receipt_version"] = 1
            receipt.pop("source_config", None)
            for artifact in receipt["artifacts"]:
                if artifact["role"] == "config":
                    artifact["sha256"] = interface._sha256(config_path)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self._patch_production():
                revised = revise(church, receipt_path, {"announcements": [{"title": "Changed", "text": "Changed."}]})
            self.assertEqual(revised["status"], "blocked")
            self.assertEqual(revised["errors"][0]["code"], "revision_source_unrecoverable")


if __name__ == "__main__":
    unittest.main()
