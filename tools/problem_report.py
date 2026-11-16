#!/usr/bin/env python3
"""Build and send a short problem report to Stephen at Handbuilt.

The pastor sees the exact text first, and nothing is sent without their yes.
A report holds seven fixed fields and nothing else: the plugin version, the
operating system and its version, the agent app, the job, a short error code
and a redacted technical detail. No church names, files, sermon text or
account details go in it.

    build  Print JSON with ``text`` (what the pastor is shown) and ``payload``
           (what would be sent). Takes --job, --error-code and --detail, or
           reads a runtime result as JSON on stdin.
    send   Read that JSON (or the payload alone) on stdin and send it. On
           success print the report number. On any failure print the same text
           to copy into an email, and exit nonzero.

Standard library only, so it runs before Handbuilt's own tools are prepared.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://gethandbuilt.com/api/labs/report"
CONTACT = "hello@gethandbuilt.com"
COPY_LINE = f"Copy this into an email to {CONTACT}"
TIMEOUT_SECONDS = 10
MAX_BODY_BYTES = 8 * 1024
DETAIL_LIMIT = 1500
OS_VERSION_LIMIT = 40
SLUG = re.compile(r"[a-z0-9-]{1,60}")
REPORT_NUMBER = re.compile(r"HB-[A-Z0-9]{1,20}")
FIELDS = ("plugin_version", "os", "os_version", "host", "job", "error_code", "detail")
OS_NAMES = {"windows": "Windows", "macos": "Mac", "linux": "Linux"}
HOST_NAMES = {"claude-code": "Claude Code", "codex": "Codex", "other": "another app"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# A user folder on any of the three systems, with forward or (escaped) back slashes.
# A Windows user name can hold spaces, so a name followed by a slash may be several words.
_NAME = r"[^\\/\s\"':;,]+"
USER_FOLDER = re.compile(
    r"(?:[A-Za-z]:(?:\\+|/)Users(?:\\+|/)|(?<![\w.~-])/" + "Users/|(?<![\\w.~-])/" + "home/)"
    rf"(?:{_NAME}(?: {_NAME})*(?=[\\/])|{_NAME})",
    re.IGNORECASE,
)


class ReportError(ValueError):
    """The report is malformed; nothing was sent."""


def plugin_version(root: Path = ROOT) -> str:
    manifest = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+-]{1,40}", version):
        raise ReportError("The plugin manifest has no usable version.")
    return version


def detect_os(system: Optional[str] = None) -> str:
    system = (system or platform.system()).lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def detect_os_version(os_name: str) -> str:
    if os_name == "macos":
        version = platform.mac_ver()[0] or platform.release()
    elif os_name == "windows":
        version = " ".join(part for part in (platform.release(), platform.version()) if part)
    else:
        version = platform.release()
    return _clean_line(version)[:OS_VERSION_LIMIT]


def detect_host(environ: Mapping[str, str] = os.environ) -> str:
    if environ.get("CLAUDECODE") == "1":
        return "claude-code"
    if any(name.startswith("CODEX_") for name in environ):
        return "codex"
    return "other"


def _clean_line(value: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()


def redact(detail: str, *, home: Optional[str] = None, folder: Optional[str] = None) -> str:
    """Remove personal paths and email addresses, then keep the last 1500 characters.

    The end of an error is the useful part, so a long detail keeps its tail.
    """
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(detail))
    home = home if home is not None else str(Path.home())
    folder = folder if folder is not None else os.getcwd()
    # The working folder is usually the church folder; its name stays private.
    if folder and home and folder.rstrip("\\/") != home.rstrip("\\/") and len(folder) > len(home):
        text = _replace_path(text, folder, "<folder>")
    if home and len(home) > 1:
        text = _replace_path(text, home, "~")
    text = USER_FOLDER.sub("~", text)
    text = EMAIL.sub("<email>", text)
    text = text.strip()
    if len(text) > DETAIL_LIMIT:
        text = "..." + text[-(DETAIL_LIMIT - 3):]
    return text


def _replace_path(text: str, path: str, replacement: str) -> str:
    variants = {path, path.replace("\\", "/"), path.replace("/", "\\"), path.replace("\\", "\\\\")}
    for variant in sorted(variants, key=len, reverse=True):
        text = re.sub(re.escape(variant), lambda _match: replacement, text, flags=re.IGNORECASE)
    return text


def validate(payload: object) -> dict[str, str]:
    """Return a clean payload with only the fixed fields, or raise ReportError."""
    if not isinstance(payload, Mapping):
        raise ReportError("A report must be a JSON object.")
    extra = sorted(set(payload) - set(FIELDS))
    if extra:
        raise ReportError("A report carries only its fixed fields; remove: " + ", ".join(extra))
    clean = {}
    for name in FIELDS:
        value = payload.get(name, "")
        if not isinstance(value, str):
            raise ReportError(f"Report field {name} must be text.")
        clean[name] = value
    if not clean["plugin_version"]:
        raise ReportError("A report needs the plugin version.")
    if clean["os"] not in OS_NAMES:
        raise ReportError("Report field os must be windows, macos or linux.")
    if clean["host"] not in HOST_NAMES:
        raise ReportError("Report field host must be claude-code, codex or other.")
    for name in ("job", "error_code"):
        if not SLUG.fullmatch(clean[name]):
            raise ReportError(f"Report field {name} must be 1 to 60 lowercase letters, digits or hyphens.")
    clean["os_version"] = _clean_line(clean["os_version"])[:OS_VERSION_LIMIT]
    clean["detail"] = redact(clean["detail"])
    return clean


def build(job: str, error_code: str, detail: str = "", *, host: Optional[str] = None,
          root: Path = ROOT) -> dict[str, object]:
    os_name = detect_os()
    payload = validate({
        "plugin_version": plugin_version(root),
        "os": os_name,
        "os_version": detect_os_version(os_name),
        "host": host or detect_host(),
        "job": job,
        "error_code": error_code,
        "detail": detail,
    })
    return {"text": render_text(payload), "payload": payload}


def render_text(payload: Mapping[str, str]) -> str:
    """The exact words the pastor sees before saying yes; every sent field is here."""
    computer = OS_NAMES[payload["os"]] + (f" {payload['os_version']}" if payload["os_version"] else "")
    lines = [
        "Handbuilt Church Labs problem report",
        f"Plugin version: {payload['plugin_version']}",
        f"Computer: {computer}",
        f"Agent app: {HOST_NAMES[payload['host']]}",
        f"Job: {payload['job']}",
        f"Problem: {payload['error_code']}",
        "Technical detail:",
        payload["detail"] or "(none)",
        "",
        "This report has no church names, files or sermon text. It goes only to Stephen at Handbuilt.",
    ]
    return "\n".join(lines)


def from_runtime_result(result: Mapping[str, object]) -> tuple[str, str, str]:
    """Job, error code and detail from a handbuilt_runtime or church_workflow JSON result."""
    pdf_tools = result.get("pdf_tools") if isinstance(result.get("pdf_tools"), Mapping) else {}
    offer = result.get("problem_report") if isinstance(result.get("problem_report"), Mapping) else {}
    job = str(offer.get("job") or result.get("operation") or "setup")
    code = str(offer.get("error_code") or result.get("blocked_by") or pdf_tools.get("blocked_by")
               or result.get("code") or result.get("status") or "unknown")
    detail = str(result.get("technical_detail") or pdf_tools.get("technical_detail") or "")
    inner = result.get("runtime_check")
    if not detail and isinstance(inner, Mapping):
        detail = from_runtime_result(inner)[2]
    return _slug(job), _slug(code), detail


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:60] or "unknown"


def offer(job: str, error_code: str) -> dict[str, object]:
    """What a failed result carries so the host agent can offer a report."""
    return {
        "job": _slug(job),
        "error_code": _slug(error_code),
        "build": [sys.executable, str(ROOT / "tools/problem_report.py"), "build",
                  "--job", _slug(job), "--error-code", _slug(error_code)],
        "send": [sys.executable, str(ROOT / "tools/problem_report.py"), "send"],
    }


OFFER_NEXT_ACTION = (
    "Then ask the pastor: \"Send Stephen a report?\" To prepare it, run the problem_report.build "
    "command with this JSON result on stdin; show the pastor its text exactly as printed. Only after "
    "the pastor says yes, run problem_report.send with that build output on stdin. Never send without "
    "a yes. If sending fails, give the pastor the printed text to email instead."
)


def with_offer(result: dict, job: str, error_code: str) -> dict:
    """Add the report offer to a failed result, once."""
    if "problem_report" not in result:
        result["problem_report"] = offer(job, error_code)
        result["next_action"] = (str(result.get("next_action", "")).rstrip() + " " + OFFER_NEXT_ACTION).strip()
    return result


def encode(payload: Mapping[str, str]) -> bytes:
    """The request body: compact UTF-8 JSON, so 1500 characters of any script fit in 8 KB."""
    return json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def send(payload: Mapping[str, str], *, url: Optional[str] = None) -> tuple[bool, str]:
    """Send a validated payload. Returns (sent, message for the pastor)."""
    text = render_text(payload)
    fallback = f"{text}\n\n{COPY_LINE}"
    if os.environ.get("HANDBUILT_NO_REPORTS") == "1":
        return False, f"Sending reports is turned off on this computer.\n\n{fallback}"
    body = encode(payload)
    if len(body) >= MAX_BODY_BYTES:
        return False, f"The report is too large to send.\n\n{fallback}"
    request = urllib.request.Request(
        url or os.environ.get("HANDBUILT_REPORT_URL") or DEFAULT_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": f"handbuilt-church-labs/{payload['plugin_version']}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            answer = response.read(4096)
    except urllib.error.HTTPError as error:
        reasons = {413: "the report was too large", 429: "too many reports were sent recently",
                   503: "the report service is not available right now"}
        reason = reasons.get(error.code, f"the report service answered {error.code}")
        return False, f"The report was not sent: {reason}.\n\n{fallback}"
    except (urllib.error.URLError, OSError, ValueError):
        return False, f"The report was not sent: this computer could not reach Handbuilt.\n\n{fallback}"
    if status != 201:
        return False, f"The report was not sent: the report service answered {status}.\n\n{fallback}"
    try:
        number = json.loads(answer.decode("utf-8")).get("report", "")
    except (ValueError, AttributeError, UnicodeDecodeError):
        number = ""
    if isinstance(number, str) and REPORT_NUMBER.fullmatch(number):
        return True, f"Report sent to Stephen. Report number: {number}"
    return True, "Report sent to Stephen."


def _read_stdin() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    built = commands.add_parser("build", help="Print the report text and payload as JSON. Sends nothing.")
    built.add_argument("--job")
    built.add_argument("--error-code")
    built.add_argument("--detail")
    built.add_argument("--host", choices=sorted(HOST_NAMES))
    commands.add_parser("send", help="Send the report JSON on stdin. Run only after the pastor says yes.")
    args = parser.parse_args(argv)

    if args.command == "build":
        job, code, detail = args.job, args.error_code, args.detail
        if detail is None:
            raw = _read_stdin().strip()
            if raw:
                try:
                    result = json.loads(raw)
                except ValueError:
                    result = None
                if isinstance(result, Mapping):
                    found_job, found_code, detail = from_runtime_result(result)
                    job, code = job or found_job, code or found_code
                else:
                    detail = raw
        if not job or not code:
            print("build needs --job and --error-code, or a runtime result on stdin.", file=sys.stderr)
            return 2
        try:
            report = build(job, code, detail or "", host=args.host)
        except (ReportError, OSError, ValueError) as error:
            print(f"Could not prepare the report: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2))
        return 0

    try:
        data = json.loads(_read_stdin())
        payload = validate(data.get("payload", data) if isinstance(data, Mapping) else data)
    except (ReportError, ValueError, AttributeError) as error:
        print(f"Nothing was sent: {error}", file=sys.stderr)
        return 2
    sent, message = send(payload)
    print(message)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
