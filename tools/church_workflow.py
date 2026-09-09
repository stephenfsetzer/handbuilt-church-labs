#!/usr/bin/env python3
"""Connect a private church to the installed plugin and run its public tools.

This adapter selects the managed interpreter and records which installation
ran. Workflow decisions remain in each skill's existing implementation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {
    "onboarding": "skills/onboarding/scripts/church_setup.py",
    "brand": "skills/onboarding/scripts/brand_setup.py",
    "bulletin": "skills/bulletin/scripts/bulletin_production.py",
    "sermon-research": "skills/sermon-research/scripts/sermon_workflow.py",
}
OPERATIONS = {
    "onboarding": {"status", "update", "resolve-person"},
    "brand": {"status", "update"},
    "bulletin": {"orient", "produce", "revise", "finalize"},
    "sermon-research": {"orient", "record"},
}


def _load_setup():
    path = ROOT / WORKFLOWS["onboarding"]
    spec = importlib.util.spec_from_file_location("handbuilt_church_setup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _private_file(church: Path, relative: str) -> Path:
    church = church.resolve()
    path = church / relative
    if path.is_symlink() or not path.resolve().is_relative_to(church):
        raise ValueError("Handbuilt connection files must stay inside the private church folder")
    return path


def installation() -> dict:
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("name") != "handbuilt-church-labs":
        raise ValueError("This is not a Handbuilt Church Labs installation")
    return {
        "plugin_name": manifest["name"], "plugin_version": manifest["version"],
        "plugin_root": str(ROOT),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "entrypoint_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def connect(church_folder: str | Path) -> dict:
    church = _load_setup()._assert_private_root(church_folder)
    metadata = _private_file(church, ".handbuilt/installation.json")
    launcher = _private_file(church, "handbuilt.py")
    source = ROOT / "scaffold/church-folder/handbuilt.py"
    expected = source.read_bytes()
    if launcher.exists() and launcher.read_bytes() != expected:
        old = json.loads(metadata.read_text()) if metadata.exists() else {}
        if hashlib.sha256(launcher.read_bytes()).hexdigest() != old.get("launcher_sha256"):
            raise ValueError("The church's handbuilt.py was customized; preserve it and review before reconnecting")
    info = installation()
    info.update({"schema_version": 1, "launcher_sha256": hashlib.sha256(expected).hexdigest()})
    metadata.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_bytes(expected)
    metadata.write_text(json.dumps(info, indent=2) + "\n")
    return {"status": "connected", "church_folder": str(church), "installation": info,
            "next_action": "Run python3 handbuilt.py start onboarding from the church folder."}


def _doctor() -> dict:
    result = subprocess.run([sys.executable, str(ROOT / "tools/handbuilt_runtime.py"),
                             "doctor", "--format", "json"], capture_output=True, text=True)
    report = json.loads(result.stdout)
    if report.get("status") != "ready":
        return {"status": "blocked", "code": "runtime_not_ready", "runtime_check": report,
                "next_action": "Use python3 handbuilt.py runtime setup, then repeat the runtime check. For native tools, follow the doctor's host setup plan."}
    return report


def _record(church: Path, workflow: str, operation: str, result: dict, runtime: dict) -> Path:
    path = _private_file(church, f".handbuilt/runs/{uuid.uuid4()}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    script = ROOT / WORKFLOWS[workflow]
    record = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "installation": installation(), "workflow": workflow, "operation": operation,
              "script": str(script), "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
              "runtime_python": runtime["runtime"]["python"],
              "status": result.get("status"),
              "production_receipt": result.get("receipt") or result.get("receipt_path")}
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def execute(church: Path, workflow: str, operation: str, arguments: list[str]) -> tuple[dict, int]:
    church = _load_setup()._assert_private_root(church)
    if operation not in OPERATIONS[workflow]:
        raise ValueError(f"Unsupported {workflow} operation: {operation}")
    if any(arg == "--church-folder" or arg.startswith("--church-folder=") for arg in arguments):
        raise ValueError("The church folder comes from this launcher and cannot be overridden")
    doctor = _doctor()
    if doctor.get("status") != "ready":
        return doctor, 2
    script = ROOT / WORKFLOWS[workflow]
    if not script.is_file():
        raise ValueError(f"The installed {workflow} tool is missing. Reinstall Handbuilt; do not substitute another workflow.")
    # A launcher never replaces the production interface's source and approval
    # checks. It also verifies brand readiness before a new bulletin build.
    if workflow == "bulletin" and operation in {"produce", "revise"}:
        brand_script = ROOT / WORKFLOWS["brand"]
        check = subprocess.run([doctor["runtime"]["python"], str(brand_script), "status",
                                "--church-folder", str(church)], capture_output=True, text=True)
        brand = json.loads(check.stdout)
        if not brand.get("ready"):
            return {"status": "blocked", "code": "brand_not_ready", "brand": brand}, 2
    command = [doctor["runtime"]["python"], str(script), operation]
    if not (workflow == "bulletin" and operation == "finalize"):
        command += ["--church-folder", str(church)]
    else:
        # Finalization accepts a receipt instead of a church-folder argument.
        # Keep that receipt in this church even though the underlying CLI can
        # also be used directly by maintainers.
        for index, value in enumerate(arguments):
            if value == "--receipt" and index + 1 < len(arguments):
                if not (church / arguments[index + 1]).resolve().is_relative_to(church):
                    raise ValueError("Finalize only a receipt inside this church folder")
            elif value.startswith("--receipt="):
                if not (church / value.split("=", 1)[1]).resolve().is_relative_to(church):
                    raise ValueError("Finalize only a receipt inside this church folder")
    process = subprocess.run(command + arguments, cwd=church, capture_output=True, text=True)
    try:
        result = json.loads(process.stdout)
    except ValueError:
        result = {"status": "blocked", "code": "workflow_failed",
                  "message": process.stderr[-2000:] or process.stdout[-2000:]}
    if process.returncode and result.get("status") in {"ok", "recorded", "ready_for_review", "approved"}:
        result = {"status": "blocked", "code": "workflow_failed", "detail": result}
    record = _record(church, workflow, operation, result, doctor)
    result["handbuilt_run"] = str(record)
    result["installation"] = installation()
    return result, process.returncode or (2 if result.get("status") in {"blocked", "failed", "error"} else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Use the installed Handbuilt workflows for a private church")
    parser.add_argument("--church-folder", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connect")
    start = sub.add_parser("start")
    start.add_argument("workflow", choices=("onboarding", "bulletin", "sermon-research"))
    runtime = sub.add_parser("runtime")
    runtime.add_argument("operation", choices=("doctor", "setup", "native-install"))
    for name in WORKFLOWS:
        command = sub.add_parser(name)
        command.add_argument("operation", choices=sorted(OPERATIONS[name]))
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        church = _load_setup()._assert_private_root(args.church_folder)
        if args.command == "connect":
            result, code = connect(church), 0
        elif args.command == "runtime":
            return subprocess.run([sys.executable, str(ROOT / "tools/handbuilt_runtime.py"),
                                   args.operation, "--format", "json"]).returncode
        elif args.command == "start":
            doctor = _doctor()
            if doctor.get("status") != "ready":
                result, code = doctor, 2
            else:
                skill = ROOT / "skills" / args.workflow / "SKILL.md"
                if not skill.is_file():
                    raise ValueError("The requested Handbuilt skill is missing; repair the installation")
                result, code = {"status": "ready", "installation": installation(),
                                "skill": str(skill), "runtime_python": doctor["runtime"]["python"],
                                "next_action": "Read this exact skill and use this church's handbuilt.py for its supported operations. Ready here means the tools are available; check workflow readiness before producing."}, 0
                result["handbuilt_run"] = str(_record(church, args.workflow, "start", result, doctor))
        else:
            result, code = execute(church, args.command, args.operation, args.arguments)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result, code = {"status": "blocked", "code": "handbuilt_connection_error", "message": str(exc)}, 2
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
