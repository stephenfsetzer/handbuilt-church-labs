#!/usr/bin/env python3
"""Prepare and inspect the private Handbuilt Church Labs runtime.

The doctor operation is read-only. Python setup mutates only the Handbuilt-owned
per-user support directory. Native-tool setup uses an explicit host operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import runtime_security
from tools.runtime_lock import RuntimeLockError, validate_runtime_lock


SCHEMA_VERSION = 1
MINIMUM_PYTHON = runtime_security.MINIMUM_PYTHON
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
NATIVE_TOOLS = ("pdftoppm", "pdfinfo", "pdffonts", "pdftotext")
ACTIVE_RUNTIME_POINTER = "active-runtime.json"
POINTER_SCHEMA_VERSION = 1
MAX_POINTER_BYTES = 4096
MAX_PIP_WHEEL_BYTES = 4 * 1024 * 1024
MAX_RUNTIME_LOCK_BYTES = 1024 * 1024
GENERATION_MARKER = ".handbuilt-runtime-generation.json"
MAX_PRUNE_GENERATIONS = 1000
MAX_PRUNE_TREE_ENTRIES = 100_000
PIP_WHEEL_TIMEOUT = 30
PIP_INSTALL_INDEX = "https://pypi.org/simple"
DOWNLOAD_SCRIPT = r'''import json,os,ssl,sys,urllib.parse,urllib.request
url,destination,limit,timeout=sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4])
allowed_host="files.pythonhosted.org"
def valid(value):
    parsed=urllib.parse.urlsplit(value)
    return (parsed.scheme=="https" and parsed.hostname==allowed_host
            and parsed.username is None and parsed.password is None
            and parsed.port in (None,443))
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,message,headers,newurl):
        if not valid(newurl):
            raise ValueError("Pip wheel redirect left the approved HTTPS host.")
        return super().redirect_request(request,fp,code,message,headers,newurl)
if not valid(url):
    raise ValueError("Pip wheel URL is not on the approved HTTPS host.")
opener=urllib.request.build_opener(
    SafeRedirect,
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)
request=urllib.request.Request(url,headers={"User-Agent":"Handbuilt-Runtime-Setup"})
with opener.open(request,timeout=timeout) as response:
    final_url=response.geturl()
    if not valid(final_url):
        raise ValueError("Pip wheel final URL left the approved HTTPS host.")
    data=response.read(limit+1)
if len(data)>limit:
    raise ValueError("Pip wheel download exceeded its size limit.")
with open(destination,"xb") as output:
    output.write(data)
print(json.dumps({"final_url":final_url,"size":len(data)}))
'''
INSTALL_PIP_SCRIPT = r'''import runpy,sys
wheel=sys.argv[1]
sys.path.insert(0,wheel)
sys.argv=["pip","--isolated","install","--no-index","--no-deps","--no-cache-dir","--disable-pip-version-check",wheel]
runpy.run_module("pip",run_name="__main__")
'''


def _normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.split("[", 1)[0]).lower()

VERSION_PROBE = (
    "import json,sys; "
    "print(json.dumps({'version': list(sys.version_info[:3]), 'releaselevel': sys.version_info.releaselevel}))"
)
PACKAGE_PROBE = (
    "import importlib.metadata,importlib.util,json,sys; "
    "versions={d.metadata.get('Name','').lower().replace('_','-'):d.version for d in importlib.metadata.distributions()}; "
    "print(json.dumps([{'distribution':(distribution:=item.split('\\x1f',1)[0]),'module':(module:=item.split('\\x1f',1)[1]),'installed':versions.get(distribution.split('[',1)[0].lower().replace('_','-')),'importable':not module or importlib.util.find_spec(module) is not None} for item in sys.argv[1:]]))"
)

Runner = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], Optional[str]]
Downloader = Callable[[str, Path, int, int], str]


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    environment: Path
    python: Path
    previous_environment: Optional[Path] = None
    pointer_error: Optional[str] = None


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
    root = root.expanduser().resolve()
    try:
        environment, previous_environment = _active_environment(root)
        pointer_error = None
    except RuntimePointerError as error:
        environment = root / ".invalid-active-runtime"
        previous_environment = None
        pointer_error = str(error)
    python = (
        environment / "Scripts" / "python.exe"
        if system == "Windows"
        else environment / "bin" / "python"
    )
    return RuntimePaths(
        root=root,
        environment=environment,
        python=python,
        previous_environment=previous_environment,
        pointer_error=pointer_error,
    )


class RuntimePointerError(ValueError):
    """The active runtime pointer is malformed or escapes its support root."""


class RuntimeSetupError(RuntimeError):
    """A staged runtime failed preparation or validation."""


def _safe_environment_relative(value: object, *, allow_none: bool = False) -> Optional[Path]:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or "\\" in value:
        raise RuntimePointerError("The active runtime pointer contains an invalid environment path.")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or ".." in relative.parts or "." in relative.parts
            or str(relative) != value):
        raise RuntimePointerError("The active runtime pointer contains an unsafe environment path.")
    if value == "python":
        return Path("python")
    if (len(relative.parts) == 3 and relative.parts[0] == "generations"
            and re.fullmatch(r"g-[0-9a-f]{32}", relative.parts[1])
            and relative.parts[2] == "python"):
        return Path(*relative.parts)
    raise RuntimePointerError("The active runtime pointer names an unrecognized environment.")


def _check_no_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise RuntimePointerError("The active runtime path contains a symbolic link.")
        except OSError as error:
            raise RuntimePointerError("The active runtime path cannot be inspected safely.") from error


def _active_environment(root: Path) -> tuple[Path, Optional[Path]]:
    pointer = root / ACTIVE_RUNTIME_POINTER
    if not pointer.exists() and not pointer.is_symlink():
        relative = Path("python")
        _check_no_symlink_components(root, relative)
        return root / relative, None
    if pointer.is_symlink():
        raise RuntimePointerError("The active runtime pointer must not be a symbolic link.")
    try:
        info = pointer.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_POINTER_BYTES:
            raise RuntimePointerError("The active runtime pointer is not a bounded regular file.")
        value = json.loads(pointer.read_bytes().decode("utf-8"))
    except RuntimePointerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimePointerError("The active runtime pointer cannot be read safely.") from error
    if not isinstance(value, dict) or value.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise RuntimePointerError("The active runtime pointer has an unsupported format.")
    relative = _safe_environment_relative(value.get("environment"))
    previous_relative = _safe_environment_relative(value.get("previous_environment"), allow_none=True)
    assert relative is not None
    _check_no_symlink_components(root, relative)
    if previous_relative is not None:
        _check_no_symlink_components(root, previous_relative)
    environment = root / relative
    previous_environment = root / previous_relative if previous_relative is not None else None
    if previous_environment == environment:
        raise RuntimePointerError("The active and previous runtime paths must differ.")
    return environment, previous_environment


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
        downloader: Optional[Downloader] = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.system = system or platform.system()
        self.paths = runtime_paths(runtime_root.expanduser(), system=self.system)
        self.bootstrap_python = bootstrap_python
        self.runner = runner
        self.which = which
        self.downloader = downloader

    @property
    def requirements(self) -> Path:
        return self.repo_root / "requirements.txt"

    @property
    def requirements_lock(self) -> Path:
        return self.repo_root / "requirements.lock"

    def _resolved_bootstrap(self) -> Optional[str]:
        return self.which(self.bootstrap_python)

    def _run(
        self, command: Sequence[str], *, timeout: int,
        env: Optional[Mapping[str, str]] = None,
    ) -> Optional[subprocess.CompletedProcess]:
        try:
            return self.runner(
                list(command),
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=dict(env) if env is not None else None,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    def _probe_version(
        self, python: str
    ) -> tuple[Optional[list[int]], Optional[str]]:
        completed = self._run((python, "-I", "-S", "-B", "-c", VERSION_PROBE), timeout=20)
        if completed is None:
            return None, "The Python process could not start."
        if completed.returncode != 0:
            return None, _command_detail(completed)
        try:
            value = json.loads(completed.stdout)
            version = [int(part) for part in value["version"]]
            releaselevel = value["releaselevel"]
            if not isinstance(releaselevel, str):
                raise ValueError("The Python release level is invalid.")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, "The Python version check returned an invalid response."
        return version, runtime_security.python_runtime_error((*version, releaselevel))

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

    def doctor(self, *, operation: str = "doctor", changed: bool = False,
               capability: str = "bulletin") -> dict[str, object]:
        """Inspect runtime state without writing files or installing software."""
        if capability not in {"workspace", "bulletin"}:
            raise ValueError(f"Unknown runtime capability: {capability}")
        bootstrap = self._resolved_bootstrap()
        bootstrap_version: Optional[list[int]] = None
        bootstrap_error: Optional[str] = None
        if self.paths.pointer_error:
            bootstrap_error = self.paths.pointer_error
        elif bootstrap is None:
            bootstrap_error = "No usable Python 3 interpreter was found."
        else:
            bootstrap_version, bootstrap_error = self._probe_version(bootstrap)

        environment_exists = self.paths.environment.is_dir()
        managed_python_exists = self.paths.python.is_file()
        managed_version: Optional[list[int]] = None
        managed_error: Optional[str] = None
        package_error: Optional[str] = None
        try:
            validate_runtime_lock(self.requirements, self.requirements_lock)
        except RuntimeLockError as error:
            package_error = str(error)
        lock_error = package_error

        if managed_python_exists:
            managed_version, managed_error = self._probe_version(str(self.paths.python))
            if managed_error:
                managed_python_exists = False
                package_error = managed_error

        self._last_package_details = {"installed": {}, "mismatched": []}
        if managed_python_exists and not lock_error:
            missing_packages, probe_error = self._probe_packages()
            package_error = probe_error or package_error
        else:
            missing_packages = list(PACKAGE_IMPORTS)

        native_locations = {tool: self.which(tool) for tool in NATIVE_TOOLS}
        missing_native_tools = [tool for tool, path in native_locations.items() if path is None]
        native_install = self.native_install_plan()

        mismatched_packages = self._last_package_details.get("mismatched", [])
        if (self.paths.pointer_error or (environment_exists and not managed_python_exists)
                or (not environment_exists and bootstrap_error)):
            status = "python-unavailable"
            message = "Handbuilt cannot use a supported, security-patched Python runtime."
            reason = managed_error if environment_exists and managed_error else bootstrap_error
            next_action = (
                f"Use Python {'.'.join(map(str, MINIMUM_PYTHON))} through "
                f"{'.'.join(map(str, max(runtime_security.SUPPORTED_RUNTIME_BRANCHES)))} "
                "at the patch levels in tools/runtime_security.py with --bootstrap-python, "
                f"then run setup. {reason or ''}"
            ).strip()
        elif missing_packages or mismatched_packages or package_error:
            status = "python-package-missing"
            if environment_exists:
                message = "Handbuilt's private bulletin runtime needs repair."
            else:
                message = "Handbuilt's private bulletin runtime has not been prepared yet."
            next_action = "The host agent should create the private runtime, then explicitly install its requirements."
            if lock_error:
                message = "Handbuilt could not verify its private tools' installation record."
                next_action = "Repair the installed plugin's requirements and locked wheel hashes before preparing its private tools."
        elif missing_native_tools and capability == "bulletin":
            status = "native-tool-missing"
            message = "Handbuilt's PDF tools need preparation before PDF import or bulletin work."
            if native_install["available"]:
                next_action = "Ask for approval, then the host agent should run the proposed native-tool setup."
            else:
                next_action = "A supported automatic native-tool installer was not found; the host agent must provide a platform-specific setup path."
        else:
            status = "ready"
            message = ("Handbuilt's Church Command Center tools are available." if capability == "workspace"
                       else "Handbuilt's bulletin dependencies are available.")
            next_action = ("Continue setting up the Church Command Center; prepare any missing PDF tools when needed."
                           if capability == "workspace" else "Run verify before PDF import or bulletin work.")

        assert status in STATUSES
        return {
            "schema_version": SCHEMA_VERSION,
            "operation": operation,
            "status": status,
            "ready": status == "ready",
            "changed": changed,
            "capability": capability,
            "host": {"system": self.system, "architecture": platform.machine()},
            "message": message,
            "next_action": next_action,
            "runtime": {
                "root": str(self.paths.root),
                "environment": str(self.paths.environment),
                "python": str(self.paths.python),
                "environment_exists": environment_exists,
                "managed_python_exists": managed_python_exists,
                "previous_environment": (
                    str(self.paths.previous_environment)
                    if self.paths.previous_environment is not None else None
                ),
                "pointer_error": self.paths.pointer_error,
            },
            "python": {
                "bootstrap": bootstrap,
                "bootstrap_version": bootstrap_version,
                "managed_version": managed_version,
                "minimum_version": ".".join(str(part) for part in MINIMUM_PYTHON),
                "error": bootstrap_error,
                "managed_error": managed_error,
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

    def verify(self) -> dict[str, object]:
        """Exercise rendering and PDF tools in a temporary directory, without installing."""
        report = self.doctor(operation="verify")
        if report["status"] != "ready":
            return report
        completed = self._run(
            (str(self.paths.python), "-I", "-B", str(self.repo_root / "tools/runtime_probe.py"),
             *(report["native_tools"]["locations"][name] for name in NATIVE_TOOLS)),
            timeout=60,
        )
        try:
            probe = json.loads(completed.stdout) if completed is not None else {}
        except (ValueError, TypeError):
            probe = {}
        expected = {"render", "pdfinfo", "pdffonts", "pdftoppm", "pdftotext"}
        if (completed is None or completed.returncode != 0 or not isinstance(probe, dict)
                or probe.get("checks") != sorted(expected) or probe.get("ok") is not True):
            report.update({
                "status": "install-failed", "ready": False,
                "message": "Handbuilt's bulletin tools did not pass their working check.",
                "next_action": "Use the check detail to repair the failing PDF component, then run verify again. Church Command Center and sermon work can continue if their check is ready.",
                "technical_detail": (str(probe.get("error"))[:800] if isinstance(probe, dict) and probe.get("error")
                                     else _command_detail(completed)),
                "verification": {"ok": False},
            })
        else:
            report.update({
                "message": "Handbuilt built and checked a sample PDF successfully.",
                "next_action": "Continue to PDF import or bulletin work.",
                "verification": probe,
            })
        return report

    def _runtime_lock(self):
        from tools.workflow_updates import file_lock

        return file_lock(self.paths.root / "runtime.lock")

    def _read_pointer_bytes(self) -> Optional[bytes]:
        pointer = self.paths.root / ACTIVE_RUNTIME_POINTER
        if not pointer.exists() and not pointer.is_symlink():
            return None
        if pointer.is_symlink():
            raise RuntimePointerError("The active runtime pointer must not be a symbolic link.")
        info = pointer.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_POINTER_BYTES:
            raise RuntimePointerError("The active runtime pointer is not a bounded regular file.")
        return pointer.read_bytes()

    def _write_pointer_bytes(self, data: Optional[bytes]) -> None:
        root = self.paths.root
        root.mkdir(parents=True, exist_ok=True)
        pointer = root / ACTIVE_RUNTIME_POINTER
        if pointer.is_symlink():
            raise RuntimePointerError("The active runtime pointer must not be a symbolic link.")
        if data is None:
            pointer.unlink(missing_ok=True)
            return
        if len(data) > MAX_POINTER_BYTES:
            raise RuntimePointerError("The active runtime pointer exceeds its size limit.")
        if pointer.exists():
            info = pointer.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise RuntimePointerError("The active runtime pointer must be a regular file.")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".active-runtime-", dir=root)
        try:
            # mkstemp creates a private file, including on older Windows Python
            # releases that do not provide os.fchmod.
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, pointer)
            try:
                directory = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError:
                pass
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def _pointer_value(self, current: Optional[Path], previous: Optional[Path]) -> bytes:
        def relative(path: Optional[Path]) -> Optional[str]:
            if path is None:
                return None
            try:
                value = path.resolve(strict=True).relative_to(self.paths.root.resolve()).as_posix()
            except (OSError, ValueError) as error:
                raise RuntimePointerError("A runtime generation is outside its support directory.") from error
            _safe_environment_relative(value)
            _check_no_symlink_components(self.paths.root, Path(value))
            return value

        payload = {
            "schema_version": POINTER_SCHEMA_VERSION,
            "environment": relative(current),
            "previous_environment": relative(previous),
        }
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def _download_pip_wheel(self, bootstrap: str, destination: Path) -> str:
        if self.downloader is not None:
            final_url = self.downloader(
                runtime_security.PIP_WHEEL_URL,
                destination,
                MAX_PIP_WHEEL_BYTES,
                PIP_WHEEL_TIMEOUT,
            )
        else:
            completed = self._run(
                (
                    bootstrap, "-I", "-S", "-c", DOWNLOAD_SCRIPT,
                    runtime_security.PIP_WHEEL_URL, str(destination),
                    str(MAX_PIP_WHEEL_BYTES), str(PIP_WHEEL_TIMEOUT),
                ),
                timeout=PIP_WHEEL_TIMEOUT + 5,
            )
            if completed is None or completed.returncode != 0:
                raise RuntimeSetupError(_command_detail(completed))
            try:
                final_url = json.loads(completed.stdout)["final_url"]
            except (TypeError, KeyError, json.JSONDecodeError) as error:
                raise RuntimeSetupError("The pip wheel downloader returned an invalid response.") from error

        from urllib.parse import urlsplit

        try:
            source = urlsplit(runtime_security.PIP_WHEEL_URL)
            final = urlsplit(final_url) if isinstance(final_url, str) else None
        except ValueError as error:
            raise RuntimeSetupError("The pip wheel download returned an invalid URL.") from error
        if (source.scheme != "https" or source.hostname != "files.pythonhosted.org"
                or source.username is not None or source.password is not None
                or final is None or final.scheme != "https"
                or final.hostname != "files.pythonhosted.org" or final.username is not None
                or final.password is not None or final.port not in (None, 443)):
            raise RuntimeSetupError("The pip wheel download did not stay on the approved HTTPS host.")
        if not destination.is_file() or destination.is_symlink():
            raise RuntimeSetupError("The pip wheel downloader did not create a regular file.")
        if destination.stat().st_size <= 0 or destination.stat().st_size > MAX_PIP_WHEEL_BYTES:
            raise RuntimeSetupError("The pip wheel download has an invalid size.")
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != runtime_security.PIP_WHEEL_SHA256:
            raise RuntimeSetupError("The pip wheel failed its SHA-256 check.")
        return final_url

    def _candidate_install(self, generation_root: Path, bootstrap: str) -> dict[str, object]:
        try:
            locked_requirements = validate_runtime_lock(self.requirements, self.requirements_lock)
        except RuntimeLockError as error:
            raise RuntimeSetupError(str(error)) from error
        environment = generation_root / "python"
        completed = self._run(
            (bootstrap, "-I", "-S", "-m", "venv", "--without-pip", str(environment)),
            timeout=180,
        )
        if completed is None or completed.returncode != 0:
            raise RuntimeSetupError(_command_detail(completed))
        candidate_paths = runtime_paths(generation_root, system=self.system)
        candidate_manager = RuntimeManager(
            repo_root=self.repo_root,
            runtime_root=generation_root,
            bootstrap_python=bootstrap,
            system=self.system,
            runner=self.runner,
            which=self.which,
            downloader=self.downloader,
        )
        _, candidate_error = candidate_manager._probe_version(str(candidate_paths.python))
        if candidate_error:
            raise RuntimeSetupError(candidate_error)

        wheel = generation_root / ".bootstrap" / "pip-26.2.2-py3-none-any.whl"
        wheel.parent.mkdir()
        candidate_lock = wheel.parent / "requirements.lock"
        with locked_requirements.open("rb") as locked_file:
            locked_bytes = locked_file.read(MAX_RUNTIME_LOCK_BYTES + 1)
        if len(locked_bytes) > MAX_RUNTIME_LOCK_BYTES:
            raise RuntimeSetupError("The runtime wheel lock exceeds its size limit.")
        candidate_lock.write_bytes(locked_bytes)
        try:
            validate_runtime_lock(self.requirements, candidate_lock)
        except RuntimeLockError as error:
            raise RuntimeSetupError(str(error)) from error
        self._download_pip_wheel(bootstrap, wheel)
        clean_env = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith("PIP_")
        }
        clean_env["PIP_CONFIG_FILE"] = os.devnull
        completed = self._run(
            (
                str(candidate_paths.python), "-I", "-c", INSTALL_PIP_SCRIPT,
                str(wheel),
            ),
            timeout=180,
            env=clean_env,
        )
        if completed is None or completed.returncode != 0:
            raise RuntimeSetupError(_command_detail(completed))

        completed = self._run(
            (
                str(candidate_paths.python), "-I", "-m", "pip", "--isolated",
                "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir",
                "--require-hashes", "--only-binary=:all:",
                "--index-url", PIP_INSTALL_INDEX, "--upgrade",
                "--requirement", str(candidate_lock),
            ),
            timeout=900,
            env=clean_env,
        )
        if completed is None or completed.returncode != 0:
            raise RuntimeSetupError(_command_detail(completed))
        wheel.unlink(missing_ok=True)
        candidate_lock.unlink(missing_ok=True)
        wheel.parent.rmdir()

        report = candidate_manager.doctor(capability="workspace")
        if report["status"] != "ready":
            raise RuntimeSetupError(str(report.get("next_action", "The candidate runtime failed its package check.")))
        missing_native = report.get("native_tools", {}).get("missing", [])
        if not missing_native:
            report = candidate_manager.verify()
            if report["status"] != "ready":
                raise RuntimeSetupError(str(report.get("technical_detail", report.get("next_action"))))
        else:
            report = candidate_manager.doctor(capability="workspace")
        marker = generation_root / GENERATION_MARKER
        with marker.open("x", encoding="utf-8") as output:
            json.dump({"schema_version": 1, "owner": "handbuilt-church-labs",
                       "environment": "python", "wheel_lock_sha256": hashlib.sha256(locked_bytes).hexdigest()}, output)
        report["installation_policy"] = {"binary_only": True, "require_hashes": True,
                                         "wheel_lock_sha256": hashlib.sha256(locked_bytes).hexdigest()}
        return report

    def _stage_and_activate(self, *, operation: str) -> dict[str, object]:
        if self.paths.pointer_error:
            return self._failure(
                operation=operation,
                message="Handbuilt could not safely read the active runtime selection.",
                detail=self.paths.pointer_error,
                changed=False,
            )
        bootstrap = self._resolved_bootstrap()
        if bootstrap is None:
            return self._failure(operation=operation, message="Handbuilt needs a patched Python to prepare a replacement runtime.",
                                 detail="Use --bootstrap-python with an inspected, supported interpreter.", changed=False)
        bootstrap_version, bootstrap_error = self._probe_version(bootstrap)
        if bootstrap_error:
            return self._failure(operation=operation, message="Handbuilt cannot use this Python to prepare a replacement runtime.",
                                 detail=bootstrap_error, changed=False)
        if not self.requirements.is_file():
            return self._failure(
                operation=operation,
                message="Handbuilt cannot find its runtime requirements file.",
                detail=str(self.requirements),
                changed=False,
            )
        try:
            validate_runtime_lock(self.requirements, self.requirements_lock)
        except RuntimeLockError as error:
            return self._failure(operation=operation,
                                 message="Handbuilt cannot verify its locked runtime requirements.",
                                 detail=str(error), changed=False)

        root = self.paths.root
        root.mkdir(parents=True, exist_ok=True)
        generations = root / "generations"
        if generations.is_symlink():
            return self._failure(
                operation=operation,
                message="Handbuilt cannot safely create a runtime generation.",
                detail="The generations directory must not be a symbolic link.",
                changed=False,
            )
        generations.mkdir(exist_ok=True)
        generation_root = generations / f"g-{uuid.uuid4().hex}"
        old_pointer: Optional[bytes] = None
        previous = None
        activation_attempted = False
        if not generation_root.parent.resolve().is_relative_to(root.resolve()):
            return self._failure(
                operation=operation,
                message="Handbuilt could not safely create a runtime generation.",
                detail="The generations directory is outside the runtime support directory.",
                changed=False,
            )
        try:
            old_pointer = self._read_pointer_bytes()
            self.paths = runtime_paths(root, system=self.system)
            if self.paths.pointer_error:
                raise RuntimePointerError(self.paths.pointer_error)
            if self.paths.environment.exists():
                previous = self.paths.environment
            generation_root.mkdir()
            prepared = self._candidate_install(generation_root, bootstrap)
            new_pointer = self._pointer_value(generation_root / "python", previous)
            activation_attempted = True
            self._write_pointer_bytes(new_pointer)
            self.paths = runtime_paths(root, system=self.system)
            selected = self.doctor(operation=operation)
            if selected["status"] not in {"ready", "native-tool-missing"}:
                self._write_pointer_bytes(old_pointer)
                self.paths = runtime_paths(root, system=self.system)
                raise RuntimeSetupError(str(selected.get("next_action", "The selected runtime did not pass verification.")))
            receipt = {
                "previous_environment": str(previous) if previous is not None else None,
                "current_environment": str(self.paths.environment),
                "changed": True,
                "verified": True,
                "retained_previous": str(previous) if previous is not None and previous.exists() else None,
            }
            selected["migration"] = receipt
            selected["installation_policy"] = prepared["installation_policy"]
            selected["changed"] = True
            return selected
        except (OSError, RuntimePointerError, RuntimeSetupError) as error:
            recovery_required = False
            try:
                current, _ = _active_environment(root)
                if activation_attempted and current == generation_root / "python":
                    try:
                        self._write_pointer_bytes(old_pointer)
                        if self._read_pointer_bytes() != old_pointer:
                            recovery_required = True
                    except (OSError, RuntimePointerError):
                        recovery_required = True
                if activation_attempted:
                    current_after_restore, _ = _active_environment(root)
                    if (current_after_restore == generation_root / "python"
                            or self._read_pointer_bytes() != old_pointer):
                        recovery_required = True
            except (OSError, RuntimePointerError):
                recovery_required = activation_attempted
            self.paths = runtime_paths(root, system=self.system)
            if (not recovery_required and generation_root.exists()
                    and not generation_root.is_symlink()):
                shutil.rmtree(generation_root, ignore_errors=True)
            detail = str(error)[-800:]
            if recovery_required:
                detail = (detail + " Prior runtime restoration could not be verified. ")[-800:]
            result = self._failure(
                operation=operation,
                message=("Handbuilt could not restore the prior runtime selection; the candidate was retained for recovery."
                         if recovery_required else
                         "Handbuilt could not prepare and verify a replacement private runtime."),
                detail=detail,
                changed=recovery_required,
            )
            result["migration"] = {
                "previous_environment": str(previous) if previous is not None else None,
                "current_environment": str(self.paths.environment),
                "changed": recovery_required,
                "verified": False,
                "retained_previous": str(previous) if previous is not None and previous.exists() else None,
                "recovery_required": recovery_required,
            }
            return result

    def create_environment(self) -> dict[str, object]:
        """Create an empty legacy venv only when its path is absent."""
        self.paths.root.mkdir(parents=True, exist_ok=True)
        with self._runtime_lock() as acquired:
            if not acquired:
                return self._failure(operation="create", message="Runtime setup is already in progress.",
                                     detail="Retry after the active runtime operation finishes.", changed=False)
            self.paths = runtime_paths(self.paths.root, system=self.system)
            if self.paths.pointer_error:
                return self._failure(operation="create", message="The active runtime selection is invalid.",
                                     detail=self.paths.pointer_error, changed=False)
            if self.paths.environment.exists() or self.paths.python.exists():
                return self._failure(operation="create", message="An existing private runtime was preserved.",
                                     detail="Create does not overwrite an existing runtime. Use setup to prepare a replacement.",
                                     changed=False)
            bootstrap = self._resolved_bootstrap()
            if bootstrap is None or self._probe_version(bootstrap)[1]:
                return self.doctor(operation="create")
            completed = self._run(
                (bootstrap, "-I", "-S", "-m", "venv", "--without-pip", str(self.paths.environment)),
                timeout=180,
            )
            if completed is None or completed.returncode != 0:
                return self._failure(operation="create", message="Handbuilt could not create its private runtime.",
                                     detail=_command_detail(completed), changed=False)
            return self.doctor(operation="create", changed=True)

    def install_requirements(self) -> dict[str, object]:
        """Safely stage and activate requirements for an existing environment."""
        self.paths = runtime_paths(self.paths.root, system=self.system)
        if self.paths.pointer_error:
            return self._failure(operation="install", message="The active runtime selection is invalid.",
                                 detail=self.paths.pointer_error, changed=False)
        if not self.paths.python.is_file():
            return self._failure(
                operation="install",
                message="Handbuilt's private bulletin runtime does not exist yet.",
                detail="Run the create operation before the install operation.",
                changed=False,
            )
        self.paths.root.mkdir(parents=True, exist_ok=True)
        with self._runtime_lock() as acquired:
            if not acquired:
                return self._failure(operation="install", message="Runtime setup is already in progress.",
                                     detail="Retry after the active runtime operation finishes.", changed=False)
            self.paths = runtime_paths(self.paths.root, system=self.system)
            if self.paths.pointer_error:
                return self._failure(operation="install", message="The active runtime selection is invalid.",
                                     detail=self.paths.pointer_error, changed=False)
            if not self.paths.python.is_file():
                return self._failure(operation="install", message="Handbuilt's private runtime is missing.",
                                     detail="Run setup to create a replacement runtime.", changed=False)
            return self._stage_and_activate(operation="install")

    def setup(self) -> dict[str, object]:
        """Stage, verify, and select a patched runtime without replacing the old one."""
        current = self.doctor(operation="setup")
        if current["status"] in {"ready", "native-tool-missing"}:
            return current
        if current.get("runtime", {}).get("pointer_error"):
            return current
        if current["status"] == "python-unavailable" and current.get("python", {}).get("error"):
            bootstrap = self._resolved_bootstrap()
            if bootstrap is None or self._probe_version(bootstrap)[1]:
                return current
        self.paths.root.mkdir(parents=True, exist_ok=True)
        with self._runtime_lock() as acquired:
            if not acquired:
                return self._failure(operation="setup", message="Runtime setup is already in progress.",
                                     detail="Retry after the active runtime operation finishes.", changed=False)
            self.paths = runtime_paths(self.paths.root, system=self.system)
            current = self.doctor(operation="setup")
            if current["status"] in {"ready", "native-tool-missing"}:
                return current
            return self._stage_and_activate(operation="setup")

    def rollback(self) -> dict[str, object]:
        """Select the retained previous generation only if it meets current policy."""
        self.paths.root.mkdir(parents=True, exist_ok=True)
        with self._runtime_lock() as acquired:
            if not acquired:
                return self._failure(operation="rollback", message="Runtime setup is already in progress.",
                                     detail="Retry after the active runtime operation finishes.", changed=False)
            self.paths = runtime_paths(self.paths.root, system=self.system)
            if self.paths.pointer_error:
                return self._failure(operation="rollback", message="The active runtime selection is invalid.",
                                     detail=self.paths.pointer_error, changed=False)
            previous = self.paths.previous_environment
            if previous is None or not previous.is_dir():
                return self._failure(operation="rollback", message="No retained runtime is available for rollback.",
                                     detail="The previous runtime directory is missing.", changed=False)
            previous_manager = RuntimeManager(
                repo_root=self.repo_root,
                runtime_root=previous.parent,
                bootstrap_python=self.bootstrap_python,
                system=self.system,
                runner=self.runner,
                which=self.which,
                downloader=self.downloader,
            )
            previous_manager.paths = RuntimePaths(
                root=self.paths.root,
                environment=previous,
                python=(previous / "Scripts" / "python.exe" if self.system == "Windows"
                        else previous / "bin" / "python"),
            )
            previous_report = previous_manager.doctor(capability="workspace")
            if previous_report["status"] == "ready" and not previous_report["native_tools"]["missing"]:
                previous_report = previous_manager.verify()
            if previous_report["status"] != "ready":
                return self._failure(
                    operation="rollback",
                    message="The retained runtime does not meet the current security policy.",
                    detail=str(previous_report.get("next_action", previous_report.get("python", {}).get("managed_error"))),
                    changed=False,
                )
            old_pointer = self._read_pointer_bytes()
            current = self.paths.environment
            try:
                self._write_pointer_bytes(self._pointer_value(previous, current))
                self.paths = runtime_paths(self.paths.root, system=self.system)
                selected = self.doctor(operation="rollback")
                if selected["status"] not in {"ready", "native-tool-missing"}:
                    raise RuntimeSetupError(str(selected.get("next_action", "Rollback verification failed.")))
                selected["changed"] = True
                selected["migration"] = {
                    "previous_environment": str(current),
                    "current_environment": str(previous),
                    "changed": True,
                    "verified": True,
                    "retained_previous": str(current),
                }
                return selected
            except (OSError, RuntimePointerError, RuntimeSetupError) as error:
                recovery_required = False
                try:
                    self._write_pointer_bytes(old_pointer)
                    recovery_required = self._read_pointer_bytes() != old_pointer
                except (OSError, RuntimePointerError):
                    recovery_required = True
                self.paths = runtime_paths(self.paths.root, system=self.system)
                result = self._failure(
                    operation="rollback",
                    message=("Handbuilt could not restore the prior selection after a failed rollback; both runtimes were retained."
                             if recovery_required else "Handbuilt could not verify the rollback."),
                    detail=str(error)[-800:], changed=recovery_required,
                )
                result["migration"] = {
                    "previous_environment": str(current),
                    "current_environment": str(self.paths.environment),
                    "changed": recovery_required, "verified": False,
                    "retained_previous": str(current), "recovery_required": recovery_required,
                }
                return result

    def _prune_tree_safe(self, target: Path) -> bool:
        """Refuse mounted trees, junctions, and oversized directory walks."""
        root_device = self.paths.root.stat().st_dev
        mounts: set[Path] = set()
        if sys.platform.startswith("linux"):
            try:
                with open("/proc/self/mountinfo", "rb") as source:
                    mount_data = source.read(1024 * 1024 + 1)
                if len(mount_data) > 1024 * 1024:
                    return False
                for line in mount_data.splitlines():
                    fields = line.split()
                    if len(fields) < 6:
                        return False
                    name = re.sub(rb"\\([0-7]{3})", lambda match: bytes([int(match[1], 8)]), fields[4])
                    mounts.add(Path(os.fsdecode(name)))
            except (OSError, ValueError):
                return False
        pending = [target]
        inspected = 0
        while pending:
            path = pending.pop()
            inspected += 1
            if inspected > MAX_PRUNE_TREE_ENTRIES:
                return False
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                continue
            if (info.st_dev != root_device or path in mounts or os.path.ismount(path)
                    or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                return False
            if stat.S_ISDIR(info.st_mode):
                with os.scandir(path) as entries:
                    for entry in entries:
                        if inspected + len(pending) >= MAX_PRUNE_TREE_ENTRIES:
                            return False
                        pending.append(Path(entry.path))
        return True

    def _prune_candidate_error(self, target: Path, environment: Path, *, legacy: bool) -> Optional[str]:
        if target.is_symlink() or environment.is_symlink() or not environment.is_dir():
            return "not_an_owned_environment"
        config = environment / "pyvenv.cfg"
        if config.is_symlink() or not config.is_file():
            return "unrecognized_environment"
        if not legacy:
            marker = target / GENERATION_MARKER
            try:
                info = marker.lstat()
                if marker.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 2048:
                    return "unrecognized_generation"
                with marker.open("rb") as source:
                    data = source.read(2049)
                if len(data) > 2048:
                    return "unrecognized_generation"
                payload = json.loads(data)
                if (not isinstance(payload, dict) or payload.get("schema_version") != 1
                        or payload.get("owner") != "handbuilt-church-labs"
                        or payload.get("environment") != "python"
                        or re.fullmatch(r"[0-9a-f]{64}", str(payload.get("wheel_lock_sha256", ""))) is None):
                    return "unrecognized_generation"
            except (OSError, ValueError):
                return "unrecognized_generation"
        if not self._prune_tree_safe(target):
            return "mounted_or_uninspectable_tree"
        return None

    def _prune_candidates(self) -> tuple[list[Path], list[dict[str, str]]]:
        """Recognize obsolete owned environments without following links."""
        root = self.paths.root
        protected = {self.paths.environment, self.paths.previous_environment}
        candidates: list[Path] = []
        skipped: list[dict[str, str]] = []

        def inspect(target: Path, environment: Path, *, legacy: bool = False) -> None:
            if environment in protected:
                return
            reason = self._prune_candidate_error(target, environment, legacy=legacy)
            if reason is not None:
                skipped.append({"path": str(target), "reason": reason})
            else:
                candidates.append(target)

        legacy = root / "python"
        if legacy.exists() or legacy.is_symlink():
            inspect(legacy, legacy, legacy=True)
        generations = root / "generations"
        if generations.is_symlink():
            raise RuntimePointerError("The generations directory must not be a symbolic link.")
        if generations.exists():
            if not generations.is_dir():
                raise RuntimePointerError("The generations path must be a directory.")
            for count, target in enumerate(generations.iterdir(), start=1):
                if count > MAX_PRUNE_GENERATIONS:
                    raise RuntimePointerError("Too many runtime directories to inspect in one cleanup.")
                if re.fullmatch(r"g-[0-9a-f]{32}", target.name) is None:
                    skipped.append({"path": str(target), "reason": "unrecognized_directory"})
                    continue
                inspect(target, target / "python")
        return sorted(candidates), skipped

    def prune(self, *, apply: bool = False, workflows_stopped: bool = False) -> dict[str, object]:
        """Preview obsolete runtimes; remove only after explicit host quiescence."""
        root = self.paths.root
        if apply and not workflows_stopped:
            return self._failure(operation="prune", changed=False,
                                 message="Pause all Handbuilt workflows before removing old private tools.",
                                 detail="Prune requires --apply and --workflows-stopped. Setup never removes older runtimes automatically.")
        if not root.exists():
            report = self.doctor(operation="prune", capability="workspace")
            report["prune"] = {"applied": False, "candidates": [], "removed": [], "skipped": []}
            return report
        if not root.is_dir():
            return self._failure(operation="prune", changed=False,
                                 message="Handbuilt cannot safely inspect its runtime folder.",
                                 detail="The runtime root is not a directory.")
        with self._runtime_lock() as acquired:
            if not acquired:
                return self._failure(operation="prune", changed=False,
                                     message="Another private-tool operation is in progress.",
                                     detail="Retry cleanup after the active operation finishes.")
            self.paths = runtime_paths(root, system=self.system)
            if self.paths.pointer_error:
                return self._failure(operation="prune", changed=False,
                                     message="Repair the runtime selection before cleanup.",
                                     detail=self.paths.pointer_error)
            try:
                pointer_before = self._read_pointer_bytes()
                candidates, skipped = self._prune_candidates()
            except (OSError, RuntimePointerError) as error:
                return self._failure(operation="prune", changed=False,
                                     message="Handbuilt could not safely inspect old private tools.", detail=str(error))
            report = self.doctor(operation="prune", capability="workspace")
            if apply and report["status"] == "ready" and not report["native_tools"]["missing"]:
                report = self.verify()
                report["operation"] = "prune"
            removed: list[str] = []
            errors: list[dict[str, str]] = []
            partial_removal_possible = False
            if apply:
                if report["status"] != "ready":
                    report.update({"message": "Repair and verify the selected private tools before cleanup.",
                                   "next_action": "Run setup and verify before retrying runtime prune."})
                    report["prune"] = {"applied": False, "candidates": [str(path) for path in candidates],
                                       "removed": [], "skipped": skipped}
                    return report
                for target in candidates:
                    try:
                        if self._read_pointer_bytes() != pointer_before:
                            raise RuntimePointerError("The runtime selection changed during cleanup.")
                        # Reinspect ownership and confinement immediately before removal.
                        legacy = target == root / "python"
                        environment = target if legacy else target / "python"
                        if (environment in {self.paths.environment, self.paths.previous_environment}
                                or self._prune_candidate_error(target, environment, legacy=legacy) is not None):
                            raise RuntimePointerError("The cleanup candidate changed during inspection.")
                        try:
                            shutil.rmtree(target)
                        except OSError:
                            partial_removal_possible = True
                            raise
                        removed.append(str(target))
                    except (OSError, RuntimePointerError) as error:
                        errors.append({"path": str(target), "error": str(error)[-800:]})
                        break
            report["changed"] = bool(removed)
            report["prune"] = {"applied": apply, "candidates": [str(path) for path in candidates],
                               "removed": removed, "skipped": skipped, "errors": errors,
                               "partial_removal_possible": partial_removal_possible,
                               "retained": [str(path) for path in (self.paths.environment, self.paths.previous_environment)
                                            if path is not None]}
            report["message"] = ("Old private-tool cleanup did not complete." if errors else
                                 "Old private tools were removed; the selected and rollback runtimes were kept." if apply else
                                 "This is a cleanup preview. No private tools were removed.")
            report["next_action"] = ("Inspect the cleanup errors before retrying." if errors else
                                     "Keep the cleanup receipt." if apply else
                                     "Pause all Handbuilt workflows, then use prune --apply --workflows-stopped to remove the listed candidates.")
            if errors:
                report.update({"status": "install-failed", "ready": False})
            return report

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
        ("verify", "Render and inspect a temporary sample PDF without installing anything."),
        ("setup", "Create and install the private runtime, then verify it."),
        ("native-install", "Install native PDF tools through a detected package manager."),
        ("create", "Create the private Python environment without installing packages."),
        ("install", "Install repository requirements into the existing private environment."),
        ("rollback", "Restore the retained runtime after validating it against current security policy."),
        ("prune", "Preview obsolete runtimes; removal requires paused workflows and explicit flags."),
    ):
        child = subparsers.add_parser(operation, help=help_text)
        child.add_argument("--format", choices=("human", "json"), default="human")
        child.add_argument("--runtime-root", type=Path)
        child.add_argument("--bootstrap-python", default=os.environ.get("HANDBUILT_BOOTSTRAP_PYTHON", sys.executable))
        if operation == "doctor":
            child.add_argument("--capability", choices=("workspace", "bulletin"), default="bulletin")
        if operation == "prune":
            child.add_argument("--apply", action="store_true")
            child.add_argument("--workflows-stopped", action="store_true")
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
        result = manager.doctor(capability=args.capability)
    elif args.operation == "verify":
        result = manager.verify()
    elif args.operation == "setup":
        result = manager.setup()
    elif args.operation == "native-install":
        result = manager.native_install()
    elif args.operation == "create":
        result = manager.create_environment()
    elif args.operation == "rollback":
        result = manager.rollback()
    elif args.operation == "prune":
        result = manager.prune(apply=args.apply, workflows_stopped=args.workflows_stopped)
    else:
        result = manager.install_requirements()

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_human(result))

    if result["status"] == "install-failed":
        return 20
    if args.operation in {"doctor", "verify", "setup", "install", "rollback", "prune"} and result["status"] not in (
            {"ready", "native-tool-missing"} if args.operation in {"setup", "install", "rollback"}
            else {"ready"}):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
