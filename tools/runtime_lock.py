"""Offline validation for the managed Python runtime's wheel lock."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from tools import runtime_security


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS_PATH = REPOSITORY_ROOT / "requirements.txt"
DEFAULT_LOCK_PATH = REPOSITORY_ROOT / "requirements.lock"
MAX_REQUIREMENTS_BYTES = 64 * 1024
MAX_LOCK_BYTES = 1024 * 1024

_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[A-Za-z0-9._,-]+)\])?"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)
_HASH_RE = re.compile(r"^--hash=sha256:(?P<digest>[0-9a-f]{64})$")
_NAME_RE = re.compile(r"[-_.]+")


class RuntimeLockError(ValueError):
    """Raised when the checked-in runtime lock cannot be trusted."""


def read_regular_text_file(path: Path | str, *, max_bytes: int, label: str) -> str:
    """Read bounded UTF-8 from a regular, non-symlink file only."""
    file_path = Path(path)
    descriptor = None
    try:
        initial = file_path.lstat()
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > max_bytes:
            raise RuntimeLockError(f"The managed runtime {label} is not a bounded regular file.")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(file_path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            opened = os.fstat(stream.fileno())
            current = file_path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise RuntimeLockError(f"The managed runtime {label} changed while being opened.")
            raw = stream.read(max_bytes + 1)
    except RuntimeLockError:
        raise
    except OSError as error:
        raise RuntimeLockError(f"The managed runtime {label} is missing or unreadable.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if len(raw) > max_bytes:
        raise RuntimeLockError(f"The managed runtime {label} exceeds its size limit.")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RuntimeLockError(f"The managed runtime {label} is not valid UTF-8.") from error


@dataclass(frozen=True)
class RequirementPin:
    name: str
    version: str
    extras: tuple[str, ...]


def _normalize_name(name: str) -> str:
    return _NAME_RE.sub("-", name).lower()


def _normalize_extras(extras: str | None) -> tuple[str, ...]:
    if extras is None:
        return ()
    values = tuple(sorted({_normalize_name(value) for value in extras.split(",")}))
    if not values or any(not value for value in values):
        raise RuntimeLockError("Requirement extras are malformed.")
    return values


def parse_requirement_pins(text: str) -> dict[str, RequirementPin]:
    """Parse a deliberately small exact-pin requirements format."""
    pins: dict[str, RequirementPin] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise RuntimeLockError(
                f"requirements.txt line {line_number} is not an exact package pin."
            )
        name = _normalize_name(match.group("name"))
        if name in pins:
            raise RuntimeLockError(f"requirements.txt contains duplicate package {name}.")
        pins[name] = RequirementPin(
            name=name,
            version=match.group("version"),
            extras=_normalize_extras(match.group("extras")),
        )
    if not pins:
        raise RuntimeLockError("requirements.txt contains no package pins.")
    return pins


def _logical_lock_lines(text: str):
    pending: list[str] = []
    start_line = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or (line.startswith("#") and not pending):
            continue
        if not pending:
            start_line = line_number
        if line.endswith("\\"):
            pending.append(line[:-1].strip())
            continue
        if pending:
            pending.append(line)
            yield start_line, " ".join(pending)
            pending.clear()
        else:
            yield line_number, line
    if pending:
        raise RuntimeLockError(f"requirements.lock line {start_line} has an incomplete continuation.")


def parse_lock_pins(text: str) -> tuple[dict[str, RequirementPin], dict[str, frozenset[str]]]:
    """Parse package pins and SHA-256 wheel hashes from a lock file."""
    pins: dict[str, RequirementPin] = {}
    hashes_by_name: dict[str, frozenset[str]] = {}
    for line_number, line in _logical_lock_lines(text):
        parts = line.split()
        package_part = parts[0]
        match = _REQUIREMENT_RE.fullmatch(package_part)
        if match is None:
            raise RuntimeLockError(f"requirements.lock line {line_number} has an invalid pin.")
        name = _normalize_name(match.group("name"))
        if name in pins:
            raise RuntimeLockError(f"requirements.lock contains duplicate package {name}.")

        digests: set[str] = set()
        for token in parts[1:]:
            hash_match = _HASH_RE.fullmatch(token)
            if hash_match is None:
                raise RuntimeLockError(
                    f"requirements.lock line {line_number} contains an unsupported option or hash."
                )
            digest = hash_match.group("digest")
            if digest in digests:
                raise RuntimeLockError(
                    f"requirements.lock line {line_number} repeats a wheel hash."
                )
            digests.add(digest)
        if not digests:
            raise RuntimeLockError(
                f"requirements.lock line {line_number} has no wheel hashes."
            )

        pins[name] = RequirementPin(
            name=name,
            version=match.group("version"),
            extras=_normalize_extras(match.group("extras")),
        )
        hashes_by_name[name] = frozenset(digests)
    if not pins:
        raise RuntimeLockError("requirements.lock contains no package pins.")
    return pins, hashes_by_name


def validate_lock_text(requirements_text: str, lock_text: str) -> None:
    """Validate lock structure, pin parity, hashes, and bootstrap pip identity."""
    requirements = parse_requirement_pins(requirements_text)
    locked, hashes_by_name = parse_lock_pins(lock_text)
    if requirements != locked:
        missing = sorted(requirements.keys() - locked.keys())
        extra = sorted(locked.keys() - requirements.keys())
        mismatched = sorted(
            name for name in requirements.keys() & locked.keys()
            if requirements[name] != locked[name]
        )
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        if mismatched:
            details.append("pin mismatch for " + ", ".join(mismatched))
        raise RuntimeLockError("requirements.lock does not match requirements.txt: " + "; ".join(details))

    pip_pin = locked.get("pip")
    if pip_pin is None or pip_pin.version != runtime_security.PIP_VERSION:
        raise RuntimeLockError("requirements.lock does not pin the trusted bootstrap pip version.")
    pip_hashes = hashes_by_name["pip"]
    if pip_hashes != frozenset({runtime_security.PIP_WHEEL_SHA256}):
        raise RuntimeLockError("requirements.lock pip wheel hash does not match the trusted bootstrap wheel.")


def validate_runtime_lock(
    requirements_path: Path | str = DEFAULT_REQUIREMENTS_PATH,
    lock_path: Path | str = DEFAULT_LOCK_PATH,
) -> Path:
    """Validate the checked-in lock without network or dependency imports.

    Returns the resolved lock path for the caller to give to pip only after
    the content has passed all fail-closed checks.
    """
    requirements_file = Path(requirements_path)
    lock_file = Path(lock_path)
    try:
        requirements_text = read_regular_text_file(
            requirements_file,
            max_bytes=MAX_REQUIREMENTS_BYTES,
            label="requirements file",
        )
        lock_text = read_regular_text_file(
            lock_file,
            max_bytes=MAX_LOCK_BYTES,
            label="requirements lock",
        )
    except RuntimeLockError:
        raise
    validate_lock_text(requirements_text, lock_text)
    return lock_file.resolve()
