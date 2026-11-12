"""Handbuilt brings its own Python, so a pastor never installs one.

These checks need no network. The real download, on Windows, macOS and Linux,
runs in .github/workflows/install.yml.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import native_libraries, runtime_security  # noqa: E402

LOCK = ROOT / "tools" / "python-dist.lock"
SHELL_LAUNCHER = ROOT / "bin" / "handbuilt-python"
WINDOWS_LAUNCHER = ROOT / "bin" / "handbuilt-python.cmd"
COMPUTERS = {"darwin-aarch64", "darwin-x86_64", "linux-aarch64", "linux-x86_64", "windows-x86_64"}
SOURCE = "https://github.com/astral-sh/python-build-standalone/releases/download/"


def read_lock() -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, *rest = line.split()
            entries[key] = rest
    return entries


class PythonLock(unittest.TestCase):
    def test_every_supported_computer_has_a_checked_build(self):
        entries = read_lock()
        self.assertEqual(set(entries) - {"release", "version"}, COMPUTERS)
        version = entries["version"][0]
        for computer in COMPUTERS:
            sha, url = entries[computer]
            self.assertRegex(sha, r"^[0-9a-f]{64}$", computer)
            self.assertTrue(url.startswith(SOURCE), computer)
            self.assertIn(f"cpython-{version}+", url, computer)
            self.assertTrue(url.endswith("-install_only_stripped.tar.gz"), computer)
        self.assertEqual(len({entries[c][0] for c in COMPUTERS}), len(COMPUTERS), "two computers share one checksum")

    def test_the_build_meets_the_security_floor_and_can_run_the_runtime(self):
        entries = read_lock()
        version = tuple(int(part) for part in entries["version"][0].split("."))
        self.assertIsNone(runtime_security.python_security_error(version))
        self.assertIsNone(runtime_security.python_runtime_error(version))
        self.assertRegex(entries["release"][0], r"^cpython-\d+\.\d+\.\d+-\d{8}$")
        self.assertIn(entries["version"][0], entries["release"][0])

    def test_line_endings_survive_git_on_windows(self):
        self.assertNotIn(b"\r", LOCK.read_bytes())
        self.assertNotIn(b"\r", SHELL_LAUNCHER.read_bytes())
        windows = WINDOWS_LAUNCHER.read_bytes()
        self.assertEqual(windows.count(b"\n"), windows.count(b"\r\n"), "a command file needs Windows line endings")
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        for rule in ("bin/handbuilt-python text eol=lf", "tools/python-dist.lock text eol=lf", "*.cmd -text"):
            self.assertIn(rule, attributes)


class Launchers(unittest.TestCase):
    def test_the_shell_launcher_is_runnable_and_well_formed(self):
        self.assertTrue(os.access(SHELL_LAUNCHER, os.X_OK) or os.name == "nt")
        if os.name != "nt":
            done = subprocess.run(["sh", "-n", str(SHELL_LAUNCHER)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_both_launchers_check_the_download_before_using_it(self):
        shell = SHELL_LAUNCHER.read_text(encoding="utf-8")
        windows = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        for text in (shell, windows):
            self.assertIn("python-dist.lock", text)
            self.assertIn("--proto", text)
            self.assertIn("did not match its recorded checksum", text)
            self.assertIn("--where", text)
            self.assertNotRegex(text, r"[^\x00-\x7f]")
        # The checksum is compared before anything is unpacked.
        self.assertLess(shell.index('[ "$got" = "$sha" ]'), shell.index("tar -xzf"))
        self.assertLess(windows.index('"%GOT%"=="%SHA%"'), windows.index("tar.exe"))
        # Windows uses its own curl and tar, not Git's, which cannot read C:\ paths.
        self.assertIn(r"%SystemRoot%\System32\tar.exe", windows)
        self.assertIn(r"%SystemRoot%\System32\curl.exe", windows)

    def test_both_launchers_use_the_folder_the_runtime_uses(self):
        shell = SHELL_LAUNCHER.read_text(encoding="utf-8")
        windows = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("Library/Application Support/Handbuilt Church Labs/runtime", shell)
        self.assertIn("handbuilt-church-labs/runtime", shell)
        self.assertIn("Handbuilt Church Labs/runtime", shell)
        self.assertIn(r"%LOCALAPPDATA%\Handbuilt Church Labs\runtime", windows)
        for text in (shell, windows):
            self.assertIn("HANDBUILT_RUNTIME_HOME", text)

    @unittest.skipIf(os.name == "nt", "the shell launcher is exercised in the install workflow on Windows")
    def test_a_download_that_does_not_match_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "bin").mkdir()
            (base / "tools").mkdir()
            launcher = base / "bin" / "handbuilt-python"
            launcher.write_bytes(SHELL_LAUNCHER.read_bytes())
            launcher.chmod(0o755)
            # A fake curl that "downloads" something else.
            fake = base / "fakebin"
            fake.mkdir()
            (fake / "curl").write_text(
                '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = "-o" ] && out=$2; shift; done\nprintf tampered > "$out"\n',
                encoding="utf-8")
            (fake / "curl").chmod(0o755)
            lock = LOCK.read_text(encoding="utf-8")
            (base / "tools" / "python-dist.lock").write_text(lock, encoding="utf-8")
            home = base / "runtime"
            done = subprocess.run(
                [str(launcher), "--where"], capture_output=True, text=True,
                env={**os.environ, "HANDBUILT_RUNTIME_HOME": str(home), "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"})
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("did not match its recorded checksum", done.stderr)
            self.assertEqual(list((home / "python-dist").glob("cpython-*")), [], "an unchecked download was kept")
            self.assertEqual(list((home / "python-dist").glob(".tmp.*")), [], "the failed download was left behind")


class NativeLibraries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.prefix = self.root / "generations" / "g-1" / "python"
        self.prefix.mkdir(parents=True)

    def native(self, name: str, *, ready: bool = True) -> Path:
        folder = self.root / "native" / name
        (folder / "lib").mkdir(parents=True)
        (folder / "bin").mkdir()
        (folder / "Library" / "bin").mkdir(parents=True)
        if ready:
            (folder / native_libraries.READY_MARKER).write_text("ok", encoding="utf-8")
        return folder

    def test_only_finished_pdf_tool_folders_are_used_newest_first(self):
        old, new = self.native("2026-01"), self.native("2026-02")
        self.native("2026-03", ready=False)
        self.assertEqual(native_libraries.native_roots(self.prefix), [new, old])

    def test_folders_match_the_computer(self):
        folder = self.native("2026-01")
        self.assertEqual(native_libraries.library_directories(self.prefix, platform="linux"), [str(folder / "lib")])
        self.assertEqual(native_libraries.library_directories(self.prefix, platform="win32"),
                         [str(folder / "Library" / "bin")])
        self.assertEqual(native_libraries.tool_directories(self.prefix, platform="linux"), [str(folder / "bin")])
        self.assertEqual(native_libraries.library_directories(self.root / "a" / "b" / "c" / "d" / "e" / "f", platform="linux"), [])

    def test_importing_the_module_changes_nothing(self):
        # Only the copy that setup installs runs at startup.
        source = (ROOT / "tools" / "native_libraries.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "handbuilt_native_libraries":', source)


class Instructions(unittest.TestCase):
    def documents(self):
        for base in ("skills", "handbook"):
            yield from (ROOT / base).rglob("*.md")
        yield ROOT / "INSTALL.md"
        yield ROOT / "README.md"

    def test_no_instruction_runs_the_computers_own_python(self):
        offenders = []
        for path in self.documents():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if re.match(r"\s*(\$ )?python3? ", line) or "`python3 " in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(offenders, [], "use handbuilt-python; a pastor's computer may have no Python")

    def test_the_install_guide_covers_what_stopped_the_first_bootcamp(self):
        install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
        for needed in ("Do not install Python", "**File**, then **Exit**", "has not loaded Handbuilt yet"):
            self.assertIn(needed, install)
        doctor_advice = (ROOT / "tools" / "handbuilt_runtime.py").read_text(encoding="utf-8")
        self.assertIn("bin/handbuilt-python", doctor_advice)


if __name__ == "__main__":
    unittest.main()
