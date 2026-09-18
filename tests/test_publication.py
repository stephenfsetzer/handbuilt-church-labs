from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publication.yml"


def run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


class PublicationGuardTests(unittest.TestCase):
    def test_release_assets_job_requires_main_ancestry_before_upload(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        release_assets = workflow.index("  release-assets:")
        upload = workflow.index("gh release upload", release_assets)
        guard = workflow.index("git merge-base --is-ancestor HEAD refs/remotes/origin/main", release_assets)

        self.assertIn("fetch-depth: 0", workflow[release_assets:upload])
        self.assertIn("ref: ${{ github.event.release.tag_name }}", workflow[release_assets:upload])
        self.assertLess(guard, upload)

    def test_main_ancestry_guard_accepts_main_history_and_rejects_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_git(root, "init", "--quiet")
            run_git(root, "config", "user.name", "Test User")
            run_git(root, "config", "user.email", "test@example.com")

            (root / "README").write_text("base\n", encoding="utf-8")
            run_git(root, "add", "README")
            run_git(root, "commit", "--quiet", "-m", "base")
            main_tip = run_git(root, "rev-parse", "HEAD").stdout.strip()
            run_git(root, "update-ref", "refs/remotes/origin/main", main_tip)

            main_result = subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(main_result.returncode, 0)

            (root / "README").write_text("experimental\n", encoding="utf-8")
            run_git(root, "commit", "--quiet", "-am", "experimental")
            experiment_result = subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(experiment_result.returncode, 0)

    def test_main_ancestry_guard_rejects_missing_main_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_git(root, "init", "--quiet")
            (root / "README").write_text("base\n", encoding="utf-8")
            run_git(root, "add", "README")
            run_git(root, "-c", "user.name=Test User", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "base")

            result = subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
