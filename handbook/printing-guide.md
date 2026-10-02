# Printing Guide

Every bulletin build produces two PDFs in the week's folder:

1. The `-booklet-11x17.pdf` file is pre-imposed for booklet printing.
   Print it on 11x17 paper, double-sided, FLIP ON SHORT EDGE. Do not
   also enable the printer's booklet mode. Fold the stack in half and
   staple on the fold.
2. The plain sequential PDF is letter-size pages in reading order.
   Use it on screens, or hand it to a copier that has its own booklet
   mode and let the machine do the imposition.

Use one path or the other, never both at once. If a test print comes
out with pages in the wrong order, the duplex flip edge is the usual
culprit: it must be short edge for the imposed file.

## Printing the page-by-page PDF as a booklet

When a bulletin is set to print as a folded booklet, the page-by-page
PDF always has a multiple of 4 pages (8, 12, 16, and so on). That is
the number a folded booklet needs. So if you print the page-by-page
PDF with Adobe Acrobat's Booklet setting, you get the same booklet as
the 11x17 file: no blank pages are added, and the back page stays on
the back.

Page 2, the inside of the front cover, is sometimes left blank on
purpose. This is a normal booklet blank that lets the service start on
a right-hand page. The bulletin's review summary says when it was
used. A church that never wants it can turn it off with the
`allow_blank_inside_cover` preference.
