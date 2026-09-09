#!/usr/bin/env python3
"""Prepare and inspect the private Handbuilt Church Labs runtime.

The doctor operation is read-only. Python setup mutates only the Handbuilt-owned
per-user support directory. Native-tool setup uses an explicit host operation.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


SCHEMA_VERSION = 1
MINIMUM_PYTHON = (3, 10)
STATUSES = (
    "ready",
    "python-unavailable",
    "python-package-missing",
    "native-tool-missing",
    "install-failed",
)
PACKAGE_IMPORTS = {
    "weasyprint": "weasyprint",
    "pypdf": "pypdf",
    "Pillow": "PIL",
    "PyYAML": "yaml",
    "qrcode[pil]": "qrcode",
}
SAFE_PIP_REQUIREMENT = "pip==26.2.1"
NATIVE_TOOLS = ("pdftoppm", "pdfinfo", "pdffonts", "pdftotext")


def _normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.split("[", 1)[0]).lower()

VERSION_PROBE = (
    "import json,sys; "
    "print(json.dumps({'version': list(sys.version_info[:3])}))"
)
PACKAGE_PROBE = (
    "import importlib.metadata,importlib.util,json,sys; "
    "versions={d.metadata.get('Name','').lower().replace('_','-'):d.version for d in importlib.metadata.distributions()}; "
    "print(json.dumps([{'distribution':(distribution:=item.split('\\x1f',1)[0]),'module':(module:=item.split('\\x1f',1)[1]),'installed':versions.get(distribution.split('[',1)[0].lower().replace('_','-')),'importable':not module or importlib.util.find_spec(module) is not None} for item in sys.argv[1:]]))"
)

Runner = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    environment: Path
    python: Path


def default_runtime_root(
    *,
    system: Optional[str] = None,
    home: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    """Return the per-user support path without creating it."""
    system = system or platform.system()
    home = home or Path.home()
    environ = os.environ if environ is None else environ

    override = environ.get("HANDBUILT_RUNTIME_HOME")
    if override:
        return Path(override).expanduser()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Handbuilt Church Labs" / "runtime"
    if system == "Windows":
        base = Path(environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / "Handbuilt Church Labs" / "runtime"
    base = Path(environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return base / "handbuilt-church-labs" / "runtime"


def runtime_paths(root: Path, *, system: Optional[str] = None) -> RuntimePaths:
    system = system or platform.system()
    environment = root / "python"
    python = (
        environment / "Scripts" / "python.exe"
        if system == "Windows"
        else environment / "bin" / "python"
    )
    return RuntimePaths(root=root, environment=environment, python=python)


class RuntimeManager:
    """Inspect or mutate the managed runtime through injected boundaries."""

    def __init__(
        self,
        *,
        repo_root: Path,
        runtime_root: Path,
        bootstrap_python: str,
        system: Optional[str] = None,
        runner: Runner = subprocess.run,
        which: Which = shutil.which,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.system = system or platform.system()
        self.paths = runtime_paths(runtime_root.expanduser(), system=self.system)
        self.bootstrap_python = bootstrap_python
        self.runner = runner
        self.which = which

    @property
    def requirements(self) -> Path:
        return self.repo_root / "requirements.txt"

    def _resolved_bootstrap(self) -> Optional[str]:
        return self.which(self.bootstrap_python)

    def _run(
        self, command: Sequence[str], *, timeout: int
    ) -> Optional[subprocess.CompletedProcess]:
        try:
            return self.runner(
                list(command),
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    def _probe_version(
        self, python: str
    ) -> tuple[Optional[list[int]], Optional[str]]:
        completed = self._run((python, "-I", "-B", "-c", VERSION_PROBE), timeout=20)
        if completed is None:
            return None, "The Python process could not start."
        if completed.returncode != 0:
            return None, _command_detail(completed)
        try:
            value = json.loads(completed.stdout)
            version = [int(part) for part in value["version"]]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, "The Python version check returned an invalid response."
        if tuple(version[:2]) < MINIMUM_PYTHON:
            return version, f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required."
        return version, None

    def _probe_packages(self) -> tuple[list[str], Optional[str]]:
        requirements = self._requirements()
        known = {_normalize_distribution(name) for name in PACKAGE_IMPORTS}
        probe_distributions = [*PACKAGE_IMPORTS, *(name for name in requirements if name not in known)]
        probes = [
            f"{distribution}\x1f{PACKAGE_IMPORTS.get(distribution, '')}"
            for distribution in probe_distributions
        ]
        completed = self._run(
            (str(self.paths.python), "-I", "-B", "-c", PACKAGE_PROBE, *probes),
            timeout=30,
        )
        if completed is None:
            return list(PACKAGE_IMPORTS), "The managed Python process could not start."
        if completed.returncode != 0:
            return list(PACKAGE_IMPORTS), _command_detail(completed)
        try:
            observed = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError):
            return list(PACKAGE_IMPORTS), "The package check returned an invalid response."
        if not isinstance(observed, list):
            return list(PACKAGE_IMPORTS), "The package check returned an invalid response."
        by_distribution = {
            _normalize_distribution(str(item.get("distribution", ""))): item
            for item in observed
            if isinstance(item, dict)
        }
        missing = []
        mismatched = []
        installed = {}
        for distribution in probe_distributions:
            item = by_distribution.get(_normalize_distribution(distribution), {})
            version = item.get("installed")
            installed[distribution] = version
            expected = requirements.get(_normalize_distribution(distribution))
            if not item.get("importable") or version is None:
                missing.append(distribution)
            elif expected and version != expected:
                mismatched.append({"distribution": distribution, "required": expected, "installed": version})
        self._last_package_details = {"installed": installed, "mismatched": mismatched}
        return missing, None

    def _requirements(self) -> dict[str, str]:
        requirements: dict[str, str] = {}
        if not self.requirements.is_file():
            return requirements
        for raw_line in self.requirements.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)$", line)
            if match:
                requirements[_normalize_distribution(match.group(1))] = match.group(2)
        return requirements

    def native_install_plan(self) -> dict[str, object]:
        """Return a platform command without running or approving it."""
        if self.system == "Darwin":
            brew = self.which("brew")
            if brew:
                return {
                    "available": True,
                    "method": "Homebrew",
                    "command": [brew, "install", "poppler"],
                    "scope": "operating-system",
                    "requires_elevation": False,
                }
        if self.system == "Linux":
            package_managers = (
                ("apt-get", "poppler-utils"),
                ("dnf", "poppler-utils"),
                ("yum", "poppler-utils"),
                ("pacman", "poppler"),
            )
            for executable, package in package_managers:
                resolved = self.which(executable)
                if not resolved:
                    continue
                command = [resolved, "install"]
                if executable in {"apt-get", "dnf", "yum"}:
                    command.append("-y")
                command.append(package)
                requires_elevation = os.geteuid() != 0 if hasattr(os, "geteuid") else True
                if requires_elevation:
                    sudo = self.which("sudo")
                    if sudo:
                        command.insert(0, sudo)
                        requires_elevation = True
                return {
                    "available": True,
                    "method": executable,
                    "command": command,
                    "scope": "operating-system",
                    "requires_elevation": requires_elevation,
                }
        return {
            "available": False,
            "method": None,
            "command": None,
            "scope": "operating-system",
            "requires_elevation": False,
        }

    def doctor(self, *, operation: str = "doctor", changed: bool = False) -> dict[str, object]:
        """Inspect runtime state without writing files or installing software."""
        bootstrap = self._resolved_bootstrap()
        bootstrap_version: Optional[list[int]] = None
        bootstrap_error: Optional[str] = None
        if bootstrap is None:
            bootstrap_error = "No usable Python 3 interpreter was found."
        else:
            bootstrap_version, bootstrap_error = self._probe_version(bootstrap)

        environment_exists = self.paths.environment.is_dir()
        managed_python_exists = self.paths.python.is_file()
        managed_version: Optional[list[int]] = None
        package_error: Optional[str] = None

        if managed_python_exists:
            managed_version, managed_error = self._probe_version(str(self.paths.python))
            if managed_error:
                managed_python_exists = False
                package_error = managed_error

        self._last_package_details = {"installed": {}, "mismatched": []}
        if managed_python_exists:
            missing_packages, probe_error = self._probe_packages()
            package_error = probe_error or package_error
        else:
            missing_packages = list(PACKAGE_IMPORTS)

        native_locations = {tool: self.which(tool) for tool in NATIVE_TOOLS}
        missing_native_tools = [tool for tool, path in native_locations.items() if path is None]
        native_install = self.native_install_plan()

        mismatched_packages = self._last_package_details.get("mismatched", [])
        if (not environment_exists and bootstrap_error) or (
            environment_exists and not managed_python_exists
        ):
            status = "python-unavailable"
            message = "Handbuilt cannot find a usable Python 3 runtime."
            next_action = f"Use an available Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer interpreter with --bootstrap-python, then run the check again."
        elif missing_packages or mismatched_packages or package_error:
            status = "python-package-missing"
            if environment_exists:
                message = "Handbuilt's private bulletin runtime needs repair."
            else:
                message = "Handbuilt's private bulletin runtime has not been prepared yet."
            next_action = "The host agent should create the private runtime, then explicitly install its requirements."
        elif missing_native_tools:
            status = "native-tool-missing"
            message = "Handbuilt can build a PDF, but this computer cannot complete print verification yet."
            if native_install["available"]:
                next_action = "Ask for approval, then the host agent should run the proposed native-tool setup."
            else:
                next_action = "A supported automatic native-tool installer was not found; the host agent must provide a platform-specific setup path."
        else:
            status = "ready"
            message = "Handbuilt is ready to build and verify a bulletin."
            next_action = "Continue to bulletin setup."

        assert status in STATUSES
        return {
            "schema_version": SCHEMA_VERSION,
            "operation": operation,
            "status": status,
            "ready": status == "ready",
            "changed": changed,
            "message": message,
            "next_action": next_action,
            "runtime": {
                "root": str(self.paths.root),
                "environment": str(self.paths.environment),
                "python": str(self.paths.python),
                "environment_exists": environment_exists,
                "managed_python_exists": managed_python_exists,
            },
            "python": {
                "bootstrap": bootstrap,
                "bootstrap_version": bootstrap_version,
                "managed_version": managed_version,
                "minimum_version": ".".join(str(part) for part in MINIMUM_PYTHON),
                "error": bootstrap_error,
            },
            "python_packages": {
                "required": list(self._requirements()),
                "missing": missing_packages,
                "mismatched": mismatched_packages,
                "installed": self._last_package_details.get("installed", {}),
                "ready": not missing_packages and not mismatched_packages and package_error is None,
                "error": package_error,
            },
            "native_tools": {
                "scope": "operating-system",
                "required": list(NATIVE_TOOLS),
                "missing": missing_native_tools,
                "locations": native_locations,
                "ready": not missing_native_tools,
            },
            "native_install": native_install,
        }

    def create_environment(self) -> dict[str, object]:
        """Create or repair the venv, but never install repository packages."""
        bootstrap = self._resolved_bootstrap()
        if bootstrap is None:
            return self.doctor(operation="create")
        _, error = self._probe_version(bootstrap)
        if error:
            return self.doctor(operation="create")

        self.paths.root.mkdir(parents=True, exist_ok=True)
        completed = self._run(
            (bootstrap, "-m", "venv", str(self.paths.environment)),
            timeout=180,
        )
        if completed is None or completed.returncode != 0:
            return self._failure(
                operation="create",
                message="Handbuilt could not create its private bulletin runtime.",
                detail=_command_detail(completed),
            )
        return self.doctor(operation="create", changed=True)

    def install_requirements(self) -> dict[str, object]:
        """Install requirements into an existing managed venv only."""
        if not self.paths.python.is_file():
            return self._failure(
                operation="install",
                message="Handbuilt's private bulletin runtime does not exist yet.",
                detail="Run the create operation before the install operation.",
                changed=False,
            )
        if not self.requirements.is_file():
            return self._failure(
                operation="install",
                message="Handbuilt cannot find its runtime requirements file.",
                detail=str(self.requirements),
                changed=False,
            )

        completed = self._run(
            (
                str(self.paths.python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--upgrade",
                "--requirement",
                str(self.requirements),
            ),
            timeout=900,
        )
        if completed is None or completed.returncode != 0:
            return self._failure(
                operation="install",
                message="Handbuilt could not finish preparing its private bulletin runtime.",
                detail=_command_detail(completed),
                changed=True,
            )
        return self.doctor(operation="install", changed=True)

    def setup(self) -> dict[str, object]:
        """Prepare the private runtime, then verify the complete host setup."""
        current = self.doctor(operation="setup")
        if str(current["status"]) in {"ready", "native-tool-missing"}:
            return current
        if str(current["status"]) != "python-package-missing":
            return current

        if not self.paths.python.is_file():
            created = self.create_environment()
            if str(created["status"]) in {"python-unavailable", "install-failed"}:
                created["operation"] = "setup"
                return created

        installed = self.install_requirements()
        installed["operation"] = "setup"
        return installed

    def native_install(self) -> dict[str, object]:
        """Install Poppler through a detected platform package manager."""
        current = self.doctor(operation="native-install")
        native_tools = current.get("native_tools", {})
        if isinstance(native_tools, Mapping) and not native_tools.get("missing"):
            return current

        plan = current.get("native_install", self.native_install_plan())
        if not plan["available"] or not plan["command"]:
            current["next_action"] = "Provide a tested platform-specific native-tool installer before retrying."
            return current

        completed = self._run(plan["command"], timeout=900)
        if completed is None or completed.returncode != 0:
            result = self.doctor(operation="native-install", changed=True)
            result.update(
                {
                    "status": "install-failed",
                    "ready": False,
                    "message": "Handbuilt could not finish installing the computer-level PDF tools.",
                    "next_action": "Keep the technical detail for a maintainer and do not use an unverified manual workaround.",
                    "technical_detail": _command_detail(completed),
                }
            )
            return result
        return self.doctor(operation="native-install", changed=True)

    def _failure(
        self,
        *,
        operation: str,
        message: str,
        detail: str,
        changed: bool = True,
    ) -> dict[str, object]:
        native_locations = {tool: self.which(tool) for tool in NATIVE_TOOLS}
        missing_native_tools = [tool for tool, path in native_locations.items() if path is None]
        bootstrap = self._resolved_bootstrap()
        return {
            "schema_version": SCHEMA_VERSION,
            "operation": operation,
            "status": "install-failed",
            "ready": False,
            "changed": changed,
            "message": message,
            "next_action": "Keep the technical detail for the maintainer and do not use global package installation as a workaround.",
            "technical_detail": detail,
            "runtime": {
                "root": str(self.paths.root),
                "environment": str(self.paths.environment),
                "python": str(self.paths.python),
                "environment_exists": self.paths.environment.is_dir(),
                "managed_python_exists": self.paths.python.is_file(),
            },
            "python": {
                "bootstrap": bootstrap,
                "bootstrap_version": None,
                "managed_version": None,
                "minimum_version": ".".join(str(part) for part in MINIMUM_PYTHON),
                "error": detail,
            },
            "python_packages": {
                "required": list(self._requirements()) or list(PACKAGE_IMPORTS),
                "missing": list(PACKAGE_IMPORTS),
                "mismatched": [],
                "installed": {},
                "ready": False,
                "error": detail,
            },
            "native_tools": {
                "scope": "operating-system",
                "required": list(NATIVE_TOOLS),
                "missing": missing_native_tools,
                "locations": native_locations,
                "ready": not missing_native_tools,
            },
            "native_install": self.native_install_plan(),
        }


def _command_detail(completed: Optional[subprocess.CompletedProcess]) -> str:
    if completed is None:
        return "The process could not start."
    detail = (completed.stderr or completed.stdout or "No process output was returned.").strip()
    return detail[-800:]


def format_human(result: Mapping[str, object]) -> str:
    labels = {
        "ready": "Ready",
        "python-unavailable": "Computer setup needed",
        "python-package-missing": "Private runtime setup needed",
        "native-tool-missing": "PDF verification setup needed",
        "install-failed": "Setup did not finish",
    }
    status = str(result["status"])
    lines = [f"Status: {labels[status]}", str(result["message"]), f"Next: {result['next_action']}"]
    if status == "python-package-missing":
        packages = result.get("python_packages", {})
        if isinstance(packages, Mapping):
            missing = packages.get("missing", [])
            if missing:
                lines.append("Host detail: missing private components: " + ", ".join(str(item) for item in missing))
            mismatched = packages.get("mismatched", [])
            if mismatched:
                lines.append("Host detail: private components with unsupported versions: " + ", ".join(
                    f"{item['distribution']} {item['installed']} (need {item['required']})" for item in mismatched
                ))
    native = result.get("native_tools", {})
    if isinstance(native, Mapping) and native.get("missing"):
        lines.append("Host detail: missing computer PDF tools: " + ", ".join(str(item) for item in native["missing"]))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation, help_text in (
        ("doctor", "Check runtime readiness without changing anything."),
        ("setup", "Create and install the private runtime, then verify it."),
        ("native-install", "Install native PDF tools through a detected package manager."),
        ("create", "Create the private Python environment without installing packages."),
        ("install", "Install repository requirements into the existing private environment."),
    ):
        child = subparsers.add_parser(operation, help=help_text)
        child.add_argument("--format", choices=("human", "json"), default="human")
        child.add_argument("--runtime-root", type=Path)
        child.add_argument("--bootstrap-python", default=os.environ.get("HANDBUILT_BOOTSTRAP_PYTHON", sys.executable))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    root = args.runtime_root or default_runtime_root()
    manager = RuntimeManager(
        repo_root=repo_root,
        runtime_root=root,
        bootstrap_python=args.bootstrap_python,
    )
    if args.operation == "doctor":
        result = manager.doctor()
    elif args.operation == "setup":
        result = manager.setup()
    elif args.operation == "native-install":
        result = manager.native_install()
    elif args.operation == "create":
        result = manager.create_environment()
    else:
        result = manager.install_requirements()

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_human(result))

    if result["status"] == "install-failed":
        return 20
    if args.operation == "doctor" and result["status"] != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
