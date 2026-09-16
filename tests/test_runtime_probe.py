import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.runtime_probe import check_pdf_tools


TOOLS = {name: shutil.which(name) for name in ("pdftoppm", "pdfinfo", "pdffonts", "pdftotext")}


@unittest.skipUnless(all(TOOLS.values()), "PDF tools are required for the working runtime check")
class RuntimeProbeTests(unittest.TestCase):
    def test_real_render_and_pdf_checks_remove_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("tempfile.tempdir", directory):
                checks = check_pdf_tools(TOOLS)
            self.assertEqual(checks, ["pdffonts", "pdfinfo", "pdftoppm", "pdftotext", "render"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bad_extraction_or_tool_failure_fails_and_cleans_up(self):
        actual_run = subprocess.run
        for fail_process in (False, True):
            with self.subTest(fail_process=fail_process), tempfile.TemporaryDirectory() as directory:
                def broken_text(command, **kwargs):
                    if command[0] == TOOLS["pdftotext"]:
                        if fail_process:
                            raise subprocess.CalledProcessError(1, command, stderr="Tool failed")
                        return subprocess.CompletedProcess(command, 0, "", "")
                    return actual_run(command, **kwargs)
                with mock.patch("tempfile.tempdir", directory), mock.patch("tools.runtime_probe.subprocess.run", side_effect=broken_text):
                    with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                        check_pdf_tools(TOOLS)
                self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
