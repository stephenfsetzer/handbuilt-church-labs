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
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def connect(church_folder: str | Path, *, update_policy: str | None = None,
            _automatic: bool = False) -> dict:
    from tools.workflow_updates import file_lock
    church = _load_setup()._assert_private_root(church_folder)
    lock = _private_file(church, ".handbuilt/connection.lock")
    with file_lock(lock) as acquired:
        if not acquired:
            raise ValueError("Another task is connecting this church. Try starting again.")
        return _connect(church, update_policy=update_policy,
                        automatic=_automatic or update_policy is None)


def _connect(church_folder: str | Path, *, update_policy: str | None, automatic: bool) -> dict:
    church = _load_setup()._assert_private_root(church_folder)
    metadata = _private_file(church, ".handbuilt/installation.json")
    launcher = _private_file(church, "handbuilt.py")
    source = ROOT / "scaffold/church-folder/handbuilt.py"
    expected = source.read_bytes()
    old = json.loads(metadata.read_text()) if metadata.exists() else {}
    if not isinstance(old, dict):
        raise ValueError("The church connection is invalid; preserve it for review.")
    if automatic and old.get("plugin_root") and Path(old["plugin_root"]).resolve() != ROOT.resolve():
        from tools.workflow_updates import version
        if old.get("update_policy") == "pinned" or (Path(old["plugin_root"]) / ".git").exists():
            raise ValueError("Another task pinned this church's connection; preserve it.")
        if version(old["plugin_version"]) > version(installation()["plugin_version"]):
            return {"status": "preserved", "installation": old}
    policy = update_policy or old.get("update_policy") or ("pinned" if (ROOT / ".git").exists() else "stable")
    if policy not in {"pinned", "stable"}:
        raise ValueError("Choose stable or pinned workflow updates.")
    if launcher.exists() and launcher.read_bytes() != expected:
        old = json.loads(metadata.read_text()) if metadata.exists() else {}
        if hashlib.sha256(launcher.read_bytes()).hexdigest() != old.get("launcher_sha256"):
            raise ValueError("The church's handbuilt.py was customized; preserve it and review before reconnecting")
    info = installation()
    info.update({"schema_version": 1, "launcher_sha256": hashlib.sha256(expected).hexdigest(),
                 "update_policy": policy})
    metadata.parent.mkdir(parents=True, exist_ok=True)
    originals = {path: path.read_bytes() if path.exists() else None for path in (launcher, metadata)}
    try:
        _atomic_bytes(launcher, expected)
        _atomic_bytes(metadata, (json.dumps(info, indent=2) + "\n").encode())
    except Exception:
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_bytes(path, content)
        raise
    return {"status": "connected", "church_folder": str(church), "installation": info,
            "next_action": "Run python3 handbuilt.py start onboarding from the church folder."}


def _atomic_bytes(path: Path, contents: bytes) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".handbuilt-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _start(church: Path, workflow: str, *, skip_update: bool = False) -> tuple[dict, int]:
    from tools.plugin_identity import inspect_installation
    from tools.handbuilt_runtime import default_runtime_root
    from tools.workflow_updates import select_release, package_version, verify_installed, version
    identity = inspect_installation(ROOT, church)
    metadata = _private_file(church, ".handbuilt/installation.json")
    saved = json.loads(metadata.read_text()) if metadata.exists() else {}
    if not isinstance(saved, dict) or (saved.get("plugin_root") and not Path(saved["plugin_root"]).is_absolute()):
        raise ValueError("The church connection is invalid; preserve it for review.")
    saved_root = Path(saved.get("plugin_root", str(ROOT))).resolve()
    pinned = saved.get("update_policy") == "pinned" or (saved_root / ".git").exists() or (ROOT / ".git").exists()
    if pinned and saved_root != ROOT.resolve():
        return {"status": "blocked", "code": "pinned_connection", "identity": identity,
                "message": "This church has an intentional pinned workflow. Keep using that connection unless a change is requested."}, 2
    selected = ROOT.resolve()
    store = default_runtime_root().parent / "workflows"
    def validate(candidate):
        command = [sys.executable, str(candidate / "tools/handbuilt_runtime.py")]
        command += (["verify"] if workflow == "bulletin" else ["doctor", "--capability", "workspace"])
        try:
            check = subprocess.run(command + ["--format", "json"], capture_output=True, text=True, timeout=90)
            report = json.loads(check.stdout)
        except (subprocess.SubprocessError, ValueError) as exc:
            raise ValueError("The new workflow could not complete its runtime check.") from exc
        if check.returncode or report.get("status") != "ready":
            raise ValueError("The new workflow needs a runtime change; the current workflow was kept.")
    if not pinned and saved_root != selected and saved_root.is_relative_to((store / "releases").resolve()):
        saved_version = verify_installed(saved_root)
        if version(saved_version) >= version(package_version(selected)):
            selected = saved_root
        else:
            try:
                validate(selected)
            except (ValueError, OSError):
                selected = saved_root
    elif not pinned and saved_root != selected and saved_root.is_dir():
        # An explicitly saved host installation can also be newer than this app.
        saved_identity = inspect_installation(saved_root, church)
        if (saved_identity["connection"]["connection_matches"]
                and version(package_version(saved_root)) > version(package_version(selected))):
            validate(saved_root)
            selected = saved_root
    updates = {"status": "pinned" if pinned else "not_checked", "host_plugin_updated": False}
    if not pinned and not skip_update:
        updates = select_release(selected, store, validate)
        selected = Path(updates["selected_root"])
    if selected != ROOT.resolve():
        # The target verifies its runtime again before saving the connection.
        process = subprocess.run([sys.executable, str(selected / "tools/church_workflow.py"),
                                  "--church-folder", str(church), "start", workflow,
                                  "--skip-update-check"], capture_output=True, text=True, timeout=120)
        result = json.loads(process.stdout)
        result["app_loaded_identity"] = identity["loaded"]
        result["updates"] = updates
        result["identity"] = inspect_installation(selected, church, updates.get("latest"))
        return result, process.returncode
    doctor = _doctor(workflow)
    if doctor.get("status") != "ready":
        return doctor, 2
    skill = ROOT / "skills" / workflow / "SKILL.md"
    if not skill.is_file():
        raise ValueError("The requested Handbuilt skill is missing; repair the installation")
    # All checks precede the small, rollback-protected connection write.
    connection = connect(church, update_policy="pinned" if pinned else "stable", _automatic=True)
    if connection["status"] == "preserved":
        return {"status": "blocked", "code": "connection_changed",
                "message": "A newer church connection was preserved. Start again using that saved connection."}, 2
    identity = inspect_installation(ROOT, church, updates.get("latest"))
    result = {"status": "ready", "installation": installation(), "identity": identity,
              "updates": updates, "skill": str(skill), "runtime_python": doctor["runtime"]["python"],
              "launcher": [doctor["runtime"]["python"], str(ROOT / "tools/church_workflow.py"),
                           "--church-folder", str(church)],
              "next_action": "Read this exact skill. Use the returned launcher prefix for every operation in this task; it keeps the workflow version fixed. Check workflow readiness before producing."}
    result["handbuilt_run"] = str(_record(church, workflow, "start", result, doctor))
    return result, 0


def _doctor(workflow: str = "bulletin") -> dict:
    # Keep PDF dependencies and their working check on bulletin operations.
    # Workspace and sermon tools still require the existing managed packages.
    arguments = (["verify"] if workflow == "bulletin"
                 else ["doctor", "--capability", "workspace"])
    result = subprocess.run([sys.executable, str(ROOT / "tools/handbuilt_runtime.py"),
                             *arguments, "--format", "json"], capture_output=True, text=True)
    report = json.loads(result.stdout)
    if report.get("status") != "ready":
        return {"status": "blocked", "code": "runtime_not_ready", "runtime_check": report,
                "next_action": report.get("next_action", "Follow the runtime check's repair plan, then check again.")}
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
    doctor = _doctor(workflow)
    if doctor.get("status") != "ready":
        return doctor, 2
    script = ROOT / WORKFLOWS[workflow]
    if not script.is_file():
        raise ValueError(f"The installed Handbuilt {workflow} tool is missing. Reinstall Handbuilt to use this command. Other work can continue with available tools.")
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
    connection = sub.add_parser("connect")
    connection.add_argument("--update-policy", choices=("stable", "pinned"))
    sub.add_parser("updates")
    start = sub.add_parser("start")
    start.add_argument("workflow", choices=("onboarding", "bulletin", "sermon-research"))
    start.add_argument("--skip-update-check", action="store_true", help=argparse.SUPPRESS)
    runtime = sub.add_parser("runtime")
    runtime.add_argument("operation", choices=("doctor", "verify", "setup", "native-install"))
    runtime.add_argument("--capability", choices=("workspace", "bulletin"))
    for name in WORKFLOWS:
        command = sub.add_parser(name)
        command.add_argument("operation", choices=sorted(OPERATIONS[name]))
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        church = _load_setup()._assert_private_root(args.church_folder)
        if args.command == "connect":
            result, code = connect(church, update_policy=args.update_policy), 0
        elif args.command == "runtime":
            if args.capability and args.operation != "doctor":
                raise ValueError("Choose a capability only for runtime doctor; verify always checks all PDF tools")
            arguments = (["--capability", args.capability] if args.capability else [])
            return subprocess.run([sys.executable, str(ROOT / "tools/handbuilt_runtime.py"),
                                   args.operation, *arguments, "--format", "json"]).returncode
        elif args.command == "updates":
            from tools.plugin_identity import inspect_installation
            result, code = inspect_installation(ROOT, church), 0
        elif args.command == "start":
            result, code = _start(church, args.workflow, skip_update=args.skip_update_check)
        else:
            result, code = execute(church, args.command, args.operation, args.arguments)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result, code = {"status": "blocked", "code": "handbuilt_connection_error", "message": str(exc)}, 2
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
