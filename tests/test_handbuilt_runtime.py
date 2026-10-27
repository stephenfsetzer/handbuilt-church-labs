from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import handbuilt_runtime as runtime


WHEEL_BYTES = b"synthetic verified pip wheel bytes"
REQUIREMENTS = """weasyprint==70.0
pypdf==6.21.2
Pillow==13.0.0
PyYAML==6.0.3
qrcode[pil]==8.2
pip==26.2.2
certifi==2026.10.19
brotli==1.2.1
"""


class FakeRunner:
    def __init__(self, requirements: Path, *, missing_modules=(), fail_stage=None):
        self.requirements = requirements
        self.commands = []
        self.missing_modules = set(missing_modules)
        self.fail_stage = fail_stage
        self.versions = {}
        self.package_versions = {}
        self.package_probe_counts = {}
        self.runtime_probe_counts = {}
        self.installed = set()

    def _requirements(self):
        values = {}
        for line in self.requirements.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name, version = line.split("==", 1)
                values[name.split("[", 1)[0].lower().replace("_", "-")] = version
        return values

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append((command, kwargs))
        if command[1:6] == ["-I", "-S", "-m", "venv", "--without-pip"]:
            environment = Path(command[-1])
            python = environment / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"synthetic interpreter")
            self.package_versions[str(python)] = {}
            return subprocess.CompletedProcess(command, 0, "", "")
        if runtime.VERSION_PROBE in command:
            executable = command[0]
            version = self.versions.get(str(Path(executable).resolve()), (3, 14, 10, "final"))
            result = {"version": list(version[:3]), "releaselevel": version[3]}
            return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
        if runtime.DOWNLOAD_SCRIPT in command:
            return subprocess.CompletedProcess(command, 99, "", "Unexpected live downloader invocation")
        if runtime.INSTALL_PIP_SCRIPT in command:
            if self.fail_stage == "pip-bootstrap":
                return subprocess.CompletedProcess(command, 1, "", "synthetic pip bootstrap failure")
            self.installed.add(command[0])
            return subprocess.CompletedProcess(command, 0, "", "")
        if len(command) > 5 and command[1:5] == ["-I", "-m", "pip", "--isolated"]:
            if self.fail_stage == "requirements-install":
                return subprocess.CompletedProcess(command, 1, "", "synthetic requirements failure")
            self.package_versions[command[0]] = self._requirements()
            self.installed.add(command[0])
            return subprocess.CompletedProcess(command, 0, "", "")
        if runtime.PACKAGE_PROBE in command:
            executable = command[0]
            self.package_probe_counts[executable] = self.package_probe_counts.get(executable, 0) + 1
            if (self.fail_stage == "selected-package-probe"
                    and executable in self.installed
                    and self.package_probe_counts[executable] >= 3):
                return subprocess.CompletedProcess(command, 1, "", "synthetic selected check failure")
            distributions = []
            start = command.index(runtime.PACKAGE_PROBE) + 1
            expected = self._requirements()
            current = self.package_versions.get(executable, expected)
            for probe in command[start:]:
                distribution, module = probe.split("\x1f", 1)
                normalized = distribution.split("[", 1)[0].lower().replace("_", "-")
                missing = module in self.missing_modules
                distributions.append({
                    "distribution": distribution,
                    "module": module,
                    "installed": current.get(normalized),
                    "importable": not missing,
                })
            return subprocess.CompletedProcess(command, 0, json.dumps(distributions), "")
        if any(str(value).endswith("/runtime_probe.py") for value in command):
            executable = command[0]
            self.runtime_probe_counts[executable] = self.runtime_probe_counts.get(executable, 0) + 1
            if self.fail_stage == "runtime-probe":
                return subprocess.CompletedProcess(
                    command, 1, json.dumps({"ok": False, "error": "synthetic PDF check failure"}), ""
                )
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "ok": True,
                "checks": ["pdffonts", "pdfinfo", "pdftoppm", "pdftotext", "render"],
            }), "")
        if command[1:] == ["install", "poppler"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Unexpected command: {command}")


class RuntimeManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.requirements = self.repo / "requirements.txt"
        self.requirements.write_text(REQUIREMENTS, encoding="utf-8")
        self.support = self.base / "user-support" / "runtime"
        self.bootstrap = "/synthetic/python3"

    def which(self, missing=()):
        missing = set(missing)

        def resolve(name):
            if name in missing:
                return None
            if name == self.bootstrap:
                return self.bootstrap
            return f"/synthetic/bin/{name}"

        return resolve

    def downloader(self, data=WHEEL_BYTES, final_url=None):
        calls = []

        def download(url, destination, max_bytes, timeout):
            calls.append((url, destination, max_bytes, timeout))
            destination.write_bytes(data)
            return final_url or url

        return download, calls

    def manager(self, runner, *, missing_tools=(), downloader=None):
        return runtime.RuntimeManager(
            repo_root=self.repo,
            runtime_root=self.support,
            bootstrap_python=self.bootstrap,
            system="Darwin",
            runner=runner,
            which=self.which(missing_tools),
            downloader=downloader,
        )

    def make_legacy_runtime(self, *, version=(3, 14, 10, "final"), packages=None):
        python = self.support / "python" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"keep this legacy interpreter")
        return python

    def test_doctor_is_read_only_when_runtime_is_absent(self):
        runner = FakeRunner(self.requirements)
        manager = self.manager(runner)
        result = manager.doctor()
        self.assertEqual(result["status"], "python-package-missing")
        self.assertFalse(self.support.exists())
        self.assertFalse(any("venv" in command or "pip" in command for command, _ in runner.commands))

    def test_doctor_reports_ready_with_managed_packages_and_native_tools(self):
        self.make_legacy_runtime()
        result = self.manager(FakeRunner(self.requirements)).doctor()
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["ready"])
        self.assertEqual(result["python_packages"]["missing"], [])
        self.assertEqual(result["native_tools"]["scope"], "operating-system")
        self.assertEqual(result["native_tools"]["required"], list(runtime.NATIVE_TOOLS))

    def test_doctor_reports_unavailable_bootstrap_python_when_no_runtime_exists(self):
        result = self.manager(
            FakeRunner(self.requirements), missing_tools=(self.bootstrap,)
        ).doctor()
        self.assertEqual(result["status"], "python-unavailable")
        self.assertFalse(result["ready"])

    def test_ready_managed_runtime_does_not_require_bootstrap_python(self):
        self.make_legacy_runtime()
        result = self.manager(
            FakeRunner(self.requirements), missing_tools=(self.bootstrap,)
        ).doctor()
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["ready"])

    def test_workspace_can_continue_with_native_tools_pending(self):
        self.make_legacy_runtime()
        runner = FakeRunner(self.requirements)
        manager = self.manager(runner, missing_tools=(*runtime.NATIVE_TOOLS, "brew"))
        workspace = manager.doctor(capability="workspace")
        self.assertTrue(workspace["ready"])
        self.assertEqual(workspace["native_tools"]["missing"], list(runtime.NATIVE_TOOLS))
        self.assertFalse(workspace["native_install"]["available"])
        self.assertEqual(manager.doctor()["status"], "native-tool-missing")
        self.assertEqual(manager.verify()["status"], "native-tool-missing")
        self.assertFalse(any("runtime_probe.py" in str(command) for command, _ in runner.commands))

    def test_workspace_still_requires_usable_python_and_managed_packages(self):
        missing = (*runtime.NATIVE_TOOLS, "brew", self.bootstrap)
        report = self.manager(
            FakeRunner(self.requirements), missing_tools=missing
        ).doctor(capability="workspace")
        self.assertEqual(report["status"], "python-unavailable")
        self.assertEqual(report["native_tools"]["missing"], list(runtime.NATIVE_TOOLS))
        self.make_legacy_runtime()
        report = self.manager(
            FakeRunner(self.requirements, missing_modules=("yaml",))
        ).doctor(capability="workspace")
        self.assertEqual(report["status"], "python-package-missing")
        self.assertFalse(report["ready"])

    def test_verify_uses_managed_python_and_detected_tools_without_installing(self):
        python = self.make_legacy_runtime()
        runner = FakeRunner(self.requirements)
        before = sorted(self.base.rglob("*"))
        report = self.manager(runner).verify()
        self.assertTrue(report["verification"]["ok"])
        self.assertTrue(report["ready"])
        self.assertFalse(report["changed"])
        self.assertEqual(sorted(self.base.rglob("*")), before)
        command, options = runner.commands[-1]
        self.assertEqual(command[0], str(python.resolve()))
        self.assertEqual(command[-4:], [f"/synthetic/bin/{name}" for name in runtime.NATIVE_TOOLS])
        self.assertEqual(options["timeout"], 60)
        self.assertFalse(any("install" in command or "venv" in command for command, _ in runner.commands))

    def test_failed_pdf_check_can_be_retried_without_blocking_workspace_work(self):
        self.make_legacy_runtime()
        runner = FakeRunner(self.requirements, fail_stage="runtime-probe")
        manager = self.manager(runner)
        failed = manager.verify()
        self.assertEqual(failed["status"], "install-failed")
        self.assertFalse(failed["ready"])
        self.assertIn("synthetic PDF check failure", failed["technical_detail"])
        self.assertTrue(manager.doctor(capability="workspace")["ready"])
        runner.fail_stage = None
        self.assertTrue(manager.verify()["ready"])
        self.assertFalse(any("install" in command or "venv" in command for command, _ in runner.commands))

    def test_verify_rejects_incomplete_success_and_subprocess_timeout(self):
        self.make_legacy_runtime()
        manager = self.manager(FakeRunner(self.requirements))
        for output in ('{"ok":true}', '[]', 'not-json'):
            with self.subTest(output=output), mock.patch.object(manager, "_run", wraps=manager._run) as run:
                original = run._mock_wraps
                run.side_effect = lambda command, **kw: (
                    subprocess.CompletedProcess(command, 0, output, "")
                    if any(str(value).endswith("/runtime_probe.py") for value in command)
                    else original(command, **kw))
                self.assertFalse(manager.verify()["ready"])

        runner = FakeRunner(self.requirements)

        def timeout_probe(command, **kwargs):
            if any(str(value).endswith("/runtime_probe.py") for value in command):
                raise subprocess.TimeoutExpired(command, 60)
            return runner(command, **kwargs)

        self.assertFalse(self.manager(timeout_probe).verify()["ready"])

    def test_doctor_reports_missing_python_packages_by_distribution_name(self):
        self.make_legacy_runtime()
        result = self.manager(
            FakeRunner(self.requirements, missing_modules=("PIL", "yaml"))
        ).doctor()
        self.assertEqual(result["status"], "python-package-missing")
        self.assertEqual(result["python_packages"]["missing"], ["Pillow", "PyYAML"])

    def test_doctor_reports_native_tools_separately(self):
        self.make_legacy_runtime()
        result = self.manager(
            FakeRunner(self.requirements), missing_tools=("pdffonts",)
        ).doctor()
        self.assertEqual(result["status"], "native-tool-missing")
        self.assertEqual(result["native_tools"]["missing"], ["pdffonts"])
        self.assertTrue(result["python_packages"]["ready"])
        self.assertEqual(result["native_install"]["method"], "Homebrew")
        self.assertEqual(result["native_install"]["command"][-2:], ["install", "poppler"])

    def test_native_install_uses_detected_homebrew_command(self):
        self.make_legacy_runtime()
        runner = FakeRunner(self.requirements)
        result = self.manager(runner, missing_tools=("pdffonts",)).native_install()
        self.assertEqual(result["operation"], "native-install")
        command = next(command for command, _ in runner.commands if command[1:] == ["install", "poppler"])
        self.assertEqual(command[0], "/synthetic/bin/brew")

    def test_native_install_plan_is_unavailable_without_supported_manager(self):
        self.make_legacy_runtime()
        result = self.manager(
            FakeRunner(self.requirements),
            missing_tools=(*runtime.NATIVE_TOOLS, "brew"),
        ).doctor()
        self.assertFalse(result["native_install"]["available"])
        self.assertIsNone(result["native_install"]["command"])

    def test_doctor_reports_package_version_mismatch(self):
        self.make_legacy_runtime()

        class VersionRunner(FakeRunner):
            def __call__(self, command, **kwargs):
                result = super().__call__(command, **kwargs)
                if runtime.PACKAGE_PROBE in command:
                    observed = json.loads(result.stdout)
                    next(item for item in observed if item["distribution"] == "weasyprint")["installed"] = "69.9"
                    result.stdout = json.dumps(observed)
                return result

        result = self.manager(VersionRunner(self.requirements)).doctor()
        self.assertEqual(result["status"], "python-package-missing")
        self.assertEqual(result["python_packages"]["mismatched"][0]["distribution"], "weasyprint")

    def test_doctor_reports_pip_version_mismatch(self):
        self.make_legacy_runtime()
        (self.repo / "requirements.txt").write_text("pip==26.2.2\n", encoding="utf-8")

        class PipRunner(FakeRunner):
            def __call__(self, command, **kwargs):
                result = super().__call__(command, **kwargs)
                if runtime.PACKAGE_PROBE in command:
                    result.stdout = json.dumps([{
                        "distribution": "pip", "module": "", "installed": "26.2.1", "importable": True,
                    }])
                return result

        result = self.manager(PipRunner(self.requirements)).doctor()
        self.assertEqual(result["status"], "python-package-missing")
        self.assertEqual(result["python_packages"]["mismatched"][0]["distribution"], "pip")

    def test_doctor_rejects_old_managed_python_even_with_patched_bootstrap(self):
        runner = FakeRunner(self.requirements)
        python = self.make_legacy_runtime()
        runner.versions[str(python.resolve())] = (3, 14, 6, "final")
        result = self.manager(runner).doctor(capability="workspace")
        self.assertEqual(result["status"], "python-unavailable")
        self.assertIn("3.14.10", result["next_action"])
        self.assertEqual(result["python"]["managed_version"], [3, 14, 6])

    def test_doctor_rejects_prerelease_bootstrap_python(self):
        runner = FakeRunner(self.requirements)
        runner.versions[self.bootstrap] = (3, 15, 2, "candidate")
        result = self.manager(runner).doctor()
        self.assertEqual(result["status"], "python-unavailable")
        self.assertIn("prereleases", result["next_action"])

    def test_version_probe_disables_site_initialization(self):
        runner = FakeRunner(self.requirements)
        self.manager(runner).doctor()
        version_commands = [
            command for command, _ in runner.commands if runtime.VERSION_PROBE in command
        ]
        self.assertTrue(version_commands)
        self.assertTrue(all(command[1:4] == ["-I", "-S", "-B"] for command in version_commands))

    def test_doctor_fails_closed_on_escaping_pointer(self):
        self.support.mkdir(parents=True)
        (self.support / runtime.ACTIVE_RUNTIME_POINTER).write_text(
            json.dumps({"schema_version": 1, "environment": "../outside/python", "previous_environment": None}),
            encoding="utf-8",
        )
        runner = FakeRunner(self.requirements)
        result = self.manager(runner).doctor()
        self.assertEqual(result["status"], "python-unavailable")
        self.assertTrue(result["runtime"]["pointer_error"])
        self.assertFalse(runner.commands)

    def test_create_makes_empty_venv_only_when_missing_and_preserves_existing_runtime(self):
        runner = FakeRunner(self.requirements)
        manager = self.manager(runner)
        result = manager.create_environment()
        self.assertEqual(result["operation"], "create")
        command = next(command for command, _ in runner.commands if "venv" in command)
        self.assertIn("--without-pip", command)
        self.assertFalse(any(runtime.INSTALL_PIP_SCRIPT in command for command, _ in runner.commands))

        before = (self.support / "python" / "bin" / "python").read_bytes()
        again = manager.create_environment()
        self.assertEqual(again["status"], "install-failed")
        self.assertEqual((self.support / "python" / "bin" / "python").read_bytes(), before)

    def test_setup_stages_verified_generation_and_keeps_legacy_environment(self):
        runner = FakeRunner(self.requirements)
        old_python = self.make_legacy_runtime()
        old_bytes = old_python.read_bytes()
        runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
        downloader, calls = self.downloader()
        manager = self.manager(runner, downloader=downloader)
        expected_hash = hashlib.sha256(WHEEL_BYTES).hexdigest()
        with mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", expected_hash):
            result = manager.setup()

        self.assertEqual(result["status"], "ready")
        receipt = result["migration"]
        self.assertTrue(receipt["verified"])
        self.assertTrue(receipt["retained_previous"])
        self.assertEqual(Path(receipt["previous_environment"]), (self.support / "python").resolve())
        self.assertTrue(str(receipt["current_environment"]).endswith("/generations/" + Path(receipt["current_environment"]).parent.name + "/python"))
        pointer = json.loads((self.support / runtime.ACTIVE_RUNTIME_POINTER).read_text())
        self.assertEqual(pointer["environment"], Path(receipt["current_environment"]).relative_to(self.support.resolve()).as_posix())
        self.assertEqual(pointer["previous_environment"], "python")
        self.assertEqual(old_python.read_bytes(), old_bytes)
        self.assertEqual(result["runtime"]["python"], str(Path(receipt["current_environment"]) / "bin" / "python"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(command[0] != self.bootstrap for command, _ in runner.commands if runtime.INSTALL_PIP_SCRIPT in command or "pip" in command))
        pip_install = next(command for command, kwargs in runner.commands if len(command) > 5 and command[1:5] == ["-I", "-m", "pip", "--isolated"])
        options = next(kwargs for command, kwargs in runner.commands if command == pip_install)
        self.assertIn("--index-url", pip_install)
        self.assertEqual(options["env"]["PIP_CONFIG_FILE"], runtime.os.devnull)
        self.assertNotIn("PIP_INDEX_URL", options["env"])

    def test_both_pip_phases_ignore_external_configuration_and_cache_writes(self):
        runner = FakeRunner(self.requirements)
        downloader, _ = self.downloader()
        manager = self.manager(runner, downloader=downloader)
        with mock.patch.dict(runtime.os.environ, {"PIP_TARGET": "/synthetic/outside", "PIP_INDEX_URL": "https://example.invalid/simple"}), \
                mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", hashlib.sha256(WHEEL_BYTES).hexdigest()):
            result = manager.setup()
        self.assertEqual(result["status"], "ready")
        phases = [(command, options) for command, options in runner.commands
                  if runtime.INSTALL_PIP_SCRIPT in command or "--requirement" in command]
        self.assertEqual(len(phases), 2)
        for command, options in phases:
            self.assertEqual(options["env"]["PIP_CONFIG_FILE"], runtime.os.devnull)
            self.assertNotIn("PIP_TARGET", options["env"])
            self.assertNotIn("PIP_INDEX_URL", options["env"])
            if runtime.INSTALL_PIP_SCRIPT in command:
                self.assertIn("--no-cache-dir", runtime.INSTALL_PIP_SCRIPT)
            else:
                self.assertIn("--no-cache-dir", command)
        creation = next(command for command, _ in runner.commands if "venv" in command)
        self.assertEqual(creation[1:6], ["-I", "-S", "-m", "venv", "--without-pip"])

    def test_wrong_hash_wrong_host_and_oversize_stop_before_pip_execution(self):
        cases = (
            (WHEEL_BYTES + b"bad", None, "SHA-256"),
            (WHEEL_BYTES, "https://packages.evil.invalid/pip.whl", "approved HTTPS host"),
            (b"x" * (runtime.MAX_PIP_WHEEL_BYTES + 1), None, "invalid size"),
        )
        for data, final_url, detail in cases:
            with self.subTest(detail=detail):
                self.support = self.base / detail.replace(" ", "-") / "runtime"
                runner = FakeRunner(self.requirements)
                old_python = self.make_legacy_runtime()
                runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
                downloader, _ = self.downloader(data, final_url)
                manager = self.manager(runner, downloader=downloader)
                with mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", hashlib.sha256(WHEEL_BYTES).hexdigest()):
                    result = manager.setup()
                self.assertEqual(result["status"], "install-failed")
                self.assertIn(detail, result["technical_detail"])
                self.assertFalse(any(runtime.INSTALL_PIP_SCRIPT in command for command, _ in runner.commands))

    def test_failed_requirements_install_keeps_pointer_and_old_runtime_bytes(self):
        runner = FakeRunner(self.requirements, fail_stage="requirements-install")
        old_python = self.make_legacy_runtime()
        old_bytes = old_python.read_bytes()
        runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
        downloader, _ = self.downloader()
        manager = self.manager(runner, downloader=downloader)
        with mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", hashlib.sha256(WHEEL_BYTES).hexdigest()):
            result = manager.setup()
        self.assertEqual(result["status"], "install-failed")
        self.assertFalse(result["migration"]["changed"])
        self.assertEqual(old_python.read_bytes(), old_bytes)
        self.assertFalse((self.support / runtime.ACTIVE_RUNTIME_POINTER).exists())

    def test_install_keeps_missing_environment_contract(self):
        runner = FakeRunner(self.requirements)
        result = self.manager(runner).install_requirements()
        self.assertEqual(result["status"], "install-failed")
        self.assertFalse(result["changed"])
        self.assertFalse(runner.commands)

    def test_failed_selected_runtime_probe_restores_prior_pointer_bytes(self):
        runner = FakeRunner(self.requirements, fail_stage="selected-package-probe")
        old_python = self.make_legacy_runtime()
        runner.package_versions[str(old_python.resolve())] = {"pypdf": "old"}
        pointer = self.support / runtime.ACTIVE_RUNTIME_POINTER
        pointer.parent.mkdir(parents=True, exist_ok=True)
        previous = {"schema_version": 1, "environment": "python", "previous_environment": None}
        pointer_bytes = (json.dumps(previous, sort_keys=True, separators=(",", ":")) + "\n").encode()
        pointer.write_bytes(pointer_bytes)
        downloader, _ = self.downloader()
        manager = self.manager(runner, downloader=downloader)
        with mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", hashlib.sha256(WHEEL_BYTES).hexdigest()):
            result = manager.setup()
        self.assertEqual(result["status"], "install-failed")
        self.assertEqual(pointer.read_bytes(), pointer_bytes)
        self.assertEqual(old_python.read_bytes(), b"keep this legacy interpreter")

    def test_failed_pointer_restoration_retains_the_selected_candidate(self):
        runner = FakeRunner(self.requirements, fail_stage="selected-package-probe")
        old_python = self.make_legacy_runtime()
        runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
        downloader, _ = self.downloader()
        manager = self.manager(runner, downloader=downloader)
        write_pointer = manager._write_pointer_bytes

        def fail_restore(data):
            if data is None:
                raise OSError("synthetic pointer restoration failure")
            write_pointer(data)

        with (
            mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", hashlib.sha256(WHEEL_BYTES).hexdigest()),
            mock.patch.object(manager, "_write_pointer_bytes", side_effect=fail_restore),
        ):
            result = manager.setup()

        self.assertEqual(result["status"], "install-failed")
        self.assertTrue(result["changed"])
        self.assertTrue(result["migration"]["recovery_required"])
        pointer = json.loads((self.support / runtime.ACTIVE_RUNTIME_POINTER).read_text())
        selected = self.support / pointer["environment"]
        self.assertTrue(selected.is_dir())
        self.assertTrue((selected / "bin" / "python").is_file())
        self.assertEqual(pointer["previous_environment"], "python")

    def test_manual_rollback_requires_previous_runtime_to_pass_current_policy(self):
        runner = FakeRunner(self.requirements)
        old_python = self.make_legacy_runtime()
        runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
        active = self.support / "generations" / ("g-" + "a" * 32) / "python"
        active_python = active / "bin" / "python"
        active_python.parent.mkdir(parents=True)
        active_python.write_bytes(b"current interpreter")
        pointer = self.support / runtime.ACTIVE_RUNTIME_POINTER
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({
            "schema_version": 1,
            "environment": active.relative_to(self.support).as_posix(),
            "previous_environment": "python",
        }), encoding="utf-8")
        manager = self.manager(runner)
        before = pointer.read_bytes()
        result = manager.rollback()
        self.assertEqual(result["status"], "install-failed")
        self.assertIn("current security policy", result["message"])
        self.assertEqual(pointer.read_bytes(), before)

    def test_manual_rollback_selects_a_retained_runtime_that_still_passes(self):
        runner = FakeRunner(self.requirements)
        old_python = self.make_legacy_runtime()
        active = self.support / "generations" / ("g-" + "b" * 32) / "python"
        active_python = active / "bin" / "python"
        active_python.parent.mkdir(parents=True)
        active_python.write_bytes(b"current interpreter")
        pointer = self.support / runtime.ACTIVE_RUNTIME_POINTER
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({
            "schema_version": 1,
            "environment": active.relative_to(self.support).as_posix(),
            "previous_environment": "python",
        }), encoding="utf-8")

        result = self.manager(runner).rollback()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(Path(result["runtime"]["environment"]), (self.support / "python").resolve())
        self.assertEqual(Path(result["migration"]["retained_previous"]), active.resolve())
        self.assertEqual(old_python.read_bytes(), b"keep this legacy interpreter")

    def test_failed_rollback_restoration_returns_recovery_status_and_retains_both_runtimes(self):
        runner = FakeRunner(self.requirements)
        old_python = self.make_legacy_runtime()
        active = self.support / "generations" / ("g-" + "c" * 32) / "python"
        active_python = active / "bin" / "python"
        active_python.parent.mkdir(parents=True)
        active_python.write_bytes(b"current interpreter")
        pointer = self.support / runtime.ACTIVE_RUNTIME_POINTER
        pointer.write_text(json.dumps({"schema_version": 1,
            "environment": active.relative_to(self.support).as_posix(),
            "previous_environment": "python"}))
        manager = self.manager(runner)
        original_write = manager._write_pointer_bytes
        writes = 0

        def fail_restore(data):
            nonlocal writes
            writes += 1
            if writes > 1:
                raise OSError("synthetic rollback restoration failure")
            original_write(data)

        with mock.patch.object(manager, "doctor", return_value={"status": "python-unavailable"}), \
                mock.patch.object(manager, "_write_pointer_bytes", side_effect=fail_restore):
            result = manager.rollback()
        self.assertEqual(result["status"], "install-failed")
        self.assertTrue(result["changed"])
        self.assertTrue(result["migration"]["recovery_required"])
        self.assertTrue(active_python.is_file())
        self.assertEqual(old_python.read_bytes(), b"keep this legacy interpreter")
        self.assertEqual(json.loads(pointer.read_text())["environment"], "python")

    def test_explicit_install_cannot_report_success_without_a_patched_bootstrap(self):
        self.make_legacy_runtime()
        for unavailable in (True, False):
            with self.subTest(unavailable=unavailable):
                runner = FakeRunner(self.requirements)
                runner.versions[self.bootstrap] = (3, 14, 6, "final")
                manager = self.manager(runner, missing_tools=(self.bootstrap,) if unavailable else ())
                self.assertEqual(manager.doctor()["status"], "ready")
                result = manager.install_requirements()
                self.assertEqual(result["status"], "install-failed")
                self.assertFalse(result["changed"])
                self.assertFalse(any("venv" in command for command, _ in runner.commands))

    def test_workspace_runtime_can_activate_without_native_pdf_tools(self):
        runner = FakeRunner(self.requirements)
        old_python = self.make_legacy_runtime()
        runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
        downloader, _ = self.downloader()
        manager = self.manager(runner, missing_tools=runtime.NATIVE_TOOLS, downloader=downloader)
        with mock.patch.object(runtime.runtime_security, "PIP_WHEEL_SHA256", hashlib.sha256(WHEEL_BYTES).hexdigest()):
            result = manager.setup()
        self.assertEqual(result["status"], "native-tool-missing")
        self.assertTrue(result["python_packages"]["ready"])
        self.assertTrue(result["migration"]["verified"])

    def test_concurrent_runtime_operation_blocks_without_changing_pointer(self):
        runner = FakeRunner(self.requirements)
        old_python = self.make_legacy_runtime()
        runner.versions[str(old_python.resolve())] = (3, 14, 6, "final")
        manager = self.manager(runner)
        before = (self.support / "python" / "bin" / "python").read_bytes()
        from contextlib import contextmanager

        @contextmanager
        def busy_lock():
            yield False

        with mock.patch.object(manager, "_runtime_lock", return_value=busy_lock()):
            result = manager.setup()
        self.assertEqual(result["status"], "install-failed")
        self.assertEqual((self.support / "python" / "bin" / "python").read_bytes(), before)
        self.assertFalse(any("venv" in command for command, _ in runner.commands))

    def test_default_support_directory_is_not_a_church_folder(self):
        home = self.base / "pastor-home"
        result = runtime.default_runtime_root(system="Darwin", home=home, environ={})
        self.assertEqual(
            result,
            home / "Library" / "Application Support" / "Handbuilt Church Labs" / "runtime",
        )

    def test_statuses_and_manifest_main_dependencies_are_stable(self):
        self.assertEqual(runtime.runtime_security.PIP_VERSION, "26.2.2")
        manifest = [
            line.split("==", 1)[0]
            for line in (Path(__file__).resolve().parents[1] / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line and not line.startswith("#") and not line.startswith((
                "pip==", "certifi==", "setuptools==", "brotli==", "cffi==", "cssselect2==",
                "fonttools==", "pycparser==", "pydyf==", "pyphen==", "tinycss2==", "tinyhtml5==",
                "typing_extensions==", "webencodings==", "zopfli==",
            ))
        ]
        self.assertEqual(manifest, list(runtime.PACKAGE_IMPORTS))

    def test_rollback_is_exposed_by_the_cli_parser(self):
        args = runtime.build_parser().parse_args(["rollback"])
        self.assertEqual(args.operation, "rollback")

    def test_direct_rollback_cli_calls_the_runtime_method(self):
        runtime_root = self.base / "rollback-runtime-root"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(runtime.__file__).resolve()),
                "rollback",
                "--format",
                "json",
                "--runtime-root",
                str(runtime_root),
            ],
            cwd=self.base,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 20, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["operation"], "rollback")
        self.assertEqual(report["status"], "install-failed")

    def test_direct_isolated_cli_imports_without_pythonpath_or_repository_cwd(self):
        script = Path(runtime.__file__).resolve()
        runtime_root = self.base / "unused-runtime-root"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(script),
                "doctor",
                "--format",
                "json",
                "--runtime-root",
                str(runtime_root),
            ],
            cwd=self.base,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["operation"], "doctor")
        self.assertFalse(runtime_root.exists())


if __name__ == "__main__":
    unittest.main()
