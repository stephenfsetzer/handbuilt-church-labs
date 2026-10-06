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

    def test_unregistered_money_figures_are_caught_without_printing_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "tools" / "example-figures.txt").write_text("1,800  # invented\n", encoding="utf-8")
            (root / "guide.md").write_text(
                "We spent $1,800 on repairs.\nAugust brought in $" + "3,417 of giving.\n",
                encoding="utf-8",
            )
            (root / "finance_notes.md").write_text("The year is 61," + "803 short.\n", encoding="utf-8")
            (root / "setup.py").write_text("finance-report setup one-time --amount 98" + "765\n", encoding="utf-8")
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("guide.md:1 ", result.stdout)
            self.assertIn("guide.md:2  [unregistered money figure]", result.stdout)
            self.assertIn("finance_notes.md:1  [unregistered money figure]", result.stdout)
            self.assertIn("setup.py:1  [unregistered money figure]", result.stdout)
            self.assertIn("tools/example-figures.txt", result.stdout)
            for figure in ("3,417", "61,803", "98765"):
                self.assertNotIn(figure, result.stdout)

    def test_registered_figures_small_amounts_and_word_counts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "tools" / "example-figures.txt").write_text("$25,000\n12345\n", encoding="utf-8")
            (root / "guide.md").write_text(
                "An estate gift of $25,000.00 and a $12,345 bequest; coffee was $50 and $999.\n"
                "Research runs 1,600 to 2,200 words.\n",
                encoding="utf-8",
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_this_repository_registers_every_money_figure(self) -> None:
        result = run_checker(REPO_ROOT)
        self.assertNotIn("unregistered money figure", result.stdout)

    def test_scans_and_exports_are_blocked_once_committed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture User"], cwd=root, check=True)
            for name in ("report.pdf", "scan.png", "export.csv"):
                (root / name).write_bytes(b"synthetic")
            (root / "fonts").mkdir()
            (root / "fonts" / "Body.ttf").write_bytes(b"\x00font")
            self.assertEqual(run_checker(root).returncode, 0)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            for name in ("report.pdf", "scan.png", "export.csv"):
                self.assertIn(f"{name}  [private file type]", result.stdout)
            self.assertNotIn("Body.ttf", result.stdout)

    def test_pull_request_and_commit_text_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            denylist = Path(tmp) / "private-denylist.txt"
            denylist.write_text("Example Parish\n", encoding="utf-8")
            clean = Path(tmp) / "clean.txt"
            clean.write_text("Read the year through the last recorded month.\n", encoding="utf-8")
            self.assertEqual(run_checker(root, "--denylist", str(denylist), "--text", str(clean)).returncode, 0)
            leaky = Path(tmp) / "pull-request.txt"
            leaky.write_text(
                "Found building Example Parish's report.\nThe year read $" + "17,402 ahead.\n",
                encoding="utf-8",
            )
            result = run_checker(root, "--denylist", str(denylist), "--text", str(leaky))
            self.assertEqual(result.returncode, 1)
            self.assertIn("text:pull-request.txt:1  [private denylist]", result.stdout)
            self.assertIn("text:pull-request.txt:2  [unregistered money figure]", result.stdout)
            self.assertNotIn("Example Parish", result.stdout)

    def test_unregistered_account_numbers_are_caught_in_finance_files_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / "tools").mkdir(parents=True)
            (root / "tools" / "example-accounts.txt").write_text("6510\n2210-07\n", encoding="utf-8")
            (root / "finance_notes.md").write_text(
                '"6510 Utilities" and the "2210-07" fund.\n'
                "The 2026-08 report covers 2025 Giving and 3 Sundays.\n"
                '"88' + '31-04 Choir Robes" and the group ["' + '9925Q"].\n',
                encoding="utf-8",
            )
            (root / "guide.md").write_text("Room 88" + "31 Choir practice.\n", encoding="utf-8")
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("finance_notes.md:1 ", result.stdout)
            self.assertNotIn("finance_notes.md:2 ", result.stdout)
            self.assertIn("finance_notes.md:3  [unregistered account number]", result.stdout)
            self.assertNotIn("guide.md", result.stdout)
            self.assertIn("tools/example-accounts.txt", result.stdout)
            for code in ("8831", "9925Q"):
                self.assertNotIn(code, result.stdout)
            text = Path(tmp) / "commit.txt"
            text.write_text("Strip numbers like 44" + "02B Sexton Wages.\n", encoding="utf-8")
            result = run_checker(root, "--text", str(text))
            self.assertIn("text:commit.txt:1  [unregistered account number]", result.stdout)

    def test_this_repository_registers_every_account_number(self) -> None:
        result = run_checker(REPO_ROOT)
        self.assertNotIn("unregistered account number", result.stdout)

    def test_checker_does_not_exempt_its_own_source(self) -> None:
        source = CHECKER.read_text(encoding="utf-8")
        self.assertNotIn("path.resolve() == SELF", source)
        self.assertNotIn("if path == SELF", source)


if __name__ == "__main__":
    unittest.main()
