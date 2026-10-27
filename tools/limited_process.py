#!/usr/bin/env python3
"""Set POSIX resource limits, then replace this process with the target command.

This helper avoids ``subprocess.Popen(preexec_fn=...)``, which is unsafe when
the parent process has threads. On non-POSIX platforms it simply execs the
command; callers must keep their wall-clock and output limits enabled. macOS
omits RLIMIT_AS because address-space limits can conflict with dyld mappings.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu-seconds", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--file-bytes", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    if os.name == "posix":
        try:
            import resource

            _set_limit(resource, resource.RLIMIT_CPU, args.cpu_seconds)
            # macOS address-space limits interact poorly with dyld mappings;
            # CPU/file limits plus the parent wall-clock and pixel limits stay
            # active there instead.
            if sys.platform != "darwin" and hasattr(resource, "RLIMIT_AS"):
                _set_limit(resource, resource.RLIMIT_AS, args.memory_bytes)
            if hasattr(resource, "RLIMIT_FSIZE"):
                _set_limit(resource, resource.RLIMIT_FSIZE, args.file_bytes)
        except (ImportError, OSError, ValueError) as exc:
            print(f"Could not apply native process limits: {exc}", file=sys.stderr)
            return 126

    os.execvpe(command[0], command, os.environ)
    return 127


def _set_limit(resource: object, limit_id: int, maximum: int) -> None:
    soft, hard = resource.getrlimit(limit_id)  # type: ignore[attr-defined]
    hard_max = hard if hard != resource.RLIM_INFINITY else maximum  # type: ignore[attr-defined]
    effective = min(maximum, hard_max)
    resource.setrlimit(limit_id, (effective, effective))  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())
