import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import handbuilt_runtime as runtime


class FakeRunner:
    def __init__(self, *, missing_modules=(), fail_operation=None, create_python=None):
        self.commands = []
        self.missing_modules = list(missing_modules)
        self.fail_operation = fail_operation
        self.create_python = create_python

    def __call__(self, command, **kwargs):
        self.commands.append((list(command), kwargs))
        if command[1:3] == ["-m", "venv"]:
            if self.fail_operation == "create":
                return subprocess.CompletedProcess(command, 1, "", "venv failed")
            if self.create_python is not None:
                self.create_python.parent.mkdir(parents=True, exist_ok=True)
                self.create_python.touch()
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:4] == ["-m", "pip", "install"]:
            if self.fail_operation == "install":
                return subprocess.CompletedProcess(command, 1, "", "pip failed")
            self.missing_modules = []
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["install", "poppler"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if runtime.VERSION_PROBE in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({"version": [3, 12, 1]}), "")
        if runtime.PACKAGE_PROBE in command:
            missing = set(self.missing_modules)
            observed = [
                {
                    "distribution": distribution,
                    "module": module,
                    "installed": None if module in missing else "synthetic",
                    "importable": module not in missing,
                }
                for distribution, module in runtime.PACKAGE_IMPORTS.items()
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(observed), "")
        raise AssertionError(f"Unexpected command: {command}")


class RuntimeManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "requirements.txt").write_text("pypdf\n", encoding="utf-8")
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

    def manager(self, runner, *, missing_tools=()):
        return runtime.RuntimeManager(
            repo_root=self.repo,
            runtime_root=self.support,
            bootstrap_python=self.bootstrap,
            system="Darwin",
            runner=runner,
            which=self.which(missing_tools),
        )

    def make_managed_python(self):
        python = self.support / "python" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.touch()
        return python

    def test_doctor_does_not_create_or_install_when_runtime_is_absent(self):
        runner = FakeRunner()
        manager = self.manager(runner)

        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("doctor wrote to disk")):
            result = manager.doctor()

        self.assertEqual(result["status"], "python-package-missing")
        self.assertFalse(self.support.exists())
        self.assertFalse(any("venv" in command or "pip" in command for command, _ in runner.commands))

    def test_doctor_reports_ready_with_managed_packages_and_native_tools(self):
        self.make_managed_python()
        result = self.manager(FakeRunner()).doctor()

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["ready"])
        self.assertEqual(result["python_packages"]["missing"], [])
        self.assertEqual(result["native_tools"]["scope"], "operating-system")
        self.assertEqual(result["native_tools"]["required"], list(runtime.NATIVE_TOOLS))

    def test_doctor_reports_unavailable_bootstrap_python(self):
        result = self.manager(FakeRunner(), missing_tools=(self.bootstrap,)).doctor()

        self.assertEqual(result["status"], "python-unavailable")
        self.assertFalse(result["ready"])

    def test_doctor_rejects_unsupported_python_with_actionable_status(self):
        class OldPythonRunner(FakeRunner):
            def __call__(self, command, **kwargs):
                result = super().__call__(command, **kwargs)
                if runtime.VERSION_PROBE in command:
                    result.stdout = json.dumps({"version": [3, 9, 6]})
                return result
        result = self.manager(OldPythonRunner()).doctor()
        self.assertEqual(result["status"], "python-unavailable")
        self.assertIn("3.10", result["next_action"])

    def test_ready_managed_runtime_does_not_require_bootstrap_python(self):
        self.make_managed_python()
        result = self.manager(FakeRunner(), missing_tools=(self.bootstrap,)).doctor()

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["ready"])

    def test_doctor_reports_missing_python_packages_by_distribution_name(self):
        self.make_managed_python()
        runner = FakeRunner(missing_modules=("PIL", "yaml"))
        result = self.manager(runner).doctor()

        self.assertEqual(result["status"], "python-package-missing")
        self.assertEqual(result["python_packages"]["missing"], ["Pillow", "PyYAML"])

    def test_doctor_reports_native_tools_separately(self):
        self.make_managed_python()
        result = self.manager(FakeRunner(), missing_tools=("pdffonts",)).doctor()

        self.assertEqual(result["status"], "native-tool-missing")
        self.assertEqual(result["native_tools"]["missing"], ["pdffonts"])
        self.assertTrue(result["python_packages"]["ready"])
        self.assertEqual(result["native_install"]["method"], "Homebrew")
        self.assertEqual(result["native_install"]["command"][-2:], ["install", "poppler"])

    def test_native_install_uses_the_detected_homebrew_command(self):
        self.make_managed_python()
        runner = FakeRunner()
        result = self.manager(runner, missing_tools=("pdffonts",)).native_install()

        self.assertEqual(result["operation"], "native-install")
        command = next(command for command, _ in runner.commands if command[1:] == ["install", "poppler"])
        self.assertEqual(command[0], "/synthetic/bin/brew")

    def test_native_install_plan_is_unavailable_without_a_supported_manager(self):
        self.make_managed_python()
        result = self.manager(
            FakeRunner(),
            missing_tools=("pdftoppm", "pdfinfo", "pdffonts", "pdftotext", "brew"),
        ).doctor()

        self.assertFalse(result["native_install"]["available"])
        self.assertIsNone(result["native_install"]["command"])

    def test_create_uses_venv_in_support_directory_and_never_runs_pip(self):
        managed_python = self.support / "python" / "bin" / "python"
        runner = FakeRunner(missing_modules=tuple(runtime.PACKAGE_IMPORTS.values()), create_python=managed_python)
        result = self.manager(runner).create_environment()

        commands = [command for command, _ in runner.commands]
        self.assertEqual(result["operation"], "create")
        self.assertEqual(result["status"], "python-package-missing")
        self.assertIn([self.bootstrap, "-m", "venv", str(self.support / "python")], commands)
        self.assertFalse(any(command[1:4] == ["-m", "pip", "install"] for command in commands))

    def test_setup_creates_and_installs_in_one_host_operation(self):
        managed_python = self.support / "python" / "bin" / "python"
        runner = FakeRunner(
            missing_modules=tuple(runtime.PACKAGE_IMPORTS.values()),
            create_python=managed_python,
        )
        result = self.manager(runner).setup()

        commands = [command for command, _ in runner.commands]
        self.assertEqual(result["operation"], "setup")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(sum(command[1:3] == ["-m", "venv"] for command in commands), 1)
        self.assertEqual(sum(command[1:4] == ["-m", "pip", "install"] for command in commands), 1)

    def test_install_uses_managed_python_and_requirements_file(self):
        managed_python = self.make_managed_python()
        runner = FakeRunner()
        manager = self.manager(runner)
        result = manager.install_requirements()

        install = next(command for command, _ in runner.commands if command[1:4] == ["-m", "pip", "install"])
        self.assertEqual(install[0], str(managed_python))
        self.assertIn(str(manager.requirements), install)
        self.assertEqual(result["status"], "ready")

    def test_install_does_not_create_a_missing_environment(self):
        runner = FakeRunner()
        result = self.manager(runner).install_requirements()

        self.assertEqual(result["status"], "install-failed")
        self.assertFalse(result["changed"])
        self.assertEqual(runner.commands, [])

    def test_failed_install_has_stable_status_and_no_global_pip_command(self):
        managed_python = self.make_managed_python()
        runner = FakeRunner(fail_operation="install")
        result = self.manager(runner).install_requirements()

        self.assertEqual(result["status"], "install-failed")
        install = runner.commands[0][0]
        self.assertEqual(install[0], str(managed_python))
        self.assertNotEqual(install[0], self.bootstrap)

    def test_failed_environment_creation_has_stable_install_failed_status(self):
        runner = FakeRunner(fail_operation="create")
        result = self.manager(runner).create_environment()

        self.assertEqual(result["status"], "install-failed")
        self.assertIn("venv failed", result["technical_detail"])

    def test_default_support_directory_is_not_a_church_folder(self):
        home = self.base / "pastor-home"
        result = runtime.default_runtime_root(system="Darwin", home=home, environ={})

        self.assertEqual(
            result,
            home / "Library" / "Application Support" / "Handbuilt Church Labs" / "runtime",
        )

    def test_status_vocabulary_and_requirement_manifest_are_stable(self):
        self.assertEqual(
            runtime.STATUSES,
            (
                "ready",
                "python-unavailable",
                "python-package-missing",
                "native-tool-missing",
                "install-failed",
            ),
        )
        manifest = [
            line.split("==", 1)[0]
            for line in (Path(__file__).resolve().parents[1] / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line and not line.startswith("#") and not line.startswith(("pip==", "setuptools==", "brotli==", "cffi==", "cssselect2==", "fonttools==", "pycparser==", "pydyf==", "pyphen==", "tinycss2==", "tinyhtml5==", "typing_extensions==", "webencodings==", "zopfli=="))
        ]
        self.assertEqual(manifest, list(runtime.PACKAGE_IMPORTS))

    def test_doctor_reports_supported_package_version_mismatch(self):
        self.make_managed_python()
        (self.repo / "requirements.txt").write_text("weasyprint==66.0\n", encoding="utf-8")
        class VersionRunner(FakeRunner):
            def __call__(self, command, **kwargs):
                result = super().__call__(command, **kwargs)
                if runtime.PACKAGE_PROBE in command:
                    observed = json.loads(result.stdout)
                    observed[0]["installed"] = "65.1"
                    result.stdout = json.dumps(observed)
                return result
        result = self.manager(VersionRunner()).doctor()
        self.assertEqual(result["status"], "python-package-missing")
        self.assertEqual(result["python_packages"]["mismatched"][0]["distribution"], "weasyprint")
        self.assertFalse(result["python_packages"]["ready"])

    def test_doctor_reports_pip_version_mismatch(self):
        self.make_managed_python()
        (self.repo / "requirements.txt").write_text("pip==26.2.1\n", encoding="utf-8")
        class PipRunner(FakeRunner):
            def __call__(self, command, **kwargs):
                result = super().__call__(command, **kwargs)
                if runtime.PACKAGE_PROBE in command:
                    result.stdout = json.dumps([{"distribution": "pip", "module": "", "installed": "26.1.2", "importable": True}])
                return result
        result = self.manager(PipRunner()).doctor()
        self.assertEqual(result["status"], "python-package-missing")
        self.assertEqual(result["python_packages"]["mismatched"][0]["distribution"], "pip")


if __name__ == "__main__":
    unittest.main()
