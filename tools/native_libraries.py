"""Help Handbuilt's Python find the PDF libraries that live outside it.

Setup copies this file into Handbuilt's private Python environment, where it
runs once each time that Python starts. The PDF engine (WeasyPrint) needs the
Pango text libraries. Handbuilt's own Python does not look where those are
installed, so this adds the folders that hold them:

- Handbuilt's own PDF tools, when setup has installed them beside the runtime.
- Homebrew's library folders on a Mac.

It only adds places to look. It downloads nothing and changes no files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


READY_MARKER = ".handbuilt-native-ready"
_DLL_HANDLES: list[object] = []


def roots_under(runtime_root: str | os.PathLike[str]) -> list[Path]:
    """Handbuilt's own PDF tool folders in this runtime folder, newest first."""
    native = Path(runtime_root) / "native"
    if not native.is_dir():
        return []
    return sorted((item for item in native.iterdir() if (item / READY_MARKER).is_file()), reverse=True)


def native_roots(prefix: str | os.PathLike[str] | None = None) -> list[Path]:
    """Handbuilt's own PDF tool folders, newest first, found from a Python inside the runtime."""
    start = Path(prefix or sys.prefix).resolve()
    for parent in list(start.parents)[:4]:
        if (parent / "native").is_dir():
            return roots_under(parent)
    return []


def library_directories(prefix: str | os.PathLike[str] | None = None, *,
                        platform: str | None = None) -> list[str]:
    platform = platform or sys.platform
    windows = platform.startswith("win")
    own = [root / ("Library/bin" if windows else "lib") for root in native_roots(prefix)]
    own = [str(item) for item in own if item.is_dir()]
    if own:
        # Handbuilt's own libraries are used alone. Loading them beside
        # Homebrew's copies of the same libraries crashes the PDF engine.
        return own[:1]
    if platform == "darwin":
        return [str(item) for item in (Path("/opt/homebrew/lib"), Path("/usr/local/lib")) if item.is_dir()]
    return []


def tool_directories(prefix: str | os.PathLike[str] | None = None, *,
                     platform: str | None = None) -> list[str]:
    """Folders that hold Handbuilt's own PDF command-line tools."""
    platform = platform or sys.platform
    windows = platform.startswith("win")
    candidates = [root / ("Library/bin" if windows else "bin") for root in native_roots(prefix)]
    return [str(item) for item in candidates if item.is_dir()]


def use_utf8_on_windows() -> None:
    """Make Handbuilt's Python on Windows speak UTF-8 to the screen and to the programs it starts.

    Windows otherwise uses an older encoding that cannot hold curly quotes or
    the characters in a psalm, and a bulletin stops with an encoding error.
    """
    if not sys.platform.startswith("win"):
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def prepare(prefix: str | os.PathLike[str] | None = None) -> list[str]:
    """Add the library and tool folders for this process and the ones it starts."""
    # Handbuilt's own PDF tools go first on the path, so "pdfinfo" and the
    # others are found by name on a computer that has no other copy.
    tools = tool_directories(prefix)
    if tools:
        current = os.environ.get("PATH")
        os.environ["PATH"] = os.pathsep.join(dict.fromkeys(tools + (current.split(os.pathsep) if current else [])))
    directories = library_directories(prefix)
    if not directories:
        return []
    if sys.platform.startswith("win"):
        for directory in directories:
            try:
                _DLL_HANDLES.append(os.add_dll_directory(directory))
            except (OSError, AttributeError):
                pass
        for name in ("WEASYPRINT_DLL_DIRECTORIES", "PATH"):
            current = os.environ.get(name)
            parts = directories + (current.split(os.pathsep) if current else [])
            os.environ[name] = os.pathsep.join(dict.fromkeys(parts))
    elif sys.platform == "darwin":
        current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH")
        own = bool(native_roots(prefix))
        # With Handbuilt's own libraries, look nowhere else but the system.
        fallback = ["/usr/lib"] if own else (current.split(":") if current else [
            os.path.expanduser("~/lib"), "/usr/local/lib", "/usr/lib"])
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(dict.fromkeys(directories + fallback))
    for root in native_roots(prefix):
        fonts = root / ("Library/etc/fonts" if sys.platform.startswith("win") else "etc/fonts")
        if (fonts / "fonts.conf").is_file():
            os.environ.setdefault("FONTCONFIG_PATH", str(fonts))
            break
    return directories


# Setup installs this file under the name below; only that copy runs at startup.
if __name__ == "handbuilt_native_libraries":
    for _step in (use_utf8_on_windows, prepare):
        try:
            _step()
        except Exception:  # noqa: BLE001 - a startup hook must never stop Python
            pass
