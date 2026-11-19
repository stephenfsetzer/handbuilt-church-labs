"""A small client for the Handbuilt connector, used by the evals to set up and collect a run.

The connector-only runner gives the agent nothing but the Handbuilt connector, the way a
pastor's own Claude would have it. The church's files therefore live on Handbuilt's server,
not on this computer. Before a run this client copies the seeded church folder up; after
the run it copies the folder back down, so the finished-work graders read the same files
they read on the plugin path.

It speaks MCP's JSON-RPC over HTTP and needs three folder tools on the server:

- ``list_files``: ``{"prefix": str}`` -> ``{"files": [{"path": str, "sha256": str, "size": int}]}``
- ``read_file``: ``{"path": str}`` -> ``{"path": str, "content_base64": str}``
- ``save_file``: ``{"path": str, "content_base64": str}`` -> ``{"path": str, "sha256": str}``

Each tool returns its JSON object as ``structuredContent``. These names and shapes are
the contract PRD-025 phase 2 builds to. A server without them is reported as a setup
problem, never worked around.
"""
from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

FOLDER_TOOLS = ("list_files", "read_file", "save_file")
PROTOCOL = "2025-06-18"
USER_AGENT = "handbuilt-church-labs-eval/1.0"
TOKEN_ENV = "HANDBUILT_CONNECTOR_TOKEN"
URL_ENV = "HANDBUILT_CONNECTOR_URL"


class ConnectorError(RuntimeError):
    """The connector refused, failed, or lacks what the eval needs."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Connector:
    def __init__(self, url: str, token: str, *, timeout: int = 120) -> None:
        if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ConnectorError("The connector address must be https, or http on this computer.")
        if not token:
            raise ConnectorError(f"No connector token. Set {TOKEN_ENV}.")
        self.url, self.token, self.timeout = url, token, timeout
        self.session = ""
        self.ids = itertools.count(1)
        self.ready = False

    @classmethod
    def from_env(cls, url: str = "") -> "Connector":
        return cls(url or os.environ.get(URL_ENV, ""), os.environ.get(TOKEN_ENV, ""))

    def _post(self, message: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Authorization": f"Bearer {self.token}", "User-Agent": USER_AGENT,
                   "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(self.url, data=json.dumps(message).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.session = response.headers.get("Mcp-Session-Id") or self.session
                kind = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise ConnectorError(f"The connector answered {exc.code}: {exc.read()[:300]!r}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectorError(f"The connector could not be reached: {exc}") from exc
        if "id" not in message:
            return None
        if "text/event-stream" in kind:
            data = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
            body = data[-1] if data else ""
        try:
            reply = json.loads(body)
        except ValueError as exc:
            raise ConnectorError(f"The connector sent something that is not JSON: {body[:200]!r}") from exc
        if reply.get("error"):
            raise ConnectorError(f"The connector refused: {reply['error']}")
        return reply.get("result") or {}

    def rpc(self, method: str, params: dict | None = None) -> dict:
        if not self.ready and method != "initialize":
            self.initialize()
        return self._post({"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params or {}}) or {}

    def initialize(self) -> dict:
        result = self._post({"jsonrpc": "2.0", "id": next(self.ids), "method": "initialize", "params": {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "handbuilt-church-labs-eval", "version": "1.0"}}}) or {}
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.ready = True
        return result

    def tools(self) -> list[str]:
        return [tool.get("name", "") for tool in self.rpc("tools/list").get("tools", [])]

    def call(self, name: str, arguments: dict) -> dict:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            text = " ".join(part.get("text", "") for part in result.get("content", []) if isinstance(part, dict))
            raise ConnectorError(f"{name} failed: {text[:300]}")
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise ConnectorError(f"{name} returned no structured result")
        return structured

    def missing_folder_tools(self) -> list[str]:
        have = set(self.tools())
        return [name for name in FOLDER_TOOLS if name not in have]


def push_folder(connector: Connector, local: Path, prefix: str) -> list[dict]:
    """Copy every file under ``local`` to ``prefix`` on the server and confirm each one landed intact."""
    sent = []
    for path in sorted(p for p in local.rglob("*") if p.is_file()):
        data = path.read_bytes()
        remote = f"{prefix.rstrip('/')}/{path.relative_to(local).as_posix()}"
        saved = connector.call("save_file", {"path": remote, "content_base64": base64.b64encode(data).decode()})
        if saved.get("sha256") != sha256(data):
            raise ConnectorError(f"{remote} did not arrive intact")
        sent.append({"path": remote, "size": len(data), "sha256": sha256(data)})
    return sent


def pull_folder(connector: Connector, prefix: str, local: Path) -> list[dict]:
    """Copy every file under ``prefix`` on the server into ``local``, replacing what is there."""
    pulled = []
    prefix = prefix.rstrip("/") + "/"
    for item in connector.call("list_files", {"prefix": prefix}).get("files", []):
        remote = item["path"]
        if not remote.startswith(prefix) or ".." in Path(remote).parts:
            raise ConnectorError(f"The connector listed a file outside the church folder: {remote}")
        data = base64.b64decode(connector.call("read_file", {"path": remote})["content_base64"])
        if item.get("sha256") and item["sha256"] != sha256(data):
            raise ConnectorError(f"{remote} changed while it was being read")
        target = local / remote[len(prefix):]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        pulled.append({"path": remote, "size": len(data), "sha256": sha256(data)})
    return pulled
