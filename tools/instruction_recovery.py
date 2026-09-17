"""Bounded, local recovery snapshots for a church's instruction files.

Only ``CLAUDE.md`` and ``AGENTS.md`` in a church folder are in scope.  The
module deliberately records observed file state; it does not infer who made a
change and it never repairs a file without an explicit restore request.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Any

from tools.workflow_updates import file_lock


INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")
MAX_FILE_BYTES = 1024 * 1024
MAX_REASON_CHARS = 512
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
SNAPSHOT_ID_RE = re.compile(r"[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SCHEMA_VERSION = 1


def _failure(message: str) -> ValueError:
    return ValueError("Instruction recovery: " + message)


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _assert_no_symlink_path(path: Path, *, allow_missing_leaf: bool = False) -> None:
    """Reject a symlink at a controlled recovery path.

    System paths can legitimately contain an ancestor symlink, such as macOS
    ``/var``.  Each recovery path is built only by appending a fixed child to
    the already checked church root, so inspecting its own inode is the useful
    protection here.
    """
    absolute = _absolute(path)
    try:
        item = os.lstat(absolute)
    except FileNotFoundError:
        if allow_missing_leaf:
            return
        raise _failure(f"missing required path {absolute}.")
    except OSError as exc:
        raise _failure(f"cannot inspect {absolute}: {exc}") from exc
    if stat.S_ISLNK(item.st_mode):
        raise _failure(f"refusing symlinked path {absolute}.")


def _lstat(path: Path, *, missing_ok: bool = False) -> os.stat_result | None:
    _assert_no_symlink_path(path, allow_missing_leaf=missing_ok)
    try:
        return os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise _failure(f"missing required path {path}.")
    except OSError as exc:
        raise _failure(f"cannot inspect {path}: {exc}") from exc


def _private_mode(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError as exc:
        if os.name != "nt":
            raise _failure(f"cannot protect recovery store path {path}: {exc}") from exc


def _private_fd_mode(descriptor: int, mode: int) -> None:
    try:
        os.fchmod(descriptor, mode)
    except (AttributeError, OSError) as exc:
        if os.name != "nt":
            raise _failure(f"cannot protect recovery store file: {exc}") from exc


def _church_path(church: Path | str) -> Path:
    root = _absolute(church)
    item = _lstat(root)
    if not stat.S_ISDIR(item.st_mode):
        raise _failure("the church folder must be a real directory.")
    return root


def _safe_store_directory(path: Path, *, create: bool, private: bool = True) -> bool:
    """Validate one recovery-store directory, creating it owner-only if asked.

    Returns false only when the directory is absent and callers requested a
    read-only operation.
    """
    item = _lstat(path, missing_ok=True)
    if item is None:
        if not create:
            return False
        try:
            os.mkdir(path, 0o700)
            _private_mode(path, 0o700)
        except FileExistsError:
            # Another cooperating starter may have created the directory
            # before either process acquired the store lock. Revalidate it.
            pass
        except OSError as exc:
            raise _failure(f"cannot create private recovery directory {path}: {exc}") from exc
        item = _lstat(path)
    if not stat.S_ISDIR(item.st_mode):
        raise _failure(f"recovery store path {path} is not a directory.")
    if os.name != "nt" and item.st_uid != os.getuid():
        raise _failure(f"recovery store path {path} is not owned by this user.")
    if os.name != "nt" and item.st_mode & 0o022:
        raise _failure(f"recovery store path {path} is writable by another user.")
    if os.name != "nt" and private and item.st_mode & 0o077:
        raise _failure(f"recovery store path {path} is accessible by another user.")
    return True


def _store_paths(church: Path | str, *, create: bool) -> tuple[Path, Path] | tuple[None, None]:
    root = _church_path(church)
    handbuilt = root / ".handbuilt"
    recovery = handbuilt / "recovery"
    snapshots = recovery / "snapshots"
    for directory, private in ((handbuilt, False), (recovery, True), (snapshots, True)):
        if not _safe_store_directory(directory, create=create, private=private):
            return None, None
    return recovery, snapshots


def _safe_store_file(path: Path, *, missing_ok: bool = False) -> os.stat_result | None:
    item = _lstat(path, missing_ok=missing_ok)
    if item is None:
        return None
    if not stat.S_ISREG(item.st_mode):
        raise _failure(f"recovery store file {path} is not a regular file.")
    if os.name != "nt" and item.st_uid != os.getuid():
        raise _failure(f"recovery store file {path} is not owned by this user.")
    if os.name != "nt" and item.st_mode & 0o077:
        raise _failure(f"recovery store file {path} is accessible by another user.")
    return item


def _lock_path(store: Path) -> Path:
    lock = store / "recovery.lock"
    existing = _safe_store_file(lock, missing_ok=True)
    if existing is None:
        # file_lock opens with the platform default permissions, so establish
        # the private inode before asking it to lock.
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            _private_mode(lock, 0o600)
        except FileExistsError:
            _safe_store_file(lock)
        except OSError as exc:
            raise _failure(f"cannot prepare recovery lock: {exc}") from exc
    return lock


@contextmanager
def _recovery_lock(store: Path):
    lock = _lock_path(store)
    with file_lock(lock) as acquired:
        if not acquired:
            raise _failure("another recovery operation is in progress; try again.")
        yield


def _target_path(church: Path, name: str) -> Path:
    if name not in INSTRUCTION_FILES:
        raise _failure("only CLAUDE.md and AGENTS.md can be recovered.")
    return church / name


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    try:
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
    except OSError as exc:
        raise _failure(f"cannot read {label}: {exc}") from exc
    if len(content) > limit:
        raise _failure(f"{label} exceeds its size limit.")
    return content


def _observe_target(church: Path, name: str) -> dict[str, Any]:
    path = _target_path(church, name)
    item = _lstat(path, missing_ok=True)
    if item is None:
        return {"presence": "missing", "sha256": None, "mode": None}
    if not stat.S_ISREG(item.st_mode):
        raise _failure(f"{name} is not a regular file.")
    if item.st_size > MAX_FILE_BYTES:
        raise _failure(f"{name} exceeds the 1 MiB recovery limit.")
    content = _read_bounded(path, MAX_FILE_BYTES, name)
    if len(content) > MAX_FILE_BYTES:
        raise _failure(f"{name} exceeds the 1 MiB recovery limit.")
    return {
        "presence": "present",
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": stat.S_IMODE(item.st_mode),
        "content_b64": base64.b64encode(content).decode("ascii"),
    }


def _observed_files(church: Path) -> dict[str, dict[str, Any]]:
    return {name: _observe_target(church, name) for name in INSTRUCTION_FILES}


def _public_file_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in ("presence", "sha256", "mode")}


def _public_files(files: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: _public_file_metadata(files[name]) for name in INSTRUCTION_FILES}


def _snapshot_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return stamp + "-" + secrets.token_hex(8)


def _validate_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_CHARS:
        raise _failure(f"observation reason must be 1 to {MAX_REASON_CHARS} characters.")
    return reason


def _snapshot_path(snapshots: Path, snapshot_id: str) -> Path:
    if not isinstance(snapshot_id, str) or not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise _failure("invalid snapshot identifier.")
    return snapshots / (snapshot_id + ".json")


def _decode_record(name: str, record: Any) -> tuple[dict[str, Any], bytes | None]:
    if not isinstance(record, dict):
        raise _failure(f"snapshot record for {name} is invalid.")
    presence = record.get("presence")
    if presence == "missing":
        if set(record) != {"presence", "sha256", "mode"} or record["sha256"] is not None or record["mode"] is not None:
            raise _failure(f"snapshot missing record for {name} is invalid.")
        return {"presence": "missing", "sha256": None, "mode": None}, None
    if presence != "present" or set(record) != {"presence", "sha256", "mode", "content_b64"}:
        raise _failure(f"snapshot record for {name} is invalid.")
    digest = record.get("sha256")
    mode = record.get("mode")
    encoded = record.get("content_b64")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise _failure(f"snapshot hash for {name} is invalid.")
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o777:
        raise _failure(f"snapshot mode for {name} is invalid.")
    if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4 + 4:
        raise _failure(f"snapshot data for {name} is invalid.")
    try:
        content = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise _failure(f"snapshot data for {name} is not valid base64.") from exc
    if len(content) > MAX_FILE_BYTES or hashlib.sha256(content).hexdigest() != digest:
        raise _failure(f"snapshot data for {name} failed its hash check.")
    return {"presence": "present", "sha256": digest, "mode": mode, "content_b64": encoded}, content


def _read_snapshot(snapshots: Path, snapshot_id: str) -> tuple[dict[str, Any], dict[str, bytes | None]]:
    path = _snapshot_path(snapshots, snapshot_id)
    item = _safe_store_file(path, missing_ok=True)
    if item is None:
        raise _failure("requested snapshot does not exist.")
    if item.st_size > MAX_SNAPSHOT_BYTES:
        raise _failure("snapshot exceeds its size limit.")
    try:
        payload = json.loads(_read_bounded(path, MAX_SNAPSHOT_BYTES, "snapshot").decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _failure("snapshot JSON is corrupt.") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "snapshot_id", "created_at", "reason", "files"}:
        raise _failure("snapshot structure is invalid.")
    if payload["schema_version"] != _SCHEMA_VERSION or payload["snapshot_id"] != snapshot_id:
        raise _failure("snapshot identity is invalid.")
    if not isinstance(payload["created_at"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+\-]+Z", payload["created_at"]):
        raise _failure("snapshot timestamp is invalid.")
    _validate_reason(payload["reason"])
    if not isinstance(payload["files"], dict) or set(payload["files"]) != set(INSTRUCTION_FILES):
        raise _failure("snapshot file set is invalid.")
    files: dict[str, dict[str, Any]] = {}
    contents: dict[str, bytes | None] = {}
    for name in INSTRUCTION_FILES:
        files[name], contents[name] = _decode_record(name, payload["files"][name])
    return dict(payload, files=files), contents


def _snapshot_ids(snapshots: Path) -> list[str]:
    try:
        entries = list(snapshots.iterdir())
    except OSError as exc:
        raise _failure(f"cannot list recovery snapshots: {exc}") from exc
    ids: list[str] = []
    for entry in entries:
        if entry.name.startswith(".snapshot-"):
            _safe_store_file(entry)
            continue
        if entry.name == ".keep":
            continue
        if not entry.name.endswith(".json"):
            raise _failure(f"unexpected recovery store entry {entry.name}.")
        snapshot_id = entry.name[:-5]
        _snapshot_path(snapshots, snapshot_id)
        _safe_store_file(entry)
        ids.append(snapshot_id)
    return sorted(ids, reverse=True)


def _same_state(left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]]) -> bool:
    return all(_public_file_metadata(left[name]) == _public_file_metadata(right[name]) for name in INSTRUCTION_FILES)


def _write_snapshot(snapshots: Path, payload: dict[str, Any]) -> None:
    destination = _snapshot_path(snapshots, payload["snapshot_id"])
    if _safe_store_file(destination, missing_ok=True) is not None:
        raise _failure("snapshot identifier collision; try again.")
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise _failure("snapshot exceeds its size limit.")
    descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=snapshots)
    temporary_path = Path(temporary)
    try:
        _private_fd_mode(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # hard-link creation is an atomic no-replace publication on local file systems.
        os.link(temporary_path, destination)
    except FileExistsError as exc:
        raise _failure("snapshot identifier collision; try again.") from exc
    except OSError as exc:
        raise _failure(f"cannot save recovery snapshot: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    _safe_store_file(destination)


def _snapshot_locked(church: Path, snapshots: Path, reason: str) -> dict[str, Any]:
    files = _observed_files(church)
    ids = _snapshot_ids(snapshots)
    if ids:
        latest, _ = _read_snapshot(snapshots, ids[0])
        if _same_state(files, latest["files"]):
            return {"status": "ok", "snapshot_id": ids[0], "files": _public_files(files), "created": False}
    for _ in range(4):
        snapshot_id = _snapshot_id()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "reason": reason,
            "files": files,
        }
        try:
            _write_snapshot(snapshots, payload)
            return {"status": "ok", "snapshot_id": snapshot_id, "files": _public_files(files), "created": True}
        except ValueError as exc:
            if "identifier collision" not in str(exc):
                raise
    raise _failure("could not reserve a unique snapshot identifier.")


def snapshot(church: Path, reason: str) -> dict[str, Any]:
    """Record both in-scope instruction files, including an observed absence."""
    reason = _validate_reason(reason)
    root = _church_path(church)
    store, snapshots = _store_paths(root, create=True)
    assert store is not None and snapshots is not None
    with _recovery_lock(store):
        return _snapshot_locked(root, snapshots, reason)


def list_snapshots(church: Path) -> dict[str, Any]:
    """Read bounded snapshot metadata only.  This function never creates files."""
    root = _church_path(church)
    store, snapshots = _store_paths(root, create=False)
    current = _public_files(_observed_files(root))
    if store is None or snapshots is None:
        return {"status": "empty", "snapshots": [], "current": current}
    result = []
    for snapshot_id in _snapshot_ids(snapshots):
        payload, _ = _read_snapshot(snapshots, snapshot_id)
        result.append({
            "snapshot_id": payload["snapshot_id"],
            "created_at": payload["created_at"],
            "reason": payload["reason"],
            "files": _public_files(payload["files"]),
        })
    return {"status": "ok", "snapshots": result, "current": current}


def show_snapshot(church: Path, snapshot_id: str, file: str) -> dict[str, Any]:
    """Return one selected saved instruction as UTF-8 text for human review."""
    root = _church_path(church)
    _target_path(root, file)
    _, snapshots = _store_paths(root, create=False)
    if snapshots is None:
        raise _failure("no recovery store exists for this church.")
    payload, contents = _read_snapshot(snapshots, snapshot_id)
    record = payload["files"][file]
    content = contents[file]
    if content is None:
        return {"status": "missing", "snapshot_id": snapshot_id, "file": file,
                **_public_file_metadata(record), "text": None}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _failure(f"saved {file} is not UTF-8 text and cannot be shown safely.") from exc
    return {"status": "ok", "snapshot_id": snapshot_id, "file": file,
            **_public_file_metadata(record), "text": text}


def _current_token(record: dict[str, Any]) -> str:
    return "missing" if record["presence"] == "missing" else record["sha256"]


def _validate_expected(expected_sha256: str) -> None:
    if expected_sha256 != "missing" and (not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256)):
        raise _failure("expected_sha256 must be a current SHA-256 or 'missing'.")


def _atomic_restore(church: Path, file: str, content: bytes, mode: int | None,
                    expected_sha256: str) -> None:
    path = _target_path(church, file)
    _assert_no_symlink_path(path, allow_missing_leaf=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".instruction-recovery-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        _private_fd_mode(descriptor, 0o600 if mode is None else mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck after staging and immediately before replacement. os.replace
        # replaces a destination symlink itself, rather than following it.
        _assert_no_symlink_path(path, allow_missing_leaf=True)
        if _current_token(_observe_target(church, file)) != expected_sha256:
            raise _failure(f"{file} changed during recovery; no restore was written.")
        os.replace(temporary_path, path)
    except OSError as exc:
        raise _failure(f"cannot restore {path.name}: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def restore(church: Path, snapshot_id: str, file: str, expected_sha256: str) -> dict[str, Any]:
    """Restore one present historical instruction after an exact current-state check."""
    _validate_expected(expected_sha256)
    root = _church_path(church)
    _target_path(root, file)
    store, snapshots = _store_paths(root, create=False)
    if store is None or snapshots is None:
        raise _failure("no recovery store exists for this church.")
    with _recovery_lock(store):
        payload, contents = _read_snapshot(snapshots, snapshot_id)
        selected = payload["files"][file]
        content = contents[file]
        if content is None:
            raise _failure("a missing historical instruction cannot be restored as a deletion.")
        current = _observe_target(root, file)
        if _current_token(current) != expected_sha256:
            raise _failure(f"{file} changed since review; its current state does not match expected_sha256.")
        backup = _snapshot_locked(root, snapshots, "before restoring " + file + " from " + snapshot_id)
        _atomic_restore(root, file, content, selected["mode"], expected_sha256)
        restored = _observe_target(root, file)
        if restored["sha256"] != selected["sha256"]:
            raise _failure(f"{file} did not match its selected snapshot after restore.")
        after_files = _public_files(_observed_files(root))
    return {
        "status": "restored",
        "snapshot_id": snapshot_id,
        "file": file,
        "files": after_files,
        "backup": backup,
        "restored_sha256": restored["sha256"],
        "external_edit_limit": (
            "The lock coordinates Handbuilt recovery operations. An editor that ignores it "
            "can still edit immediately after the final check."
        ),
    }
