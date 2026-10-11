#!/usr/bin/env python3
"""A read-only QuickBooks connector for one eval church, for skill runs.

It offers the reads the finance skills make through Intuit's QuickBooks connector (company
info, the balance sheet split by month, profit and loss), in the connector's own shapes, built
from the church's books (books.py). Like the real connector, a profit and loss stops at 100 rows
without saying so. It has no tool that writes. Each call is appended to the file named by
EVAL_QBO_LOG, so a grader can see what the run read.

    claude -p ... --mcp-config '{"mcpServers": {"Intuit_QuickBooks": {"command": "python3",
        "args": ["evals/finance/quickbooks_stub.py", "cedar_hollow"]}}}'

It speaks MCP over stdio (JSON-RPC, one message per line) with no dependencies.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books as B  # noqa: E402
from churches import ALL  # noqa: E402

TOOLS = [
    {"name": "company_info", "description": "Read the connected QuickBooks company's name and details. Call first.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "qbo_accounting_get_balance_sheet",
     "description": "Read the balance sheet as JSON. start_date and end_date are YYYY-MM-DD; split_by may be month.",
     "inputSchema": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"},
                                                      "split_by": {"type": "string"}}, "required": ["end_date"]}},
    {"name": "profit_loss_quickbooks_account",
     "description": "Read profit and loss for a period as JSON. periodStart and periodEnd are YYYY-MM-DD.",
     "inputSchema": {"type": "object", "properties": {"periodStart": {"type": "string"}, "periodEnd": {"type": "string"}},
                     "required": ["periodStart", "periodEnd"]}},
]


def month_of(text):
    day = date.fromisoformat(text)
    return day.year, day.month


def call(books: B.Books, name: str, args: dict) -> dict:
    if name == "company_info":
        return books.company_info()
    if name == "qbo_accounting_get_balance_sheet":
        if args.get("split_by") not in (None, "", "month"):
            raise ValueError("this test company only serves the balance sheet split by month")
        end = min(month_of(args["end_date"]), books.last)
        return books.balance_sheet(end)
    if name == "profit_loss_quickbooks_account":
        start, end = month_of(args["periodStart"]), min(month_of(args["periodEnd"]), books.last)
        return books.pl(start, end, limit=B.CONNECTOR_ROW_LIMIT)
    raise ValueError(f"unknown tool {name}")


def handle(books, message, log=None):
    """One JSON-RPC message in, one reply out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "eval-quickbooks", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        name, args = params.get("name", ""), params.get("arguments") or {}
        try:
            body, error = json.dumps(call(books, name, args)), False
        except (KeyError, ValueError) as problem:
            body, error = f"QuickBooks could not answer: {problem}", True
        if log:
            with Path(log).open("a") as out:
                out.write(json.dumps({"tool": name, "arguments": args, "error": error}) + "\n")
        result = {"content": [{"type": "text", "text": body}], "isError": error}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in ALL:
        sys.exit(f"name one eval church: {', '.join(ALL)}")
    books = B.Books(ALL[argv[0]].CHURCH)
    log = os.environ.get("EVAL_QBO_LOG")
    for line in sys.stdin:
        if line.strip():
            reply = handle(books, json.loads(line), log)
            if reply is not None:
                print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
