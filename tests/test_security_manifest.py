from __future__ import annotations

from collections import namedtuple
import re
from pathlib import Path
from urllib.parse import urlsplit
import unittest

from tools import runtime_security as security


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def read_requirement_pins() -> dict[str, str]:
    pins = {}
    for raw_line in (REPOSITORY_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        name, version = line.split("==", 1)
        pins[name.lower().replace("_", "-")] = version
    return pins


class RuntimeSecurityPolicyTests(unittest.TestCase):
    def test_manifest_has_the_verified_security_pins(self):
        pins = read_requirement_pins()
        self.assertEqual(
            {name: pins[name] for name in ("pip", "certifi", "setuptools", "brotli", "pillow", "pypdf")},
            {
                "pip": security.PIP_VERSION,
                "certifi": security.CERTIFI_MINIMUM,
                "brotli": "1.2.1",
                "pillow": "13.0.0",
                "setuptools": "84.1.0",
                "pypdf": "6.21.2",
            },
        )
        self.assertEqual(security.PIP_VERSION, "26.2.2")

    def test_reviewed_python_floor_is_accepted_and_previous_patch_is_rejected(self):
        self.assertEqual(security.PYTHON_SECURITY_FLOORS, {
            (3, 11): (3, 11, 18),
            (3, 12): (3, 12, 16),
            (3, 13): (3, 13, 18),
            (3, 14): (3, 14, 10),
            (3, 15): (3, 15, 2),
        })
        for floor in security.PYTHON_SECURITY_FLOORS.values():
            with self.subTest(floor=floor):
                self.assertIsNone(security.python_security_error(floor))
                previous = (*floor[:2], floor[2] - 1)
                self.assertIsNotNone(security.python_security_error(previous))

    def test_python_310_and_unreviewed_future_branch_are_rejected(self):
        self.assertIsNotNone(security.python_security_error((3, 10, 22)))
        self.assertIsNotNone(security.python_security_error((3, 16, 0)))

    def test_prerelease_and_unknown_release_levels_are_rejected(self):
        VersionInfo = namedtuple("VersionInfo", "major minor micro releaselevel serial")
        self.assertIsNotNone(security.python_security_error(VersionInfo(3, 15, 2, "candidate", 1)))
        self.assertIsNotNone(security.python_security_error(VersionInfo(3, 15, 2, "other", 1)))
        self.assertIsNotNone(security.python_security_error((3, "15", 2)))

    def test_pip_wheel_is_https_on_pypi_file_host_with_sha256(self):
        parsed = urlsplit(security.PIP_WHEEL_URL)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "files.pythonhosted.org")
        self.assertEqual(parsed.path.rsplit("/", 1)[-1], "pip-26.2.2-py3-none-any.whl")
        self.assertRegex(security.PIP_WHEEL_SHA256, re.compile(r"^[0-9a-f]{64}$"))
        self.assertEqual(
            security.PIP_WHEEL_SHA256,
            "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70",
        )


if __name__ == "__main__":
    unittest.main()
