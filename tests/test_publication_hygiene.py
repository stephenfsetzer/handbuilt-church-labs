from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tools" / "pii_check.py"


def run_checker(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class PublicationHygieneTest(unittest.TestCase):
    def test_generic_credentials_and_private_paths_are_redacted_in_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "AKIA" + "1234567890ABCDEF"
            private_path = "/" + "Users" + "/alice/church-work"
            (root / "notes.md").write_text(
                f"Temporary key: {secret}\nPrivate checkout: {private_path}\n",
                encoding="utf-8",
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            self.assertIn("cloud access key", result.stdout)
            self.assertIn("private user path", result.stdout)
            self.assertNotIn(secret, result.stdout)
            self.assertNotIn("alice/church-work", result.stdout)

    def test_sensitive_environment_filename_is_caught_but_example_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.production").write_text("APP_TOKEN=placeholder\n", encoding="utf-8")
            (root / ".env.example").write_text("APP_TOKEN=replace-me\n", encoding="utf-8")
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            self.assertIn(".env.production", result.stdout)
            self.assertNotIn(".env.example", result.stdout)

    def test_private_denylist_stays_outside_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            denylist = Path(tmp) / "private-denylist.txt"
            denylist.write_text("Example Parish\n", encoding="utf-8")
            (root / "README.md").write_text("Example Parish is a fixture.\n", encoding="utf-8")
            result = run_checker(root, "--denylist", str(denylist))
            self.assertEqual(result.returncode, 1)
            self.assertIn("private denylist", result.stdout)
            self.assertNotIn("Example Parish", result.stdout)

    def test_missing_denylist_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_checker(Path(tmp), "--denylist", str(Path(tmp) / "missing.txt"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("PII CHECK ERROR", result.stderr)

    def test_history_mode_catches_a_reachable_deleted_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture User"], cwd=root, check=True)
            credential_line = "pass" + "word: deleted-secret-value\n"
            (root / "old.md").write_text(credential_line, encoding="utf-8")
            subprocess.run(["git", "add", "old.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            (root / "old.md").unlink()
            result = run_checker(root, "--history")
            self.assertEqual(result.returncode, 1)
            self.assertIn("history:old.md", result.stdout)
            self.assertNotIn("deleted-secret-value", result.stdout)

    def test_tracked_private_directory_is_flagged_in_worktree_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture User"], cwd=root, check=True)
            private_file = root / ".private" / "church.md"
            private_file.parent.mkdir()
            private_file.write_text("Synthetic private church fixture.\n", encoding="utf-8")
            subprocess.run(["git", "add", "-f", ".private/church.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            current = run_checker(root)
            self.assertEqual(current.returncode, 1)
            self.assertIn(".private/church.md", current.stdout)
            self.assertIn("tracked private path", current.stdout)
            history = run_checker(root, "--history")
            self.assertEqual(history.returncode, 1)
            self.assertIn("history:.private/church.md", history.stdout)
            self.assertIn("tracked private path", history.stdout)

    def test_checker_does_not_exempt_its_own_source(self) -> None:
        source = CHECKER.read_text(encoding="utf-8")
        self.assertNotIn("path.resolve() == SELF", source)
        self.assertNotIn("if path == SELF", source)


if __name__ == "__main__":
    unittest.main()
