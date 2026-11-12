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


def native_roots(prefix: str | os.PathLike[str] | None = None) -> list[Path]:
    """Handbuilt's own PDF tool folders, newest first."""
    start = Path(prefix or sys.prefix).resolve()
    for parent in list(start.parents)[:4]:
        native = parent / "native"
        if native.is_dir():
            return sorted(
                (item for item in native.iterdir() if (item / READY_MARKER).is_file()),
                reverse=True,
            )
    return []


def library_directories(prefix: str | os.PathLike[str] | None = None, *,
                        platform: str | None = None) -> list[str]:
    platform = platform or sys.platform
    windows = platform.startswith("win")
    candidates = [root / ("Library/bin" if windows else "lib") for root in native_roots(prefix)]
    if platform == "darwin":
        candidates += [Path("/opt/homebrew/lib"), Path("/usr/local/lib")]
    return [str(item) for item in candidates if item.is_dir()]


def tool_directories(prefix: str | os.PathLike[str] | None = None, *,
                     platform: str | None = None) -> list[str]:
    """Folders that hold Handbuilt's own PDF command-line tools."""
    platform = platform or sys.platform
    windows = platform.startswith("win")
    candidates = [root / ("Library/bin" if windows else "bin") for root in native_roots(prefix)]
    return [str(item) for item in candidates if item.is_dir()]


def prepare(prefix: str | os.PathLike[str] | None = None) -> list[str]:
    """Add the library folders for this process and the ones it starts."""
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
        fallback = current.split(":") if current else [
            os.path.expanduser("~/lib"), "/usr/local/lib", "/usr/lib"]
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(dict.fromkeys(directories + fallback))
    for root in native_roots(prefix):
        fonts = root / ("Library/etc/fonts" if sys.platform.startswith("win") else "etc/fonts")
        if (fonts / "fonts.conf").is_file():
            os.environ.setdefault("FONTCONFIG_PATH", str(fonts))
            break
    return directories


# Setup installs this file under the name below; only that copy runs at startup.
if __name__ == "handbuilt_native_libraries":
    try:
        prepare()
    except Exception:  # noqa: BLE001 - a startup hook must never stop Python
        pass
