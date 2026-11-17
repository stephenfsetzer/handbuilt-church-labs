"""The plugin ships only what the Claude plugin directory accepts.

Handbuilt is not a Verified organization, so the directory refuses a plugin
that has a bin/ folder, has a .claude/skills/ folder, or has a file it cannot
read completely: anything other than an image or font at 256 KiB or more.
These rules are checked here so a release cannot bring a refused file back.
The developer portal's Validate still runs before each submission, because
the directory's rules can change.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 256 * 1024
MAX_FILES = 512
IMAGES_AND_FONTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".otf"}
SYSTEM_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def shipped_files() -> list[str]:
    """Every file the plugin ships, as paths relative to the plugin folder."""
    if (ROOT / ".git").exists():
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                                capture_output=True).stdout.decode("utf-8").split("\0")
        return sorted(path for path in listed if path and (ROOT / path).is_file())
    # An installed copy has no Git history; every file there shipped.
    found = []
    for folder, children, files in os.walk(ROOT):
        children[:] = [name for name in children if name not in {".git", "__pycache__"}]
        found.extend(Path(folder, name).relative_to(ROOT).as_posix() for name in files
                     if not name.endswith(".pyc"))
    return sorted(found)


class DirectoryRulesTest(unittest.TestCase):
    def test_no_bin_folder(self):
        self.assertEqual([path for path in shipped_files() if path.startswith("bin/")], [],
                         "the directory accepts bin/ only from Verified organizations; use tools/")

    def test_no_claude_skills_folder(self):
        self.assertEqual([path for path in shipped_files() if path.startswith(".claude/skills/")], [],
                         "the directory accepts .claude/skills/ only from Verified organizations")

    def test_every_file_the_directory_reads_is_under_256_kib(self):
        large = [f"{path} ({(ROOT / path).stat().st_size} bytes)" for path in shipped_files()
                 if Path(path).suffix.lower() not in IMAGES_AND_FONTS
                 and (ROOT / path).stat().st_size >= LIMIT_BYTES]
        self.assertEqual(large, [], "the directory can't read these completely; split them into parts")

    def test_no_system_files(self):
        self.assertEqual([path for path in shipped_files() if Path(path).name in SYSTEM_FILES
                          or "__MACOSX/" in path], [])

    def test_the_plugin_stays_within_the_file_count(self):
        count = len(shipped_files())
        self.assertLessEqual(count, MAX_FILES, f"{count} files; the directory holds a plugin over {MAX_FILES}")


if __name__ == "__main__":
    unittest.main()
