#!/usr/bin/env python3
"""Build a deterministic, public distribution of the Handbuilt workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Iterable, Optional
import zipfile


PLUGIN_NAME = "handbuilt-church-labs"
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
MANIFESTS = (".codex-plugin/plugin.json", ".claude-plugin/plugin.json")
EXACT_FILES = ("requirements.txt", "LICENSE", "THIRD-PARTY-NOTICES.md", "README.md", "AGENTS.md", "CLAUDE.md", *MANIFESTS)
REQUIRED_FILES = (
    "tools/church_workflow.py",
    "tools/handbuilt_runtime.py",
    "tools/workflow_updates.py",
    "tools/plugin_identity.py",
    "tools/instruction_recovery.py",
    "handbook/instruction-recovery.md",
    "requirements.txt",
    "LICENSE",
    "scaffold/church-folder/handbuilt.py",
    "skills/bulletin/SKILL.md",
    "skills/onboarding/SKILL.md",
    "skills/sermon-research/SKILL.md",
)
PACKAGE_ROOTS = ("skills/", "tools/", "scaffold/", "handbook/")
EXCLUDED_PARTS = {
    "__pycache__",
    ".git",
    "tests",
    "church-data",
    "church_data",
    "private-church-data",
    "private_church_data",
}


class PackageError(ValueError):
    """Raised when the source tree is not a safe package input."""


def _run_git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PackageError(f"Unable to inspect the source repository: {exc}") from exc
    return result.stdout


def _git_files(root: Path) -> list[str]:
    output = _run_git(root, "ls-files", "-z")
    return [item for item in output.split("\0") if item]


def _is_allowed(relative: str) -> bool:
    return relative in EXACT_FILES or relative.startswith(PACKAGE_ROOTS)


def _is_excluded(relative: str) -> bool:
    path = PurePosixPath(relative)
    return any(part in EXCLUDED_PARTS or part.endswith(".pyc") for part in path.parts) or path.suffix == ".pyc"


def _validate_manifest(root: Path, relative: str) -> str:
    path = root / relative
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackageError(f"Invalid plugin manifest {relative}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PackageError(f"Invalid plugin manifest {relative}: expected a JSON object")
    if manifest.get("name") != PLUGIN_NAME:
        raise PackageError(f"Plugin manifest {relative} must name {PLUGIN_NAME!r}")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise PackageError(f"Plugin manifest {relative} must use a strict X.Y.Z version")
    return version


def _reject_symlink_inputs(root: Path, path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            relative = current.relative_to(root).as_posix()
            raise PackageError(f"Symlink inputs are not allowed: {relative}")
        if current == root:
            return
        current = current.parent


def _source_files(root: Path, tracked: Iterable[str]) -> list[tuple[str, Path]]:
    selected: list[tuple[str, Path]] = []
    for relative in tracked:
        if not _is_allowed(relative) or _is_excluded(relative):
            continue
        path = root / relative
        _reject_symlink_inputs(root, path)
        if not path.is_file():
            raise PackageError(f"Tracked package input is missing or not a file: {relative}")
        selected.append((relative, path))
    selected.sort(key=lambda item: item[0])
    return selected


def _zip_entry(name: str, data: bytes) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.flag_bits = 0
    info.extra = b""
    info.comment = b""
    return info


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = handle.name
            handle.write(data)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def build_package(root: Path, output_dir: Path) -> dict:
    """Build the package and return its version, files, and output paths."""
    root = Path(root).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not root.is_dir():
        raise PackageError(f"Source root is not a directory: {root}")
    try:
        git_root = Path(_run_git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    except PackageError:
        raise
    if git_root != root:
        raise PackageError(f"Source root must be the repository root: {root}")
    try:
        output_dir.relative_to(root)
    except ValueError:
        pass
    else:
        raise PackageError("Output directory must be outside the source root")

    tracked = _git_files(root)
    missing_manifests = [relative for relative in MANIFESTS if relative not in tracked]
    if missing_manifests:
        raise PackageError("Required plugin manifests are not tracked: " + ", ".join(missing_manifests))
    versions = [_validate_manifest(root, relative) for relative in MANIFESTS]
    if versions[0] != versions[1]:
        raise PackageError("Plugin manifests must use the same version")
    version = versions[0]
    files = _source_files(root, tracked)
    names = {relative for relative, _ in files}
    missing = [relative for relative in REQUIRED_FILES if relative not in names]
    if missing:
        raise PackageError("Required package inputs are missing: " + ", ".join(missing))

    contents = {relative: path.read_bytes() for relative, path in files}
    file_hashes = {relative: hashlib.sha256(data).hexdigest() for relative, data in contents.items()}
    metadata = {
        "schema_version": 1,
        "version": version,
        "files": file_hashes,
    }
    metadata_bytes = (json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_bytes: bytes
    temporary_archive: Optional[str] = None
    archive_path = output_dir / "handbuilt-workflow.zip"
    try:
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".handbuilt-workflow.", suffix=".zip", delete=False) as handle:
            temporary_archive = handle.name
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, data in contents.items():
                archive.writestr(_zip_entry(relative, data), data)
            archive.writestr(_zip_entry(".handbuilt-workflow.json", metadata_bytes), metadata_bytes)
        archive_bytes = Path(temporary_archive).read_bytes()
        os.replace(temporary_archive, archive_path)
        temporary_archive = None
    finally:
        if temporary_archive:
            try:
                os.unlink(temporary_archive)
            except FileNotFoundError:
                pass

    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    digest_path = output_dir / "handbuilt-workflow.sha256"
    _write_atomic(digest_path, f"{archive_digest}  {archive_path.name}\n".encode("ascii"))
    return {
        "version": version,
        "files": file_hashes,
        "zip": str(archive_path),
        "sha256": str(digest_path),
        "zip_sha256": archive_digest,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic Handbuilt workflow package")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_package(args.root, args.output_dir)
    except PackageError as exc:
        print(f"package failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
