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

from tools import native_libraries, native_tools, runtime_security  # noqa: E402

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
        self.assertIn("\n* -text\n", attributes, "Git must not rewrite any file's line endings")


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
        self.assertIn(r"%USERPROFILE%\.handbuilt\runtime", windows)
        self.assertIn('"$USERPROFILE")/.handbuilt/runtime', shell)
        # Not AppData: the Claude desktop app redirects it to a folder too deep for Windows.
        for text in (shell, windows):
            self.assertNotIn("LOCALAPPDATA", text)
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

    def test_handbuilts_own_libraries_are_never_mixed_with_homebrews(self):
        """The PDF engine crashed on a Mac that had both: two copies of one library were loaded."""
        folder = self.native("2026-01")
        self.assertEqual(native_libraries.library_directories(self.prefix, platform="darwin"), [str(folder / "lib")])

    @unittest.skipIf(os.name == "nt", "plain library names are a Mac need")
    def test_each_library_gets_its_plain_name(self):
        lib = self.root / "lib"
        lib.mkdir()
        (lib / "libgobject-2.0.0.dylib").write_bytes(b"x")
        (lib / "libpango-1.0.0.dylib").write_bytes(b"x")
        (lib / "libpango-1.0.dylib").symlink_to("libpango-1.0.0.dylib")
        (lib / "libz.1.3.2.dylib").write_bytes(b"x")
        added = native_tools.add_plain_library_names(lib)
        self.assertIn("libgobject-2.0.dylib", added)
        self.assertIn("libz.dylib", added)
        self.assertNotIn("libpango-1.0.dylib", added, "an existing name is left alone")
        self.assertEqual((lib / "libgobject-2.0.dylib").resolve(), (lib / "libgobject-2.0.0.dylib").resolve())

    def test_handbuilts_pdf_tools_are_found_by_name(self):
        """On a Mac with no other copy, bulletins stopped: 'pdftoppm is not on PATH'."""
        from unittest import mock
        folder = self.native("2026-01")
        tools = folder / ("Library/bin" if os.name == "nt" else "bin")
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=False):
            native_libraries.prepare(self.prefix)
            self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], str(tools))

    def test_importing_the_module_changes_nothing(self):
        # Only the copy that setup installs runs at startup.
        source = (ROOT / "tools" / "native_libraries.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "handbuilt_native_libraries":', source)


def conda_package(files: dict[str, bytes]) -> bytes:
    """A package in conda-forge's .conda format, built in memory."""
    import io
    import tarfile
    import zipfile
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:zst") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as package:
        package.writestr("metadata.json", "{}")
        package.writestr("info-sample-1.0-0.tar.zst", b"")
        package.writestr("pkg-sample-1.0-0.tar.zst", inner.getvalue())
    return outer.getvalue()


@unittest.skipIf(sys.version_info < (3, 14), "the package format needs Python 3.14")
class NativeTools(unittest.TestCase):
    URL = "https://conda.anaconda.org/conda-forge/osx-arm64/sample-1.0-0.conda"

    def setUp(self):
        from unittest import mock
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "runtime"
        self.lock = Path(self.temp.name) / "native-tools.lock"
        patcher = mock.patch.object(native_tools, "computer_key", return_value="darwin-aarch64")
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_lock(self, package: bytes, *, sha256: str | None = None, url: str | None = None) -> None:
        import hashlib
        self.lock.write_text(
            "# test\nrelease conda-forge-20260101\n"
            f"darwin-aarch64 {sha256 or hashlib.sha256(package).hexdigest()} {len(package)} {url or self.URL}\n",
            encoding="utf-8")

    def test_checked_packages_are_unpacked_and_found(self):
        package = conda_package({"bin/pdfinfo": b"tool", "lib/libpango-1.0.dylib": b"library"})
        self.write_lock(package)
        result = native_tools.install(self.root, lock=self.lock, fetch=lambda url, limit: package)
        self.assertTrue(result["installed"] and result["changed"])
        folder = self.root / "native" / "conda-forge-20260101"
        self.assertEqual((folder / "bin" / "pdfinfo").read_bytes(), b"tool")
        self.assertEqual(native_libraries.roots_under(self.root), [folder])
        again = native_tools.install(self.root, lock=self.lock, fetch=lambda url, limit: self.fail("downloaded twice"))
        self.assertFalse(again["changed"])

    def test_a_package_that_does_not_match_installs_nothing(self):
        package = conda_package({"bin/pdfinfo": b"tool"})
        self.write_lock(package, sha256="0" * 64)
        with self.assertRaisesRegex(native_tools.NativeToolsError, "did not match its recorded checksum"):
            native_tools.install(self.root, lock=self.lock, fetch=lambda url, limit: package)
        self.assertEqual(list((self.root / "native").iterdir()), [])

    def test_a_package_cannot_write_outside_its_folder(self):
        package = conda_package({"../../escaped.txt": b"x"})
        self.write_lock(package)
        with self.assertRaises(native_tools.NativeToolsError):
            native_tools.install(self.root, lock=self.lock, fetch=lambda url, limit: package)
        self.assertFalse((self.root.parent / "escaped.txt").exists())
        self.assertEqual(native_libraries.roots_under(self.root), [])

    def test_only_the_approved_source_is_accepted(self):
        package = conda_package({"bin/pdfinfo": b"tool"})
        for url in ("https://example.org/conda-forge/osx-arm64/sample-1.0-0.conda",
                    "http://conda.anaconda.org/conda-forge/osx-arm64/sample-1.0-0.conda",
                    "https://conda.anaconda.org/conda-forge/osx-arm64/sample-1.0-0.exe"):
            self.write_lock(package, url=url)
            with self.assertRaises(native_tools.NativeToolsError, msg=url):
                native_tools.read_lock(self.lock)

    def test_the_real_lock_covers_mac_and_windows_with_pango_and_poppler(self):
        release, packages = native_tools.read_lock()
        self.assertTrue(release.startswith("conda-forge-"))
        self.assertEqual(set(packages), {"darwin-aarch64", "darwin-x86_64", "windows-x86_64"})
        for computer, items in packages.items():
            names = {str(item["url"]).rsplit("/", 1)[-1].rsplit("-", 2)[0] for item in items}
            for needed in ("pango", "libpango", "poppler", "libharfbuzz", "fontconfig", "fribidi", "libglib"):
                self.assertIn(needed, names, computer)
            self.assertFalse(names & {"python", "tk"}, computer)
            self.assertLess(sum(int(item["size"]) for item in items), 80 * 1024 * 1024, computer)


class WorksOnWindows(unittest.TestCase):
    """Windows differs from a Mac in ways that stopped real work. Each is pinned here."""

    def product_files(self):
        # Tests and evals count too: a test that reads text the Mac way fails on
        # Windows and hides whether the product works there.
        for base in ("skills", "tools", "scaffold", "tests", "evals"):
            yield from (ROOT / base).rglob("*.py")

    def test_every_text_file_is_read_and_written_as_utf8(self):
        # Windows reads and writes text in an older encoding unless told otherwise,
        # and a psalm or a curly quote then stops the work with an encoding error.
        import ast
        offenders = []
        for path in self.product_files():
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                keywords = {keyword.arg for keyword in node.keywords}
                if "encoding" in keywords or None in keywords:
                    continue
                name = node.func.attr
                if (name == "read_text" and not node.args) or (name == "write_text" and len(node.args) == 1):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}")
            for number, line in enumerate(source.splitlines(), start=1):
                if path == Path(__file__).resolve():
                    break  # this file names the pattern it looks for
                if "text=True" in line and "mkstemp" not in line and "encoding=" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number} text=True")
        self.assertEqual(offenders, [], "name the encoding: encoding=\"utf-8\"")

    def test_dates_do_not_use_a_format_windows_lacks(self):
        offenders = [path.relative_to(ROOT).as_posix() for path in self.product_files()
                     if re.search(r"strftime\([^)]*%-", path.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [], "\"%-d\" fails on Windows; build the date from its parts")

    def test_shipped_worship_text_is_still_recognized_after_git_rewrites_line_endings(self):
        import hashlib
        import json
        from skills.bulletin import sunday_library
        manifest = json.loads((ROOT / "skills/bulletin/resources/bcp1979/manifest.json").read_text(encoding="utf-8"))
        identifier, entry = next(iter(manifest["liturgy"].items()))
        original = (ROOT / "skills/bulletin/renderer/liturgy" / f"{identifier}.md").read_bytes()
        self.assertNotIn(b"\r\n", original)
        with tempfile.TemporaryDirectory() as temp:
            rewritten = Path(temp) / "text.md"
            rewritten.write_bytes(original.replace(b"\n", b"\r\n"))
            self.assertNotEqual(hashlib.sha256(rewritten.read_bytes()).hexdigest(), entry["sha256"])
            self.assertTrue(sunday_library._matches_release(rewritten, entry["sha256"]))
            rewritten.write_bytes(original.replace(b"\n", b"\r\n") + b"An added line.\r\n")
            self.assertFalse(sunday_library._matches_release(rewritten, entry["sha256"]), "changed words must still be refused")

    def test_handbuilts_folder_on_windows_is_short(self):
        """Setup failed with 'path too long' because the Claude app redirects AppData to a deep folder."""
        from pathlib import PureWindowsPath
        from tools.handbuilt_runtime import default_runtime_root
        # Built from parts so this invented path is not mistaken for a real person's folder.
        profile = "C:\\" + "\\".join(("Users", "example"))
        deep = profile + "\\" + "\\".join(("AppData", "Local", "Packages", "Claude_abcdefghijklm", "LocalCache", "Local"))
        root = default_runtime_root(system="Windows", home=Path(profile.replace("\\", "/")),
                                    environ={"USERPROFILE": profile, "LOCALAPPDATA": deep})
        parts = PureWindowsPath(str(root).replace("/", "\\")).parts
        self.assertEqual(parts[-2:], (".handbuilt", "runtime"))
        self.assertNotIn("Packages", parts)
        self.assertNotIn("AppData", parts)

    def test_file_addresses_are_turned_into_paths_the_windows_way(self):
        """Every bulletin on Windows was refused: its fonts 'could not be found'."""
        offenders = []
        for path in self.product_files():
            if path == Path(__file__).resolve():
                continue  # this file names the pattern it looks for
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                # urlparse("file:///C:/x").path is "/C:/x", which is not a Windows path.
                if re.search(r"Path\(unquote\(urlparse\(", line) or "[7:]" in line and "file://" in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(offenders, [], "use urllib.request.url2pathname for file addresses")
        from skills.bulletin.renderer import print_layout
        with tempfile.TemporaryDirectory() as temp:
            font = Path(temp).resolve() / "a font.ttf"
            font.write_bytes(b"x")
            html = f'<style>@font-face {{ src: url("{font.as_uri()}"); }}</style>'
            self.assertEqual(print_layout.missing_assets(html), [])
            (Path(temp) / "picture.png").write_bytes(b"x")
            self.assertEqual(print_layout.missing_assets('<img src="picture.png">', base_url=Path(temp).resolve().as_uri()), [])
            self.assertEqual(len(print_layout.missing_assets('<img src="gone.png">', base_url=Path(temp).resolve().as_uri())), 1)

    def test_recorded_paths_use_forward_slashes(self):
        # A church folder may be opened on a Mac and on Windows. A path saved in a
        # receipt as "brand\\guide.pdf" on one does not match on the other.
        import ast
        offenders = []
        for base in ("skills", "tools", "scaffold", "evals", "tests"):
            for path in (ROOT / base).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str"
                            and len(node.args) == 1 and isinstance(node.args[0], ast.Call)
                            and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == "relative_to"):
                        offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
        self.assertEqual(offenders, [], "write it as path.relative_to(root).as_posix()")

    def test_both_launchers_start_python_in_utf8_mode(self):
        self.assertIn('exec "$py" -X utf8 "$@"', SHELL_LAUNCHER.read_text(encoding="utf-8"))
        self.assertIn('"%PY%" -X utf8 %*', WINDOWS_LAUNCHER.read_text(encoding="utf-8"))


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
