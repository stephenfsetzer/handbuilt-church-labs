#!/usr/bin/env python3
"""Check the public tree for high-confidence private or credential material.

This is a release hygiene check, not a complete privacy audit. A private
denylist can be supplied outside the repository with ``--denylist`` or the
``HANDBUILT_PRIVATE_DENYLIST`` environment variable. Each non-empty,
non-comment line is matched without printing the matching text.

Money figures get a stricter rule because a real church's books look exactly
like a made-up example. Every dollar amount of $1,000 or more, every
comma-grouped number in a finance file, and every ``--amount`` example must be
listed in ``tools/example-figures.txt``. Adding a figure there is a visible,
deliberate statement in the pull request that the figure is invented.

Account numbers get the same rule, because a chart of accounts is as
identifying as the figures in it. In finance files and in pull request and
commit text, an account number written with its name ("6510 Utilities"), or a
quoted number with hyphen, dot or letter parts ("2210-07", "7315B"), must be
listed in ``tools/example-accounts.txt``.

Images, PDFs, office documents, spreadsheets and accounting exports are never
committed: a scan, screenshot or export cannot be read for private material,
so the file type itself is a finding. Fonts are the only binary files allowed.

``--text FILE`` scans pull request titles, descriptions and commit messages
written to FILE with the same rules, so public Git and GitHub text is checked
as well as the tree.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator


ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "fonts",
    "venv",
}
PRIVATE_DIRS = {".handbuilt-runtime", ".private", "private-church-data", "runtime"}
SENSITIVE_FILENAMES = {
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "token.json",
}
SENSITIVE_FILENAME_PATTERNS = (
    re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE),
    re.compile(r"(?:^|[._-])(credentials|secrets|secret|tokens?)(?:[._-]|$)", re.IGNORECASE),
)

# These patterns are intentionally narrow. Generic names such as "name" or
# "email" are useful source data in a public project and are not findings.
DETECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential assignment",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
            r"private[_-]?key|password|passwd|secret|token)\b\s*[:=]\s*"
            r"[\"']?[A-Za-z0-9_./+=:-]{8,}[\"']?",
            re.IGNORECASE,
        ),
    ),
    (
        "private key block",
        re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----"),
    ),
    (
        "provider token",
        re.compile(
            r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
            r"xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,})\b"
        ),
    ),
    (
        "cloud access key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "private user path",
        re.compile(
            r"(?i)(?:"
            + "|".join(re.escape(root) for root in ("/" + "Users", "/" + "home"))
            + r")/[^/\s]+(?:/[^\s]*)?"
        ),
    ),
)


BLOCKED_FILE_TYPES = {
    ".bmp", ".csv", ".doc", ".docx", ".gif", ".heic", ".iif", ".jpeg", ".jpg", ".numbers",
    ".ods", ".odt", ".ofx", ".pages", ".pdf", ".png", ".ppt", ".pptx", ".qbo", ".qfx",
    ".svg", ".tif", ".tiff", ".tsv", ".webp", ".xls", ".xlsx", ".zip",
}
FIGURE_REGISTRY = Path("tools") / "example-figures.txt"
DOLLAR_FIGURE = re.compile(r"\$\s?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})(?:\.[0-9]{1,2})?(?![0-9])")
GROUPED_FIGURE = re.compile(r"(?<![0-9.,$])([0-9]{1,3}(?:,[0-9]{3})+)(?![0-9,])")
AMOUNT_OPTION = re.compile(r"--amount[ =]([0-9]{4,})(?![0-9])")
ACCOUNT_REGISTRY = Path("tools") / "example-accounts.txt"
ACCOUNT_CODE = r"[0-9]{3,5}(?:[-.][0-9]{1,3})*[A-Za-z]?"
# A number followed by a capitalised name: "6510 Utilities", "2210-07 General Fund".
NAMED_ACCOUNT = re.compile(rf"(?<![\w.$,/-])({ACCOUNT_CODE})[ \t]+(?=[A-Z][A-Za-z&]{{2}})")
# A quoted number with parts, as in group settings: "2210-07", "7315B".
QUOTED_ACCOUNT = re.compile(r"[\"']([0-9]{3,5}(?:[-.][0-9]{1,3})+[A-Za-z]?|[0-9]{3,5}[A-Za-z])[\"']")
YEAR_OR_MONTH = re.compile(r"(?:19|20)[0-9]{2}(?:-(?:0[1-9]|1[0-2])(?:-[0-9]{2})?)?")


def normalize_figure(raw: str) -> str:
    return raw.replace("$", "").replace(",", "").strip().split(".")[0].lstrip("0") or "0"


def load_figure_registry(root: Path) -> frozenset[str]:
    path = root / FIGURE_REGISTRY
    if not path.exists():
        return frozenset()
    figures = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            figures.add(normalize_figure(entry))
    return frozenset(figures)


def load_account_registry(root: Path) -> frozenset[str]:
    path = root / ACCOUNT_REGISTRY
    if not path.exists():
        return frozenset()
    accounts = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            accounts.add(entry.casefold())
    return frozenset(accounts)


def unregistered_accounts(line: str, registry: frozenset[str]) -> bool:
    found = [m.group(1) for m in NAMED_ACCOUNT.finditer(line)]
    found += [m.group(1) for m in QUOTED_ACCOUNT.finditer(line)]
    return any(
        not YEAR_OR_MONTH.fullmatch(code) and code.casefold() not in registry for code in found
    )


def is_finance_path(location: str) -> bool:
    return "finance" in location.casefold()


def unregistered_figures(line: str, location: str, registry: frozenset[str]) -> bool:
    found = [m.group(1) for m in DOLLAR_FIGURE.finditer(line)]
    found += [m.group(1) for m in AMOUNT_OPTION.finditer(line)]
    if is_finance_path(location):
        found += [m.group(1) for m in GROUPED_FIGURE.finditer(line)]
    return any(normalize_figure(figure) not in registry for figure in found)


class Finding:
    def __init__(self, location: str, rule: str, line: int | None = None):
        self.location = location
        self.rule = rule
        self.line = line

    def display(self) -> str:
        suffix = f":{self.line}" if self.line is not None else ""
        return f"  {self.location}{suffix}  [{self.rule}]"


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def is_sensitive_filename(path: Path) -> bool:
    if path.name.lower() == ".env.example":
        return False
    if path.name.lower() in SENSITIVE_FILENAMES:
        return True
    return any(pattern.search(path.name) for pattern in SENSITIVE_FILENAME_PATTERNS)


def relative_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def is_private_path(path: Path) -> bool:
    return any(part in PRIVATE_DIRS for part in path.parts)


def tracked_paths(root: Path) -> set[str]:
    """Return tracked paths so ignored private directories cannot hide commits."""
    if not (root / ".git").exists():
        return set()
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip() or "git ls-files failed"
        raise RuntimeError(detail)
    return {
        Path(item.decode("utf-8", errors="surrogateescape")).as_posix()
        for item in result.stdout.split(b"\x00")
        if item
    }


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OSError(f"could not read {path}: {exc}") from exc
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def load_private_denylist(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OSError(f"could not read private denylist {path}: {exc}") from exc
    terms = []
    for line in lines:
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return terms


def scan_text(
    text: str,
    location: str,
    denylist: Iterable[str],
    figures: frozenset[str] | None = None,
    accounts: frozenset[str] | None = None,
) -> list[Finding]:
    """Scan one text. ``figures`` and ``accounts`` are the example registries; None skips that rule.

    The account rule applies to finance files and to pull request and commit text.
    """
    check_accounts = accounts is not None and (
        is_finance_path(location) or location.startswith("text:")
    )
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for rule, pattern in DETECTION_RULES:
            if pattern.search(line):
                findings.append(Finding(location, rule, line_number))
        if figures is not None and location != FIGURE_REGISTRY.as_posix():
            if unregistered_figures(line, location, figures):
                findings.append(Finding(location, "unregistered money figure", line_number))
        if check_accounts and unregistered_accounts(line, accounts):
            findings.append(Finding(location, "unregistered account number", line_number))
        lowered = line.casefold()
        for _term in denylist:
            if _term.casefold() in lowered:
                findings.append(Finding(location, "private denylist", line_number))
                break
    return findings


def scan_worktree(root: Path, denylist: Iterable[str]) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    errors: list[str] = []
    figures = load_figure_registry(root)
    accounts = load_account_registry(root)
    try:
        tracked = tracked_paths(root)
    except RuntimeError as exc:
        return [], [f"tracked path scan unavailable: {exc}"]
    try:
        paths = sorted(root.rglob("*"))
    except OSError as exc:
        return [], [f"could not list {root}: {exc}"]
    for path in paths:
        if path.is_dir() or path.is_symlink():
            continue
        location = relative_label(path, root)
        tracked_private = location in tracked and is_private_path(Path(location))
        if tracked_private:
            findings.append(Finding(location, "tracked private path"))
        if any(part in SKIP_DIRS or part in PRIVATE_DIRS for part in path.parts) and not tracked_private:
            continue
        if is_sensitive_filename(path):
            findings.append(Finding(location, "sensitive filename"))
        if path.suffix.lower() in BLOCKED_FILE_TYPES:
            # In a checkout, only committed files count; test runs may leave renders behind.
            if not (root / ".git").exists() or location in tracked:
                findings.append(Finding(location, "private file type"))
            continue
        if not is_text_candidate(path):
            continue
        try:
            text = read_text(path)
        except OSError as exc:
            errors.append(str(exc))
            continue
        if text is not None:
            findings.extend(scan_text(text, location, denylist, figures, accounts))
    return findings, errors


def git_history_objects(root: Path) -> Iterator[tuple[str, str]]:
    result = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git rev-list failed"
        raise RuntimeError(detail)
    seen: set[str] = set()
    for row in result.stdout.splitlines():
        parts = row.split(" ", 1)
        object_id = parts[0]
        location = parts[1] if len(parts) == 2 else object_id
        if object_id not in seen:
            seen.add(object_id)
            yield object_id, location


def scan_history(root: Path, denylist: Iterable[str]) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    errors: list[str] = []
    try:
        objects = git_history_objects(root)
        for object_id, location in objects:
            path = Path(location)
            history_location = f"history:{location}"
            if is_private_path(path):
                findings.append(Finding(history_location, "tracked private path"))
            if any(part in SKIP_DIRS for part in path.parts) and not is_private_path(path):
                continue
            if is_sensitive_filename(path):
                findings.append(Finding(history_location, "sensitive filename"))
            if not is_text_candidate(path):
                continue
            result = subprocess.run(
                ["git", "cat-file", "-p", object_id],
                cwd=root,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                errors.append(f"could not read history object {object_id}")
                continue
            if b"\x00" in result.stdout:
                continue
            try:
                text = result.stdout.decode("utf-8")
            except UnicodeDecodeError:
                continue
            findings.extend(scan_text(text, history_location, denylist))
    except (OSError, RuntimeError) as exc:
        errors.append(f"history scan unavailable: {exc}")
    return findings, errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="tree to scan")
    parser.add_argument("--history", action="store_true", help="scan reachable Git blobs")
    parser.add_argument(
        "--denylist",
        type=Path,
        default=None,
        help="private terms file, one term per line, kept outside the repository",
    )
    parser.add_argument(
        "--text",
        type=Path,
        action="append",
        default=[],
        help="also scan this file of pull request or commit message text (repeatable)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = args.root.resolve()
    denylist_path = args.denylist
    if denylist_path is None:
        configured = os.environ.get("HANDBUILT_PRIVATE_DENYLIST")
        denylist_path = Path(configured).expanduser() if configured else None
    try:
        denylist = load_private_denylist(denylist_path)
    except OSError as exc:
        print(f"PII CHECK ERROR: {exc}", file=sys.stderr)
        return 2

    findings, errors = scan_worktree(root, denylist)
    figures = load_figure_registry(root)
    accounts = load_account_registry(root)
    for text_path in args.text:
        try:
            text = text_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"could not read {text_path}: {exc}")
            continue
        findings.extend(scan_text(text, f"text:{text_path.name}", denylist, figures, accounts))
    if args.history:
        history_findings, history_errors = scan_history(root, denylist)
        findings.extend(history_findings)
        errors.extend(history_errors)
    if errors:
        print("PII CHECK ERROR:")
        for error in errors:
            print(f"  {error}")
        return 2
    if findings:
        print(f"PII CHECK FAILED: {len(findings)} hit(s)")
        for finding in findings:
            print(finding.display())
        if any(finding.rule == "unregistered money figure" for finding in findings):
            print(
                "  Money figures must be invented. If a flagged figure is made up, add it to "
                f"{FIGURE_REGISTRY.as_posix()}. If it came from a real church, replace it."
            )
        if any(finding.rule == "unregistered account number" for finding in findings):
            print(
                "  Account numbers must come from the invented Riverbend chart. If a flagged number "
                f"is made up, add it to {ACCOUNT_REGISTRY.as_posix()}. If it came from a real "
                "church's books, replace it."
            )
        return 1
    scope = "working tree and reachable Git history" if args.history else "working tree"
    print(f"PII check passed: no high-confidence findings in {scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
