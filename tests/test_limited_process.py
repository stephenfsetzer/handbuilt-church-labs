from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from skills.onboarding.bulletin_import import BulletinImportError, _run, _run_text


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "limited_process.py"


class LimitedProcessTests(unittest.TestCase):
    def test_helper_execs_target_and_sets_supported_limits(self):
        if os.name == "posix":
            source = (
            "import json, os, resource, sys; "
            "print(json.dumps({'args': sys.argv[1:], 'cpu': resource.getrlimit(resource.RLIMIT_CPU), "
            "'file': resource.getrlimit(resource.RLIMIT_FSIZE), "
            "'memory': resource.getrlimit(resource.RLIMIT_AS) if hasattr(resource, 'RLIMIT_AS') else None}))"
            )
        else:
            source = "import json, sys; print(json.dumps({'args': sys.argv[1:]}))"
        result = subprocess.run(
            [sys.executable, str(HELPER), "--cpu-seconds", "5", "--memory-bytes", str(2 * 1024**3),
             "--file-bytes", "1048576", "--", sys.executable, "-c", source, "forwarded"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values["args"], ["forwarded"])
        if os.name == "posix":
            self.assertLessEqual(values["cpu"][0], 5)
            self.assertLessEqual(values["file"][0], 1048576)
            if sys.platform != "darwin" and values["memory"] is not None:
                self.assertLessEqual(values["memory"][0], 2 * 1024**3)

    @unittest.skipUnless(os.name == "posix", "POSIX file-size limits only")
    def test_file_size_limit_bounds_child_output_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "bounded.bin"
            source = "open(sys.argv[1], 'wb').write(b'x' * (2 * 1024 * 1024))"
            result = subprocess.run(
                [sys.executable, str(HELPER), "--cpu-seconds", "5", "--memory-bytes", str(2 * 1024**3),
                 "--file-bytes", "4096", "--", sys.executable, "-c", "import sys; " + source, str(target)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertLessEqual(target.stat().st_size, 4096)

    @unittest.skipUnless(os.name == "posix", "process-group behavior is POSIX-specific")
    def test_drain_deadline_kills_descendant_that_holds_pipe_open(self):
        child = "import time; time.sleep(2)"
        parent = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); "
            "sys.stdout.write('parent exited')"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(BulletinImportError, "time limit while draining output"):
            _run_text([sys.executable, "-c", parent], timeout=0.3, max_bytes=1024)
        self.assertLess(time.monotonic() - started, 1.5)

    @unittest.skipUnless(os.name == "posix", "process-group behavior is POSIX-specific")
    def test_diagnostic_drain_deadline_kills_descendant_that_holds_pipe_open(self):
        child = "import time; time.sleep(2)"
        parent = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', " + repr(child) + "])"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(BulletinImportError, "time limit while draining diagnostics"):
            _run([sys.executable, "-c", parent], timeout=0.3)
        self.assertLess(time.monotonic() - started, 1.5)


if __name__ == "__main__":
    unittest.main()
