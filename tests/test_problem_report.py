from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from tools import church_workflow, handbuilt_runtime as runtime
from tools import problem_report as report

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/problem_report.py"
# Built in pieces so the public-tree privacy check does not read them as real paths.
USERS, HOME = "/" + "Users", "/" + "home"


class StubHandler(BaseHTTPRequestHandler):
    status = 201
    body = b'{"report": "HB-1A2B3C"}'
    received: list = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        type(self).received.append({"content_type": self.headers.get("Content-Type"),
                                    "body": json.loads(self.rfile.read(length))})
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):
        pass


class Stub:
    def __init__(self, status, body=b"{}"):
        handler = type("Handler", (StubHandler,), {"status": status, "body": body, "received": []})
        self.handler = handler
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/labs/report"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def payload(**changes):
    base = {"plugin_version": "0.8.29", "os": "windows", "os_version": "11 10.0.26100",
            "host": "claude-code", "job": "setup", "error_code": "windows-app-control",
            "detail": "OSError: [WinError 4551] An Application Control policy has blocked this file"}
    base.update(changes)
    return report.validate(base)


class RedactionTests(unittest.TestCase):
    def test_home_and_user_folders_become_tilde(self):
        detail = (r"C:\Users\Pastor Name\AppData\Local\Handbuilt\x.dll and C:\\Users\\someone\\a.pyd "
                  f"and {USERS}/someone/Library/x and {HOME}/someone/.local/y and /opt{HOME}/fine")
        text = report.redact(detail, home=f"{USERS}/someone", folder=f"{USERS}/someone")
        self.assertNotIn("someone", text)
        self.assertNotIn("Pastor", text)
        self.assertIn(r"~\AppData\Local\Handbuilt", text)
        self.assertIn("~/Library/x", text)
        self.assertIn("~/.local/y", text)
        self.assertIn(f"/opt{HOME}/fine", text)

    def test_windows_home_is_replaced_whatever_the_slashes(self):
        home = r"C:\Users\vicar"
        text = report.redact(r"C:\Users\vicar\a and c:" + USERS.lower() + r"/vicar/b and C:\\Users\\vicar\\c", home=home, folder=home)
        self.assertNotIn("vicar", text)

    def test_working_folder_name_stays_private(self):
        text = report.redact(f"{USERS}/someone/Desktop/Synthetic Parish/bulletin.json failed",
                             home=f"{USERS}/someone", folder=f"{USERS}/someone/Desktop/Synthetic Parish")
        self.assertEqual(text, "<folder>/bulletin.json failed")

    def test_email_addresses_are_removed(self):
        text = report.redact("sent by rector.one+x@example.org to warden@example.co.uk", home="/x/y", folder="/x/y")
        self.assertNotIn("@", text)
        self.assertEqual(text.count("<email>"), 2)

    def test_long_detail_keeps_its_end(self):
        text = report.redact("a" * 4000 + "THE END", home="/x/y", folder="/x/y")
        self.assertEqual(len(text), report.DETAIL_LIMIT)
        self.assertTrue(text.startswith("..."))
        self.assertTrue(text.endswith("THE END"))


class PayloadTests(unittest.TestCase):
    def test_build_has_only_the_fixed_fields(self):
        built = report.build("setup", "windows-app-control", "detail", host="codex")
        self.assertEqual(sorted(built), ["payload", "text"])
        self.assertEqual(sorted(built["payload"]), sorted(report.FIELDS))
        manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(built["payload"]["plugin_version"], manifest["version"])
        self.assertIn(built["payload"]["os"], {"windows", "macos", "linux"})
        self.assertLessEqual(len(built["payload"]["os_version"]), 40)

    def test_refused_fields_never_appear(self):
        for extra in ({"church": "Synthetic Parish"}, {"email": "a@example.org"}, {"sermon": "text"}):
            with self.subTest(extra=extra), self.assertRaises(report.ReportError):
                report.validate({**payload(), **extra})
        result = {"operation": "setup", "status": "install-failed", "technical_detail": "boom",
                  "church": "Synthetic Parish", "runtime": {"root": f"{USERS}/someone/x"}}
        job, code, detail = report.from_runtime_result(result)
        built = report.build(job, code, detail, host="other")
        self.assertNotIn("Synthetic Parish", json.dumps(built))
        self.assertNotIn("runtime", built["payload"])

    def test_bad_values_are_refused(self):
        for changes in ({"job": "Set Up"}, {"error_code": "x" * 61}, {"os": "beos"}, {"host": "vim"},
                        {"plugin_version": ""}, {"detail": 5}):
            with self.subTest(changes=changes), self.assertRaises(report.ReportError):
                report.validate({**payload(), **changes})

    def test_shown_text_carries_every_sent_value(self):
        clean = payload(detail="line one\nline two")
        text = report.render_text(clean)
        for name in report.FIELDS:
            if name not in {"os", "host"}:
                self.assertIn(clean[name], text, name)
        self.assertIn("Windows 11", text)
        self.assertIn("Claude Code", text)

    def test_build_cli_reads_a_runtime_result_on_stdin(self):
        result = {"operation": "verify", "status": "install-failed", "blocked_by": "windows-app-control",
                  "technical_detail": f"blocked at {HOME}/someone/.local/share/handbuilt/x.so by me@example.org"}
        completed = subprocess.run([sys.executable, str(TOOL), "build"], input=json.dumps(result),
                                   capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        built = json.loads(completed.stdout)
        self.assertEqual(built["payload"]["job"], "verify")
        self.assertEqual(built["payload"]["error_code"], "windows-app-control")
        self.assertNotIn("someone", completed.stdout)
        self.assertNotIn("example.org", completed.stdout)
        self.assertEqual(built["text"], report.render_text(built["payload"]))


class SendTests(unittest.TestCase):
    def run_send(self, url, data, **env):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"HANDBUILT_NO_REPORTS", "HANDBUILT_REPORT_URL"}}
        environment.update({"HANDBUILT_REPORT_URL": url, **env})
        return subprocess.run([sys.executable, str(TOOL), "send"], input=json.dumps(data),
                              capture_output=True, text=True, encoding="utf-8", timeout=30, env=environment)

    def test_201_prints_the_report_number_and_sends_the_shown_payload(self):
        built = {"text": report.render_text(payload()), "payload": payload()}
        with Stub(201, b'{"report": "HB-1A2B3C"}') as stub:
            completed = self.run_send(stub.url, built)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("HB-1A2B3C", completed.stdout)
        self.assertEqual(stub.handler.received, [{"content_type": "application/json", "body": payload()}])

    def test_429_prints_the_text_to_copy(self):
        with Stub(429, b'{"error": "slow down"}') as stub:
            completed = self.run_send(stub.url, payload())
        self.assertEqual(completed.returncode, 1)
        self.assertIn(report.render_text(payload()), completed.stdout)
        self.assertIn("Copy this into an email to hello@gethandbuilt.com", completed.stdout)

    def test_connection_refused_prints_the_text_to_copy(self):
        stub = Stub(201)
        url = stub.url
        stub.server.server_close()
        completed = self.run_send(url, payload())
        self.assertEqual(completed.returncode, 1)
        self.assertIn("could not reach Handbuilt", completed.stdout)
        self.assertIn(report.render_text(payload()), completed.stdout)
        self.assertIn(report.COPY_LINE, completed.stdout)

    def test_no_reports_setting_refuses_to_send(self):
        with Stub(201, b'{"report": "HB-1A2B3C"}') as stub:
            completed = self.run_send(stub.url, payload(), HANDBUILT_NO_REPORTS="1")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(stub.handler.received, [])
        self.assertIn("turned off", completed.stdout)
        self.assertIn(report.COPY_LINE, completed.stdout)

    def test_send_refuses_extra_fields(self):
        with Stub(201) as stub:
            completed = self.run_send(stub.url, {**payload(), "church": "Synthetic Parish"})
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(stub.handler.received, [])

    def test_body_stays_under_the_size_limit(self):
        for character in ("\u4e00", "\U0001f600", '"'):
            clean = payload(detail=character * 5000, os_version="9" * 80)
            self.assertLess(len(report.encode(clean)), report.MAX_BODY_BYTES)


class OfferTests(unittest.TestCase):
    def test_failed_and_blocked_results_offer_a_report(self):
        for result, code in (
            ({"status": "install-failed", "next_action": "Repair."}, "install-failed"),
            ({"status": "python-unavailable", "next_action": "Repair."}, "python-unavailable"),
            ({"status": "ready", "blocked_by": "windows-app-control", "next_action": "Tell."}, "windows-app-control"),
            ({"status": "ready", "pdf_tools": {"ready": False, "blocked_by": None}, "next_action": "Go."},
             "pdf-check-failed"),
        ):
            with self.subTest(code=code):
                offered = runtime.report_offer(dict(result), "setup")
                self.assertEqual(offered["problem_report"]["error_code"], code)
                self.assertIn('"Send Stephen a report?"', offered["next_action"])
                self.assertIn("Never send without a yes", offered["next_action"])
                self.assertEqual(offered["problem_report"]["build"][-4:],
                                 ["--job", "setup", "--error-code", code])

    def test_ready_and_setup_needed_results_offer_nothing(self):
        for status in ("ready", "python-package-missing", "native-tool-missing"):
            with self.subTest(status=status):
                self.assertNotIn("problem_report", runtime.report_offer({"status": status, "next_action": "x"}, "doctor"))

    def test_offer_is_added_once(self):
        result = runtime.report_offer({"status": "install-failed", "next_action": "x"}, "verify")
        again = runtime.report_offer(result, "verify")
        self.assertEqual(again["next_action"].count("Send Stephen a report?"), 1)

    def test_runtime_cli_json_carries_the_offer(self):
        failed = {"schema_version": 1, "operation": "verify", "status": "install-failed", "ready": False,
                  "message": "m", "next_action": "Repair.", "blocked_by": "windows-app-control"}
        with mock.patch.object(runtime.RuntimeManager, "verify", return_value=failed), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            runtime.main(["verify", "--format", "json"])
        printed = json.loads(out.getvalue())
        self.assertEqual(printed["problem_report"]["error_code"], "windows-app-control")

    def test_church_launcher_keeps_the_runtime_offer(self):
        check = runtime.report_offer({"status": "install-failed", "next_action": "Repair.",
                                      "technical_detail": "boom"}, "verify")
        completed = subprocess.CompletedProcess([], 1, stdout=json.dumps(check), stderr="")
        with mock.patch.object(church_workflow.subprocess, "run", return_value=completed):
            blocked = church_workflow._doctor("bulletin")
        self.assertEqual(blocked["problem_report"], check["problem_report"])
        self.assertIn("Send Stephen a report?", blocked["next_action"])
        self.assertEqual(report.from_runtime_result(blocked), ("verify", "install-failed", "boom"))


if __name__ == "__main__":
    unittest.main()


class HostDetectionTests(unittest.TestCase):
    """The agent app is named from a few named settings, never the whole environment."""

    def test_names_the_agent_app_from_named_settings_only(self) -> None:
        from tools import problem_report as report
        clean = {"PATH": os.environ.get("PATH", ""), "GITHUB_TOKEN": "secret-value"}
        with mock.patch.dict(os.environ, {**clean, "CLAUDECODE": "1"}, clear=True):
            self.assertEqual(report.detect_host(), "claude-code")
        with mock.patch.dict(os.environ, {**clean, "CODEX_SANDBOX": "seatbelt"}, clear=True):
            self.assertEqual(report.detect_host(), "codex")
        with mock.patch.dict(os.environ, {**clean, "CODEX_SOMETHING_ELSE": "1"}, clear=True):
            self.assertEqual(report.detect_host(), "other")

    def test_the_bundled_prayer_book_readings_stay_compact(self) -> None:
        folder = Path(__file__).parents[1] / "skills" / "bulletin" / "resources" / "bcp1979"
        parts = sorted(folder.glob("sunday-*.json"))
        self.assertEqual(len(parts), 3)
        for data in parts:
            self.assertLess(data.stat().st_size, 256 * 1024, "the plugin directory can't read larger files")
            self.assertNotIn("\n  ", data.read_text(encoding="utf-8"))
