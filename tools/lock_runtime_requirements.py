"""Explicit maintainer tool to build the runtime lock from PyPI wheel metadata.

This script only reads PyPI JSON metadata and writes the requested lock file.
It never downloads, unpacks, imports, or installs a package artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from tools import runtime_lock, runtime_security


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WHEEL_RE = re.compile(r"\.whl$")
_NAME_RE = re.compile(r"[-_.]+")
MAX_METADATA_BYTES = 4 * 1024 * 1024


def _normalize_project_name(name: str) -> str:
    return _NAME_RE.sub("-", name).lower()


class LockGenerationError(ValueError):
    """Raised when official PyPI metadata cannot produce a safe wheel lock."""


def fetch_release_metadata(name: str, version: str) -> dict[str, object]:
    """Fetch a pinned release's public JSON metadata from PyPI."""
    security_error = runtime_security.python_security_error(sys.version_info)
    if security_error:
        raise LockGenerationError("Use a security-patched Python before reading package metadata: " + security_error)
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "handbuilt-runtime-lock/1"})
    try:
        with urlopen(request, timeout=30) as response:
            if response.geturl() != url:
                raise LockGenerationError("PyPI metadata redirected away from the requested release URL.")
            raw = response.read(MAX_METADATA_BYTES + 1)
            if len(raw) > MAX_METADATA_BYTES:
                raise LockGenerationError("PyPI release metadata exceeds the size limit.")
            data = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LockGenerationError(f"Could not read official PyPI metadata for {name}=={version}.") from error
    if not isinstance(data, dict):
        raise LockGenerationError(f"PyPI metadata for {name}=={version} is malformed.")
    return data


def wheel_hashes(name: str, version: str, metadata: dict[str, object]) -> tuple[str, ...]:
    """Return deduplicated hashes for wheel files in exact PyPI release JSON."""
    info = metadata.get("info")
    if not isinstance(info, dict):
        raise LockGenerationError(f"PyPI metadata for {name}=={version} has no release info.")
    actual_version = info.get("version")
    if actual_version != version:
        raise LockGenerationError(f"PyPI returned the wrong version for {name}=={version}.")
    actual_name = info.get("name")
    if (
        not isinstance(actual_name, str)
        or _normalize_project_name(actual_name) != _normalize_project_name(name)
    ):
        raise LockGenerationError(f"PyPI returned the wrong project for {name}=={version}.")
    files = metadata.get("urls")
    if not isinstance(files, list):
        raise LockGenerationError(f"PyPI metadata for {name}=={version} has no file list.")

    hashes: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise LockGenerationError(f"PyPI metadata for {name}=={version} has an invalid file record.")
        filename = item.get("filename")
        packagetype = item.get("packagetype")
        if packagetype != "bdist_wheel":
            if isinstance(filename, str) and _WHEEL_RE.search(filename) is not None:
                raise LockGenerationError(f"PyPI file {filename} is mislabeled as a non-wheel artifact.")
            continue
        if not isinstance(filename, str) or _WHEEL_RE.search(filename) is None:
            raise LockGenerationError(f"PyPI wheel record for {name}=={version} has an invalid filename.")
        basename = filename[:-4]
        wheel_parts = basename.split("-")
        if (
            len(wheel_parts) < 5
            or _normalize_project_name(wheel_parts[0]) != _normalize_project_name(name)
            or wheel_parts[1] != version
        ):
            raise LockGenerationError(f"PyPI wheel filename {filename} does not match {name}=={version}.")
        if item.get("yanked") is not False:
            raise LockGenerationError(f"PyPI wheel {filename} is yanked or lacks a verified yanked status.")
        file_url = item.get("url")
        try:
            parsed_url = urlsplit(file_url) if isinstance(file_url, str) else None
            parsed_port = parsed_url.port if parsed_url is not None else None
        except ValueError as error:
            raise LockGenerationError(f"PyPI wheel {filename} has a malformed URL.") from error
        if (
            parsed_url is None
            or parsed_url.scheme != "https"
            or parsed_url.hostname != "files.pythonhosted.org"
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_port is not None
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.path.rsplit("/", 1)[-1] != filename
        ):
            raise LockGenerationError(f"PyPI wheel {filename} has an unapproved download URL.")
        digests = item.get("digests")
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise LockGenerationError(f"PyPI wheel {filename} has no valid SHA-256 hash.")
        hashes.add(digest)
    if not hashes:
        raise LockGenerationError(
            f"PyPI has no wheel artifacts for {name}=={version}; source builds are not allowed."
        )
    return tuple(sorted(hashes))


def render_lock(requirements_text: str, fetcher=fetch_release_metadata) -> str:
    """Build lock text using only wheel hashes from exact PyPI release JSON."""
    pins = runtime_lock.parse_requirement_pins(requirements_text)
    rendered = [
        "# Generated from exact-version PyPI JSON metadata by python -m tools.lock_runtime_requirements.",
        "# Contains wheel SHA-256 hashes only; source distributions are excluded.",
    ]
    for name in sorted(pins):
        pin = pins[name]
        metadata = fetcher(name, pin.version)
        hashes = wheel_hashes(name, pin.version, metadata)
        if name == "pip":
            official_url = runtime_security.PIP_WHEEL_URL
            pip_files = metadata.get("urls", [])
            matching = [
                item for item in pip_files
                if isinstance(item, dict)
                and item.get("filename") == official_url.rsplit("/", 1)[-1]
                and item.get("url") == official_url
                and isinstance(item.get("digests"), dict)
                and item["digests"].get("sha256") == runtime_security.PIP_WHEEL_SHA256
            ]
            if pin.version != runtime_security.PIP_VERSION or len(matching) != 1:
                raise LockGenerationError("The pip wheel does not match the trusted bootstrap artifact.")
            if hashes != (runtime_security.PIP_WHEEL_SHA256,):
                raise LockGenerationError("pip release metadata includes unexpected wheel artifacts.")
        extras = f"[{','.join(pin.extras)}]" if pin.extras else ""
        requirement = f"{pin.name}{extras}=={pin.version}"
        rendered.append(requirement + " \\")
        for index, digest in enumerate(hashes):
            continuation = " \\" if index + 1 < len(hashes) else ""
            rendered.append(f"    --hash=sha256:{digest}{continuation}")
    lock_text = "\n".join(rendered) + "\n"
    runtime_lock.validate_lock_text(requirements_text, lock_text)
    return lock_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=runtime_lock.DEFAULT_REQUIREMENTS_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        security_error = runtime_security.python_security_error(sys.version_info)
        if security_error:
            raise LockGenerationError("Use a security-patched Python before generating the lock: " + security_error)
        text = runtime_lock.read_regular_text_file(
            args.requirements,
            max_bytes=runtime_lock.MAX_REQUIREMENTS_BYTES,
            label="requirements file",
        )
        lock_text = render_lock(text)
        args.output.write_text(lock_text, encoding="utf-8")
    except (OSError, runtime_lock.RuntimeLockError, LockGenerationError) as error:
        print(f"Runtime lock generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
