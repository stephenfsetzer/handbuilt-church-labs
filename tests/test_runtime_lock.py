from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import lock_runtime_requirements, runtime_lock, runtime_security


PIP_HASH = runtime_security.PIP_WHEEL_SHA256
OTHER_HASH = "a" * 64


def sample_lock(pip_hash: str = PIP_HASH, certifi_hash: str = OTHER_HASH) -> str:
    return (
        "pip==26.2.2 --hash=sha256:" + pip_hash + "\n"
        "certifi==2026.10.19 --hash=sha256:" + certifi_hash + "\n"
        "qrcode[pil]==8.2 --hash=sha256:" + OTHER_HASH + "\n"
    )


def wheel_record(name: str, version: str, digest: str = OTHER_HASH, url: str | None = None) -> dict:
    filename = f"{name}-{version}-py3-none-any.whl"
    return {
        "filename": filename,
        "packagetype": "bdist_wheel",
        "yanked": False,
        "url": url or f"https://files.pythonhosted.org/packages/{filename}",
        "digests": {"sha256": digest},
    }


class RuntimeLockTests(unittest.TestCase):
    def test_lock_generator_refuses_unpatched_python_before_network_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "requirements.lock"
            with mock.patch.object(lock_runtime_requirements.sys, "version_info", (3, 14, 6)), \
                    mock.patch.object(lock_runtime_requirements, "urlopen") as network:
                with self.assertRaisesRegex(lock_runtime_requirements.LockGenerationError, "security-patched"):
                    lock_runtime_requirements.fetch_release_metadata("pip", runtime_security.PIP_VERSION)
                self.assertEqual(lock_runtime_requirements.main(["--output", str(output)]), 1)
            network.assert_not_called()
            self.assertFalse(output.exists())

    def test_checked_in_lock_matches_requirements_and_is_offline_valid(self):
        lock_path = runtime_lock.validate_runtime_lock()
        self.assertEqual(lock_path, runtime_lock.DEFAULT_LOCK_PATH.resolve())
        self.assertTrue(lock_path.is_file())

    def test_valid_exact_pins_and_hashes_pass(self):
        runtime_lock.validate_lock_text(
            "pip==26.2.2\ncertifi==2026.10.19\nqrcode[pil]==8.2\n",
            sample_lock(),
        )

    def test_lock_pin_drift_missing_and_extra_packages_fail(self):
        requirements = "pip==26.2.2\ncertifi==2026.10.19\nqrcode[pil]==8.2\n"
        cases = (
            sample_lock().replace("certifi==2026.10.19", "certifi==2026.10.20"),
            sample_lock().replace("certifi==2026.10.19 --hash=sha256:" + OTHER_HASH + "\n", ""),
            sample_lock() + "setuptools==84.1.0 --hash=sha256:" + OTHER_HASH + "\n",
            sample_lock().replace("qrcode[pil]==8.2", "qrcode==8.2"),
        )
        for lock_text in cases:
            with self.subTest(lock_text=lock_text[-70:]):
                with self.assertRaises(runtime_lock.RuntimeLockError):
                    runtime_lock.validate_lock_text(requirements, lock_text)

    def test_unhashed_or_malformed_entries_fail(self):
        requirements = "pip==26.2.2\ncertifi==2026.10.19\nqrcode[pil]==8.2\n"
        cases = (
            sample_lock().replace(" --hash=sha256:" + OTHER_HASH, "", 1),
            sample_lock().replace(OTHER_HASH, "A" * 64, 1),
            sample_lock().replace("--hash=sha256:", "--hash=sha512:", 1),
            sample_lock().replace("--hash=sha256:" + OTHER_HASH, "--hash=sha256:" + OTHER_HASH + " --hash=sha256:" + OTHER_HASH, 1),
        )
        for lock_text in cases:
            with self.subTest(lock_text=lock_text[:90]):
                with self.assertRaises(runtime_lock.RuntimeLockError):
                    runtime_lock.validate_lock_text(requirements, lock_text)

    def test_directives_urls_unpinned_and_duplicate_requirements_fail(self):
        invalid_requirements = (
            "-r other.txt\n",
            "certifi @ https://example.invalid/certifi.whl\n",
            "certifi>=2026.10.19\n",
            "certifi==2026.10.19\ncertifi==2026.10.19\n",
        )
        for text in invalid_requirements:
            with self.subTest(text=text):
                with self.assertRaises(runtime_lock.RuntimeLockError):
                    runtime_lock.parse_requirement_pins(text)

        for line in (
            "--index-url https://pypi.org/simple",
            "-r base.lock",
            "certifi==2026.10.19 https://example.invalid/certifi.whl",
        ):
            with self.subTest(line=line):
                with self.assertRaises(runtime_lock.RuntimeLockError):
                    runtime_lock.parse_lock_pins(line + "\n")

    def test_trusted_bootstrap_hash_is_mandatory_and_exclusive(self):
        requirements = "pip==26.2.2\ncertifi==2026.10.19\nqrcode[pil]==8.2\n"
        with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "bootstrap"):
            runtime_lock.validate_lock_text(
                requirements,
                sample_lock(pip_hash=OTHER_HASH),
            )
        with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "bootstrap"):
            runtime_lock.validate_lock_text(
                requirements,
                sample_lock().replace(
                    "pip==26.2.2 --hash=sha256:" + PIP_HASH,
                    "pip==26.2.2 --hash=sha256:" + PIP_HASH + " --hash=sha256:" + OTHER_HASH,
                ),
            )

    def test_missing_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            requirements = Path(directory) / "requirements.txt"
            requirements.write_text("pip==26.2.2\n", encoding="utf-8")
            with self.assertRaises(runtime_lock.RuntimeLockError):
                runtime_lock.validate_runtime_lock(requirements, Path(directory) / "missing.lock")

    def test_lock_files_must_be_bounded_regular_utf8_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements = root / "requirements.txt"
            lock = root / "requirements.lock"
            requirements.write_text("pip==26.2.2\n", encoding="utf-8")
            lock.write_text("pip==26.2.2 --hash=sha256:" + PIP_HASH + "\n", encoding="utf-8")

            linked_lock = root / "linked.lock"
            linked_lock.symlink_to(lock)
            with self.assertRaises(runtime_lock.RuntimeLockError):
                runtime_lock.validate_runtime_lock(requirements, linked_lock)

            linked_requirements = root / "linked-requirements.txt"
            linked_requirements.symlink_to(requirements)
            with self.assertRaises(runtime_lock.RuntimeLockError):
                runtime_lock.validate_runtime_lock(linked_requirements, lock)

            requirements.write_bytes(b"pip==26.2.2\n\xff")
            with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "UTF-8"):
                runtime_lock.validate_runtime_lock(requirements, lock)

            requirements.write_text("pip==26.2.2\n", encoding="utf-8")
            lock.write_bytes(b"pip==26.2.2 --hash=sha256:" + PIP_HASH.encode() + b"\n\xff")
            with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "UTF-8"):
                runtime_lock.validate_runtime_lock(requirements, lock)

            requirements.write_bytes(b"x" * (runtime_lock.MAX_REQUIREMENTS_BYTES + 1))
            with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "regular file"):
                runtime_lock.validate_runtime_lock(requirements, lock)

            requirements.write_text("pip==26.2.2\n", encoding="utf-8")
            lock.write_bytes(b"x" * (runtime_lock.MAX_LOCK_BYTES + 1))
            with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "regular file"):
                runtime_lock.validate_runtime_lock(requirements, lock)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO files are not available")
    def test_lock_validator_rejects_fifo_without_reading_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements = root / "requirements.txt"
            requirements.write_text("pip==26.2.2\n", encoding="utf-8")
            fifo = root / "requirements.lock"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(runtime_lock.RuntimeLockError, "regular file"):
                runtime_lock.validate_runtime_lock(requirements, fifo)

    def test_lock_generator_accepts_only_exact_release_wheel_hashes(self):
        requirements = "pip==26.2.2\ncertifi==2026.10.19\n"
        calls = []

        def fetcher(name: str, version: str):
            calls.append((name, version))
            if name == "pip":
                url = runtime_security.PIP_WHEEL_URL
                return {
                    "info": {"name": name, "version": version},
                    "urls": [{**wheel_record("pip", version, digest=PIP_HASH, url=url)}, {
                        "filename": "pip-26.2.2.tar.gz",
                        "packagetype": "sdist",
                        "digests": {"sha256": OTHER_HASH},
                    }],
                }
            return {
                "info": {"name": name, "version": version},
                "urls": [wheel_record(name, version), {
                    "filename": "certifi-2026.10.19.tar.gz",
                    "packagetype": "sdist",
                    "digests": {"sha256": "b" * 64},
                }],
            }

        lock_text = lock_runtime_requirements.render_lock(requirements, fetcher=fetcher)
        self.assertEqual(calls, [("certifi", "2026.10.19"), ("pip", "26.2.2")])
        self.assertNotIn(".tar.gz", lock_text)
        runtime_lock.validate_lock_text(requirements, lock_text)

    def test_lock_generator_rejects_wrong_pip_artifact_and_sdist_only_package(self):
        requirements = "pip==26.2.2\n"

        def wrong_pip(name: str, version: str):
            return {
                "info": {"name": name, "version": version},
                "urls": [wheel_record("pip", version, digest=PIP_HASH,
                                      url="https://files.pythonhosted.org/other.whl")],
            }

        with self.assertRaises(lock_runtime_requirements.LockGenerationError):
            lock_runtime_requirements.render_lock(requirements, fetcher=wrong_pip)
        with self.assertRaises(lock_runtime_requirements.LockGenerationError):
            lock_runtime_requirements.wheel_hashes("sample", "1.0", {
                "info": {"name": "sample", "version": "1.0"},
                "urls": [{"filename": "sample-1.0.tar.gz", "packagetype": "sdist",
                          "digests": {"sha256": OTHER_HASH}}],
            })

    def test_lock_generator_rejects_yanked_mismatched_and_mislabeled_wheels(self):
        cases = (
            {**wheel_record("certifi", "2026.10.19"), "yanked": True},
            wheel_record("unrelated", "9.9"),
            {**wheel_record("certifi", "2026.10.19"), "packagetype": "sdist"},
        )
        for record in cases:
            with self.subTest(record=record):
                with self.assertRaises(lock_runtime_requirements.LockGenerationError):
                    lock_runtime_requirements.wheel_hashes("certifi", "2026.10.19", {
                        "info": {"name": "certifi", "version": "2026.10.19"},
                        "urls": [record],
                    })

    def test_lock_generator_rejects_urls_with_credentials_ports_queries_fragments_or_bad_syntax(self):
        filename = "certifi-2026.10.19-py3-none-any.whl"
        urls = (
            f"https://user@files.pythonhosted.org/{filename}",
            f"https://files.pythonhosted.org:443/{filename}",
            f"https://files.pythonhosted.org/{filename}?token=x",
            f"https://files.pythonhosted.org/{filename}#fragment",
            "https://[invalid/" + filename,
        )
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(lock_runtime_requirements.LockGenerationError):
                    lock_runtime_requirements.wheel_hashes("certifi", "2026.10.19", {
                        "info": {"name": "certifi", "version": "2026.10.19"},
                        "urls": [wheel_record("certifi", "2026.10.19", url=url)],
                    })

    def test_pypi_json_response_is_bounded_and_strict_json(self):
        class FakeResponse:
            def __init__(self, url: str, raw: bytes):
                self.url = url
                self.raw = raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def geturl(self):
                return self.url

            def read(self, limit: int):
                return self.raw[:limit]

        url = "https://pypi.org/pypi/certifi/2026.10.19/json"
        oversized = FakeResponse(url, b"x" * (lock_runtime_requirements.MAX_METADATA_BYTES + 1))
        with mock.patch.object(lock_runtime_requirements, "urlopen", return_value=oversized):
            with self.assertRaisesRegex(lock_runtime_requirements.LockGenerationError, "size limit"):
                lock_runtime_requirements.fetch_release_metadata("certifi", "2026.10.19")

        malformed = FakeResponse(url, b"not-json")
        with mock.patch.object(lock_runtime_requirements, "urlopen", return_value=malformed):
            with self.assertRaises(lock_runtime_requirements.LockGenerationError):
                lock_runtime_requirements.fetch_release_metadata("certifi", "2026.10.19")


if __name__ == "__main__":
    unittest.main()
