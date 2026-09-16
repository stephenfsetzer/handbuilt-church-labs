"""Bounded sample-PDF check, invoked with the managed interpreter by runtime verify."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def check_pdf_tools(tools: dict[str, str]) -> list[str]:
    # Import inside the probe so missing native rendering libraries produce a
    # useful failure, even when package metadata and executable paths exist.
    from PIL import Image
    from pypdf import PdfReader
    from weasyprint import HTML

    checks = []
    with tempfile.TemporaryDirectory(prefix="handbuilt-runtime-check-") as directory:
        root = Path(directory)
        pdf = root / "sample.pdf"
        text = "Handbuilt runtime check"
        HTML(string=f"<html><body><p>{text}</p></body></html>").write_pdf(pdf)
        if len(PdfReader(pdf).pages) != 1:
            raise ValueError("The sample PDF did not contain one page")
        checks.append("render")

        def run(name: str, *args: str) -> str:
            result = subprocess.run([tools[name], *args], capture_output=True, text=True,
                                    timeout=10, check=True)
            checks.append(name)
            return result.stdout

        info = run("pdfinfo", str(pdf))
        if not any(line.split() == ["Pages:", "1"] for line in info.splitlines()):
            raise ValueError("PDF metadata check did not find one page")
        fonts = run("pdffonts", str(pdf)).splitlines()[2:]
        if not fonts or any(len(row.split()) < 6 or row.split()[-5] != "yes" for row in fonts):
            raise ValueError("Sample PDF fonts were not embedded")
        extracted = run("pdftotext", str(pdf), "-")
        if text not in " ".join(extracted.split()):
            raise ValueError("The PDF text check could not recover the sample text")
        run("pdftoppm", "-png", "-r", "36", "-singlefile", str(pdf), str(root / "page"))
        with Image.open(root / "page.png") as image:
            image.verify()
    return sorted(checks)


def main() -> int:
    names = ("pdftoppm", "pdfinfo", "pdffonts", "pdftotext")
    try:
        if len(sys.argv) != len(names) + 1:
            raise ValueError("Pass the four PDF tool paths from the runtime doctor")
        checks = check_pdf_tools(dict(zip(names, sys.argv[1:])))
        print(json.dumps({"ok": True, "checks": checks}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[-800:]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
