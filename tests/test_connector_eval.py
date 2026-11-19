"""The connector-only eval runner: folder copy up and back, isolation, and honest setup failures."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "evals" / "finished_work"), str(REPO / "evals" / "connector")]

import client as K  # noqa: E402
import run as R  # noqa: E402


class FakeConnector(BaseHTTPRequestHandler):
    """An MCP server holding files in memory. ``tools`` and ``files`` are set per test."""

    tools: tuple[str, ...] = K.FOLDER_TOOLS
    files: dict[str, bytes] = {}
    seen_tokens: list[str] = []
    corrupt = False

    def log_message(self, *_):
        pass

    def do_POST(self):
        self.seen_tokens.append(self.headers.get("Authorization", ""))
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "id" not in message:
            self.send_response(202)
            self.end_headers()
            return
        method, params = message["method"], message.get("params", {})
        if method == "initialize":
            result = {"protocolVersion": K.PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": [{"name": name} for name in self.tools]}
        else:
            result = self.call(params["name"], params["arguments"])
        body = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def call(self, name, arguments):
        if name == "save_file":
            data = base64.b64decode(arguments["content_base64"])
            self.files[arguments["path"]] = data
            digest = hashlib.sha256(b"x" if self.corrupt else data).hexdigest()
            return {"structuredContent": {"path": arguments["path"], "sha256": digest}}
        if name == "list_files":
            listed = [{"path": p, "sha256": hashlib.sha256(d).hexdigest(), "size": len(d)}
                      for p, d in self.files.items() if p.startswith(arguments["prefix"])]
            return {"structuredContent": {"files": listed}}
        if name == "read_file":
            data = self.files[arguments["path"]]
            return {"structuredContent": {"path": arguments["path"], "content_base64": base64.b64encode(data).decode()}}
        return {"isError": True, "content": [{"type": "text", "text": "Unknown tool"}]}


class ConnectorEvalTest(unittest.TestCase):
    def setUp(self):
        FakeConnector.tools, FakeConnector.files, FakeConnector.seen_tokens, FakeConnector.corrupt = K.FOLDER_TOOLS, {}, [], False
        self.server = HTTPServer(("127.0.0.1", 0), FakeConnector)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/mcp"
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.server.shutdown()

    def church(self) -> Path:
        church = self.tmp / "riverbend"
        (church / "bulletins").mkdir(parents=True)
        (church / "church.yaml").write_text("name: Riverbend\n", encoding="utf-8")
        (church / "bulletins" / "logo.png").write_bytes(bytes(range(256)) * 4)
        return church

    def test_folder_goes_up_and_comes_back_byte_for_byte(self):
        connector = K.Connector(self.url, "token-for-tests-only-0000")
        church = self.church()
        sent = K.push_folder(connector, church, "evals/x/bulletin-1")
        self.assertEqual(len(sent), 2)
        back = self.tmp / "back"
        K.pull_folder(connector, "evals/x/bulletin-1", back)
        for path in church.rglob("*"):
            if path.is_file():
                self.assertEqual((back / path.relative_to(church)).read_bytes(), path.read_bytes())
        self.assertTrue(all(token == "Bearer token-for-tests-only-0000" for token in FakeConnector.seen_tokens))

    def test_a_file_that_arrives_changed_stops_the_run(self):
        FakeConnector.corrupt = True
        with self.assertRaisesRegex(K.ConnectorError, "did not arrive intact"):
            K.push_folder(K.Connector(self.url, "token-for-tests-only-0000"), self.church(), "evals/x/bulletin-1")

    def test_a_listed_path_outside_the_folder_is_refused(self):
        FakeConnector.files = {"evals/x/bulletin-1/../../secret.txt": b"no"}
        with self.assertRaisesRegex(K.ConnectorError, "outside the church folder"):
            K.pull_folder(K.Connector(self.url, "token-for-tests-only-0000"), "evals/x/bulletin-1", self.tmp / "back")

    def test_missing_folder_tools_are_named(self):
        FakeConnector.tools = ("ask_stephen", "report_problem")
        connector = K.Connector(self.url, "token-for-tests-only-0000")
        self.assertEqual(connector.missing_folder_tools(), list(K.FOLDER_TOOLS))

    def test_no_token_or_plain_http_elsewhere_is_refused(self):
        with self.assertRaisesRegex(K.ConnectorError, "token"):
            K.Connector(self.url, "")
        with self.assertRaisesRegex(K.ConnectorError, "https"):
            K.Connector("http://example.com/api/mcp", "token-for-tests-only-0000")

    def test_todays_connector_fails_at_setup_without_running_the_agent(self):
        FakeConnector.tools = ("ask_stephen", "report_problem", "book_office_hours")
        out = self.tmp / "results"
        with mock.patch.dict("os.environ", {K.TOKEN_ENV: "token-for-tests-only-0000"}), \
                mock.patch.object(R, "converse", side_effect=AssertionError("the agent must not run")):
            record = R.one_run("bulletin", 1, out, "", "sonnet", self.url)
        self.assertFalse(record["clean"])
        self.assertIn("no list_files, read_file, save_file tool", record["setup_problem"])
        self.assertEqual(json.loads((out / "bulletin-1" / "result.json").read_text())["via"], "connector")

    def test_connector_command_has_no_plugin_and_no_local_files(self):
        run_dir = self.tmp
        config = R.connector_config(run_dir, self.url)
        command = R.agent_command("Sunday's bulletin, please", None, "", run_dir, connector=config)
        self.assertNotIn("--plugin-dir", command)
        self.assertNotIn("--add-dir", command)
        self.assertEqual(command[command.index("--tools") + 1], "WebFetch,WebSearch")
        self.assertIn("mcp__handbuilt", command[command.index("--allowedTools") + 1])
        saved = json.loads(config.read_text())["mcpServers"]["handbuilt"]
        self.assertEqual(saved["headers"]["Authorization"], "Bearer ${HANDBUILT_CONNECTOR_TOKEN}")
        self.assertNotIn("token-for-tests", config.read_text())

    def test_connector_isolation_catches_plugins_other_servers_and_local_tools(self):
        good = {"init": {"mcp_servers": [{"name": "handbuilt", "status": "connected"}], "plugins": []}, "uses": []}
        self.assertEqual(R.isolation_problems(good, None), [])
        bad = {"init": {"mcp_servers": [{"name": "handbuilt", "status": "failed"}, {"name": "drive", "status": "connected"}],
                        "plugins": [{"path": "/x/plugin"}]},
               "uses": [{"name": "Bash", "input": {}}, {"name": "mcp__handbuilt__read_file", "input": {}}]}
        problems = " ".join(R.isolation_problems(bad, None))
        for expected in ("only connected server", "plugins were loaded", "local tools were used: ['Bash']"):
            self.assertIn(expected, problems)


if __name__ == "__main__":
    unittest.main()
