#!/usr/bin/env python3
"""Local MCP servers for synthetic QuickBooks reads and a contained skill workspace.

Default mode exposes only the three connector reads. ``--workspace ROOT --plugin
DIR`` exposes file and command tools instead. The model receives no general shell,
network tool, or access to fixture definitions, truth, grades, and host files.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books as B  # noqa: E402
from churches import ALL  # noqa: E402

TOOLS = [
    {"name": "company_info", "description": "Read the connected company's name and details. Call first.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "qbo_accounting_get_balance_sheet", "description": "Read the balance sheet. Dates use YYYY-MM-DD.",
     "inputSchema": {"type": "object", "properties": {"start_date": {"type": "string"},
                     "end_date": {"type": "string"}, "split_by": {"type": "string"}}, "required": ["end_date"],
                     "additionalProperties": False}},
    {"name": "profit_loss_quickbooks_account", "description": "Read profit and loss. Dates use YYYY-MM-DD; split_by can be month.",
     "inputSchema": {"type": "object", "properties": {"periodStart": {"type": "string"},
                     "periodEnd": {"type": "string"}, "split_by": {"type": "string"}},
                     "required": ["periodStart", "periodEnd"], "additionalProperties": False}},
]
WORKSPACE_TOOLS = [
    {"name": "read_file", "description": "Read a UTF-8 file or list a directory inside the church or staged plugin only.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Save a UTF-8 finance file inside the synthetic church. Creates parent directories.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["path", "text"]}},
    {"name": "inspect_pdf", "description": "View both pages of a locally rendered PDF before handing off the draft.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "run_command", "description": "Run a finance workflow command exactly as documented, using the staged church_workflow.py or returned launcher. No shell, pipes, arbitrary programs, or other workflows.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
]


def month_of(text):
    day = date.fromisoformat(text)
    return day.year, day.month


def call(books: B.Books, name: str, args: dict) -> dict:
    schema = next((t["inputSchema"] for t in TOOLS if t["name"] == name), None)
    if schema is None:
        raise ValueError(f"unknown read tool {name}")
    if not isinstance(args, dict) or set(args) - set(schema["properties"]):
        raise ValueError("unknown arguments")
    if any(key not in args for key in schema.get("required", [])):
        raise ValueError("missing required arguments")
    if any(not isinstance(value, str) for value in args.values()):
        raise ValueError("arguments must be text")
    connector = books.church.get("connector", {})
    if name == "company_info":
        return books.company_info()
    if args.get("split_by") not in (None, "", "month"):
        raise ValueError("split_by must be month")
    if name == "profit_loss_quickbooks_account" and connector.get("profile_required"):
        raise ValueError("profile_info_required: company profile fields industry and state are required before profit and loss can be read")
    counts = getattr(books, "_connector_calls", {})
    query = json.dumps([name, args], sort_keys=True)
    counts[query] = counts.get(query, 0) + 1
    books._connector_calls = counts
    pull = max(counts.values())  # Once books change, subsequent reads see the same revision.
    snapshot = books.snapshot(pull=pull) if hasattr(books, "snapshot") else books
    if name == "qbo_accounting_get_balance_sheet":
        end = min(month_of(args["end_date"]), books.last)
        if args.get("start_date") and month_of(args["start_date"]) > end:
            raise ValueError("start date is after the available end date")
        return snapshot.balance_sheet(end)
    start, requested_end = month_of(args["periodStart"]), month_of(args["periodEnd"])
    if date.fromisoformat(args["periodStart"]) > date.fromisoformat(args["periodEnd"]):
        raise ValueError("start date is after end date")
    end = min(requested_end, books.last)
    if start > end:
        raise ValueError("no books for the requested period")
    if hasattr(books, "connector_pl"):
        return books.connector_pl(start, end, split_by=args.get("split_by"), pull=pull)
    return books.pl(start, end, limit=B.CONNECTOR_ROW_LIMIT)


class Workspace:
    """Capability boundary: trusted finance scripts, synthetic files, no arbitrary code."""

    def __init__(self, root: Path, plugin: Path):
        self.root, self.plugin = root.resolve(), plugin.resolve()

    def path(self, value: str, *, write=False) -> Path:
        path = Path(value)
        path = (path if path.is_absolute() else self.root / path).resolve()
        if write:
            allowed = path.is_relative_to(self.root / "finance") and path.suffix in {".json", ".md", ".csv"}
        else:
            allowed = path.is_relative_to(self.root) or path.is_relative_to(self.plugin)
        if not allowed:
            raise ValueError("path is outside the eval workspace")
        return path

    def command(self, value: str) -> dict:
        args = shlex.split(value)
        if len(args) < 3 or Path(args[0]).name not in {"python", "python3"}:
            raise ValueError("use the documented Python workflow command")
        script = self.path(args[1])
        adapter = self.plugin / "tools/church_workflow.py"
        launcher = self.root / "handbuilt.py"
        tail = args[2:]
        if script == adapter:
            if tail[:2] != ["--church-folder", str(self.root)]:
                raise ValueError("use the current church folder with the adapter")
            tail = tail[2:]
            if tail[:1] == ["start"]:
                if len(tail) != 2 or tail[1] not in {"finance-onboarding", "finance-report"}:
                    raise ValueError("only finance workflow start is allowed")
                tail += ["--skip-update-check"]
            elif not tail or tail[0] not in {"finance-onboarding", "finance-report"}:
                raise ValueError("only finance workflows are allowed")
        elif script == launcher:
            if launcher.read_bytes() != (self.plugin / "scaffold/church-folder/handbuilt.py").read_bytes():
                raise ValueError("the launcher changed")
            if not tail or tail[0] not in {"finance-onboarding", "finance-report"}:
                raise ValueError("only finance workflows are allowed")
        else:
            raise ValueError("only the adapter and the returned launcher may run")
        finance_action = bool(tail and tail[0] in {"finance-onboarding", "finance-report"})
        if any(item.startswith("--church-folder") for item in tail):
            raise ValueError("the church folder cannot be overridden")
        # Parse a closed grammar. Production argparse permits abbreviated flags;
        # forwarding those would bypass path checks (for example --balance FILE).
        if finance_action:
            if len(tail) < 2:
                raise ValueError("choose a finance operation")
            operation = tuple(tail[:2])
            index = 2
            schemas = {
                ("finance-onboarding", "orient"): {},
                ("finance-onboarding", "look"): {"--balance-sheet": "file", "--pl-12m": "file", "--clearing-threshold": "text"},
                ("finance-onboarding", "readiness"): {"--item": "text", "--status": "text", "--reason": "text", "--caveat": "text"},
                ("finance-onboarding", "calendar"): {"--books-closed-by": "text", "--report-by": "text", "--meeting": "text", "--approver": "text"},
                ("finance-onboarding", "stage"): {"--done": "text"},
                ("finance-report", "status"): {"--month": "month"},
                ("finance-report", "build"): {"--month": "month", "--prepared": "date", "--balance-sheet": "file", "--pl-ytd": "file", "--pl-prior": "file", "--pl-through": "through", "--unrecorded": "text", "--sample": "flag"},
                ("finance-report", "render"): {"--suffix": "suffix"},
                ("finance-report", "setup", "draft"): {"--balance-sheet": "file", "--pl-12m": "file", "--pl-year": "file"},
                ("finance-report", "setup", "budget"): {"--year": "text", "--csv": "file", "--annual": "text", "--none": "flag"},
                ("finance-report", "setup", "one-time"): {"--year": "text", "--amount": "text", "--label": "text", "--none": "flag", "--done": "flag"},
                ("finance-report", "setup", "apply"): {"--approved-by": "text"},
            }
            if operation == ("finance-report", "setup"):
                operation = tuple(tail[:3])
                index = 3
            if operation not in schemas:
                raise ValueError("unsupported finance operation")
            allowed = schemas[operation]
            positionals = []
            while index < len(tail):
                token = tail[index]
                index += 1
                if not token.startswith("--"):
                    positionals.append(token)
                    continue
                key, sep, value = token.partition("=")
                if key not in allowed:
                    raise ValueError("unknown or abbreviated option")
                kind = allowed[key]
                if kind == "flag":
                    if sep:
                        raise ValueError("flag has no value")
                    continue
                if not sep:
                    if index >= len(tail):
                        raise ValueError("missing option value")
                    value = tail[index]
                    index += 1
                if kind == "file":
                    self.path(value)
                elif kind == "through":
                    month, equal, filename = value.partition("=")
                    if not equal or not re.fullmatch(r"\d{4}-\d{2}", month):
                        raise ValueError("invalid period/file pair")
                    self.path(filename)
                elif kind == "month" and not re.fullmatch(r"\d{4}-\d{2}", value):
                    raise ValueError("invalid month")
                elif kind == "date":
                    date.fromisoformat(value)
                elif kind == "suffix" and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                    raise ValueError("invalid suffix")
            if operation == ("finance-report", "render"):
                if len(positionals) != 1:
                    raise ValueError("render needs one report path")
                report_path = self.path(positionals[0])
                report = json.loads(report_path.read_text())
                if not re.fullmatch(r"\d{4}-\d{2}", report.get("meta", {}).get("month", "")):
                    raise ValueError("invalid report month")
            elif positionals:
                raise ValueError("unexpected positional argument")
        # Config and report files have indirect filesystem inputs too.
        for relative in ("finance/board/config.json", "finance/board/setup-draft.json"):
            path = self.root / relative
            if path.exists():
                config = json.loads(path.read_text())
                if config.get("report_folder", "finance/board") != "finance/board":
                    raise ValueError("eval report_folder must remain finance/board")
        if finance_action and operation == ("finance-report", "render"):
            previous = report.get("meta", {}).get("previous_report")
            if previous:
                self.path(str(report_path.parent / previous))
        # Never inherit model credentials or host service configuration into a workflow.
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "HANDBUILT_RUNTIME_HOME") if key in os.environ}
        env["PYTHONSAFEPATH"] = "1"
        # Trusted workflow HTTP clients must not fetch fonts or updates from live
        # services during an eval. No proxy credentials are inherited here.
        env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                    "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
        command_tail = ["--church-folder", str(self.root), *tail] if script == adapter else tail
        completed = subprocess.run([sys.executable, str(script), *command_tail], cwd=self.root,
                                   env=env, capture_output=True, text=True, timeout=180)
        return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}

    def call(self, name: str, args: dict) -> dict:
        if name == "read_file":
            path = self.path(args["path"])
            return {"text": "\n".join(sorted(p.name for p in path.iterdir())) if path.is_dir() else path.read_text()}
        if name == "write_file":
            path = self.path(args["path"], write=True)
            text = args["text"]
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return {"saved": str(path)}
        if name == "inspect_pdf":
            path = self.path(args["path"])
            if not path.is_relative_to(self.root / "finance") or path.suffix != ".pdf":
                raise ValueError("inspect a finance PDF")
            with tempfile.TemporaryDirectory(prefix="finance-pdf-") as tmp:
                prefix = Path(tmp) / "page"
                subprocess.run(["pdftoppm", "-png", "-scale-to", "1600", "-f", "1", "-l", "2", str(path), str(prefix)],
                               check=True, capture_output=True, timeout=60)
                pages = sorted(Path(tmp).glob("page-*.png"))
                if not pages:
                    raise ValueError("PDF has no readable pages")
                return {"images": [{"type": "image", "mimeType": "image/png",
                                    "data": base64.b64encode(page.read_bytes()).decode()} for page in pages]}
        if name == "run_command":
            return self.command(args["command"])
        raise ValueError(f"unknown workspace tool {name}")


def handle(books, message, log=None):
    """One JSON-RPC message in, one reply out (None for a notification)."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    params = message.get("params", {})
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "invalid params"}}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "finance-eval-local", "version": "2"}}
    elif method == "tools/list":
        result = {"tools": WORKSPACE_TOOLS if isinstance(books, Workspace) else TOOLS}
    elif method == "tools/call":
        name, args = params.get("name", ""), params.get("arguments", {})
        try:
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
            payload = books.call(name, args) if isinstance(books, Workspace) else call(books, name, args)
            body, error = json.dumps(payload), False
        except (KeyError, ValueError, TypeError, IndexError, OSError, subprocess.SubprocessError) as problem:
            payload = {"error": str(problem)}
            body, error = json.dumps(payload), True
        if log:
            with Path(log).open("a") as out:
                out.write(json.dumps({"tool": name, "arguments": args, "error": error, "response": {"pages": len(payload["images"])} if "images" in payload else payload}) + "\n")
        result = {"content": payload["images"] if isinstance(payload, dict) and "images" in payload else [{"type": "text", "text": body}], "isError": error}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("church", nargs="?", choices=list(ALL))
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("--plugin", type=Path)
    args = ap.parse_args(argv)
    if args.workspace and args.plugin:
        server = Workspace(args.workspace, args.plugin)
    elif args.church:
        server = B.Books(ALL[args.church].CHURCH)
    else:
        ap.error("choose a church or a workspace and plugin")
    log = os.environ.get("EVAL_QBO_LOG")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(server, json.loads(line), log)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "invalid JSON"}}
        if reply is not None:
            print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
