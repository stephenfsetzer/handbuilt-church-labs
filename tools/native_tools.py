"""Install Handbuilt's own PDF tools without an administrator password.

Bulletins, brand guides and reports are made as PDFs. That needs two things
Python packages cannot supply: the Pango text libraries and the Poppler PDF
tools. On a Mac they used to come from Homebrew, which asks for a password, and
on Windows there was no supported way to get them.

This downloads the conda-forge packages listed in tools/native-tools.lock,
checks each one against the SHA-256 recorded there, and unpacks them into a
folder beside Handbuilt's private runtime. It runs nothing from the download,
needs no installer, and changes nothing outside Handbuilt's folder.

Run it with Handbuilt's own Python (bin/handbuilt-python), which can read the
package format:

    handbuilt-python tools/native_tools.py status
    handbuilt-python tools/native_tools.py install
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import ssl
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

READY_MARKER = ".handbuilt-native-ready"
ALLOWED_HOST = "conda.anaconda.org"
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60
LOCK = Path(__file__).with_name("native-tools.lock")


class NativeToolsError(Exception):
    """A plain-language reason the PDF tools could not be installed."""


def computer_key(system: str | None = None, machine: str | None = None) -> str | None:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Windows":
        return "windows-x86_64"  # The x86-64 tools run on ARM Windows too.
    if system == "Darwin":
        return "darwin-aarch64" if machine in {"arm64", "aarch64"} else "darwin-x86_64"
    return None


def read_lock(path: Path = LOCK) -> tuple[str, dict[str, list[dict[str, object]]]]:
    """Return the release name and, for each computer, its packages."""
    release = ""
    packages: dict[str, list[dict[str, object]]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise NativeToolsError("The plugin is missing tools/native-tools.lock.") from error
    for line in lines:
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "release" and len(parts) == 2:
            release = parts[1]
            continue
        if len(parts) != 4:
            raise NativeToolsError("tools/native-tools.lock has a line that cannot be read.")
        computer, sha256, size, url = parts
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256) or not size.isdigit():
            raise NativeToolsError("tools/native-tools.lock has an invalid checksum or size.")
        if not _approved(url) or not url.endswith((".conda", ".tar.bz2")):
            raise NativeToolsError("tools/native-tools.lock names a package outside the approved source.")
        packages.setdefault(computer, []).append({"sha256": sha256, "size": int(size), "url": url})
    if not release or not release.replace("-", "").isalnum():
        raise NativeToolsError("tools/native-tools.lock does not name its release.")
    return release, packages


def _approved(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == ALLOWED_HOST
            and parsed.username is None and parsed.password is None and parsed.port in (None, 443))


class _SameHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not _approved(newurl):
            raise NativeToolsError("A download was redirected away from the approved source.")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download(url: str, limit: int) -> bytes:
    opener = urllib.request.build_opener(
        _SameHost, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers={"User-Agent": "Handbuilt-Runtime-Setup"})
    last: Exception | None = None
    for _attempt in range(3):
        try:
            with opener.open(request, timeout=DOWNLOAD_TIMEOUT) as response:
                if not _approved(response.geturl()):
                    raise NativeToolsError("A download ended outside the approved source.")
                data = response.read(limit + 1)
            if len(data) > limit:
                raise NativeToolsError("A download was larger than its recorded size.")
            return data
        except NativeToolsError:
            raise
        except (OSError, ValueError) as error:  # URLError and timeouts are OSError
            last = error
    raise NativeToolsError(f"A download failed. Check the internet connection and try again. ({last})")


def unpack(package: bytes, target: Path, budget: list[int], *, older_format: bool = False) -> None:
    """Unpack the files of one conda package into target. Runs nothing."""
    try:
        if older_format:  # a .tar.bz2 package: one archive, with its notes under info/
            inner, mode = package, "r:bz2"
        else:  # a .conda package: a zip holding the files as pkg-*.tar.zst
            with zipfile.ZipFile(io.BytesIO(package)) as outer:
                names = [name for name in outer.namelist() if name.startswith("pkg-") and name.endswith(".tar.zst")]
                if len(names) != 1:
                    raise NativeToolsError("A package did not have the expected contents.")
                inner, mode = outer.read(names[0]), "r:zst"
        with tarfile.open(fileobj=io.BytesIO(inner), mode=mode) as archive:
            for member in archive:
                if older_format and (member.name == "info" or member.name.startswith("info/")):
                    continue
                budget[0] -= max(member.size, 0)
                if budget[0] < 0:
                    raise NativeToolsError("The PDF tools unpack to more than their size limit.")
                # The "data" filter refuses absolute paths, paths that leave the
                # folder, device files, and links that point outside it.
                archive.extract(member, target, filter="data")
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as error:
        raise NativeToolsError(f"A package could not be unpacked: {error}") from error


def native_home(runtime_root: Path) -> Path:
    return runtime_root / "native"


def installed(runtime_root: Path, release: str) -> Path | None:
    folder = native_home(runtime_root) / release
    return folder if (folder / READY_MARKER).is_file() else None


def status(runtime_root: Path, *, lock: Path = LOCK) -> dict[str, object]:
    release, packages = read_lock(lock)
    key = computer_key()
    folder = installed(runtime_root, release)
    return {
        "release": release,
        "computer": key,
        "supported": bool(key and packages.get(key)),
        "installed": folder is not None,
        "folder": str(folder or native_home(runtime_root) / release),
        "download_megabytes": round(sum(int(p["size"]) for p in packages.get(key or "", [])) / 1e6),
    }


def install(runtime_root: Path, *, lock: Path = LOCK, fetch=download) -> dict[str, object]:
    if sys.version_info < (3, 14):
        raise NativeToolsError("Run this with Handbuilt's own Python: bin/handbuilt-python tools/native_tools.py install")
    release, packages = read_lock(lock)
    key = computer_key()
    wanted = packages.get(key or "")
    if not wanted:
        raise NativeToolsError("Handbuilt has no PDF tools for this kind of computer.")
    existing = installed(runtime_root, release)
    if existing:
        return {**status(runtime_root, lock=lock), "changed": False}
    home = native_home(runtime_root)
    if home.is_symlink():
        raise NativeToolsError("Handbuilt's PDF tools folder must not be a link.")
    home.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".tmp-", dir=home))
    try:
        budget = [MAX_UNPACKED_BYTES]
        for number, package in enumerate(wanted, start=1):
            name = str(package["url"]).rsplit("/", 1)[-1]
            print(f"Handbuilt PDF tools: {number} of {len(wanted)} ({name})", file=sys.stderr, flush=True)
            data = fetch(str(package["url"]), min(int(package["size"]), MAX_PACKAGE_BYTES))
            if hashlib.sha256(data).hexdigest() != package["sha256"]:
                raise NativeToolsError(f"{name} did not match its recorded checksum, so nothing was installed.")
            unpack(data, work, budget, older_format=name.endswith(".tar.bz2"))
        (work / READY_MARKER).write_text(json.dumps({"release": release, "computer": key}) + "\n", encoding="utf-8")
        final = home / release
        if final.exists():
            shutil.rmtree(final)  # an unfinished earlier attempt; it has no ready marker
        os.replace(work, final)
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
    return {**status(runtime_root, lock=lock), "changed": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Handbuilt's own PDF tools.")
    parser.add_argument("command", choices=("status", "install"))
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args(argv)
    root = args.runtime_root
    if root is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tools.handbuilt_runtime import default_runtime_root
        root = default_runtime_root()
    try:
        result = status(root) if args.command == "status" else install(root)
    except NativeToolsError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
