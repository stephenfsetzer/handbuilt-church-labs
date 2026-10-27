from __future__ import annotations

from collections import namedtuple
import unittest

from tools import runtime_security


class RuntimeSecurityTests(unittest.TestCase):
    def test_security_floor_covers_reviewed_python_branches(self):
        self.assertEqual(runtime_security.MINIMUM_PYTHON, (3, 11))
        self.assertEqual(runtime_security.PYTHON_SECURITY_FLOORS, {
            (3, 11): (3, 11, 18),
            (3, 12): (3, 12, 16),
            (3, 13): (3, 13, 18),
            (3, 14): (3, 14, 10),
            (3, 15): (3, 15, 2),
        })
        for version in runtime_security.PYTHON_SECURITY_FLOORS.values():
            with self.subTest(version=version):
                self.assertIsNone(runtime_security.python_security_error(version))
                below = (*version[:2], version[2] - 1)
                self.assertIn("security minimum", runtime_security.python_security_error(below))

    def test_eol_and_unreviewed_branches_fail_closed(self):
        for version in ((3, 10, 22), (3, 9, 18), (3, 16, 0), (4, 0, 0)):
            with self.subTest(version=version):
                self.assertIsNotNone(runtime_security.python_security_error(version))

    def test_3_15_security_floor_does_not_enable_missing_wheel_runtime(self):
        self.assertIsNone(runtime_security.python_security_error((3, 15, 2)))
        self.assertIn("not yet supported", runtime_security.python_runtime_error((3, 15, 2)))
        self.assertIn("PyYAML", runtime_security.PYTHON_RUNTIME_SUPPORT_URL)
        self.assertIsNone(runtime_security.python_runtime_error((3, 14, 10)))

    def test_prerelease_and_unknown_release_level_fail_closed(self):
        VersionInfo = namedtuple("VersionInfo", "major minor micro releaselevel serial")
        self.assertIsNotNone(runtime_security.python_security_error(VersionInfo(3, 15, 2, "alpha", 1)))
        self.assertIsNotNone(runtime_security.python_security_error(VersionInfo(3, 15, 2, "candidate", 1)))
        self.assertIsNotNone(runtime_security.python_security_error(VersionInfo(3, 15, 2, "unknown", 1)))
        self.assertIsNone(runtime_security.python_security_error(VersionInfo(3, 15, 2, "final", 0)))

    def test_invalid_version_shapes_do_not_pass(self):
        for version in (None, "3.15.2", (3, 15), (3, "15", 2), (True, 15, 2)):
            with self.subTest(version=version):
                self.assertIsNotNone(runtime_security.python_security_error(version))


if __name__ == "__main__":
    unittest.main()
