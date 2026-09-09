#!/usr/bin/env python3
"""
Impose a sequential US Letter PDF as 2-up saddle-stitch spreads on
11x17 (tabloid) landscape sheets.

Page count is padded to a multiple of 4 with blanks. Two letter pages
(8.5 x 11 = 612 x 792 pt) fit an 11x17 landscape sheet (1224 x 792 pt)
exactly, so no scaling occurs.

Print the output double-sided, FLIP ON SHORT EDGE, then fold the stack
in half and staple on the fold.

Usage:
    python3 impose_booklet.py <input.pdf> [output.pdf]
"""

import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter, PageObject, Transformation

SHEET_W, SHEET_H = 1224.0, 792.0  # 17in x 11in in points
PAGE_W = 612.0                     # 8.5in


def impose(src: Path, dst: Path):
    reader = PdfReader(str(src))
    n_real = len(reader.pages)
    n = ((n_real + 3) // 4) * 4
    writer = PdfWriter()

    # Pad with blanks BEFORE the final page, so the designed back page
    # lands on the booklet's true back cover.
    order = list(range(1, n_real)) + [0] * (n - n_real) + [n_real]
    if n_real == n:
        order = list(range(1, n + 1))

    def place(sheet, slot, x_offset):
        """slot is 1-based within the padded sequence; 0 means blank."""
        page_no = order[slot - 1]
        if page_no:
            page = reader.pages[page_no - 1]
            sheet.merge_transformed_page(
                page, Transformation().translate(tx=x_offset, ty=0))

    for j in range(n // 2):
        if j % 2 == 0:
            left, right = n - j, j + 1
        else:
            left, right = j + 1, n - j
        sheet = PageObject.create_blank_page(width=SHEET_W, height=SHEET_H)
        place(sheet, left, 0)
        place(sheet, right, PAGE_W)
        writer.add_page(sheet)

    with open(dst, "wb") as f:
        writer.write(f)
    print(f"Imposed booklet: {dst}")
    print(f"  {n_real} pages ({n} with blanks) -> {n // 2} sides on "
          f"{n // 4} sheets of 11x17")
    print("  Print double-sided, flip on SHORT edge, fold, saddle-stitch.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = Path(sys.argv[1])
    dst = (Path(sys.argv[2]) if len(sys.argv) > 2
           else src.with_name(src.stem + "-booklet-11x17.pdf"))
    impose(src, dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
