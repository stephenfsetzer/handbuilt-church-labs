# Supplied document and image limits

Handbuilt checks supplied files before expensive decoding and stops work that
exceeds its processing budgets. Explain a rejected file in church language and
ask for a smaller or simpler copy. Do not turn limits off to force an import.

## Bulletin PDFs

- Source PDF: at most 32 MiB, checked before reading or snapshotting it.
- Pages: 1 to 100. Render resolution: 72 to 300 DPI.
- Page rendering: at most 50 million pixels per page, 20,000 pixels on either
  side, and 100 million pixels across the document.
- Rendered page output: at most 400 MiB in total.
- Embedded images: at most 100 per page and 1,000 per document, with a
  25 million pixel per-image limit and a 256 MiB aggregate output budget.
  Raw images, masks and inline images are checked before decoding. The walk
  includes annotation appearances, tiling patterns, Type3 font programs and
  transparency groups. All pages pass preflight before image extraction begins.
  The estimated decoded artwork budget is also 256 MiB across the document.
  Unsafe artwork blocks the import before Poppler rendering; ask for a simpler copy.
- Per-page artwork inspection stops at 4,000 graph nodes, 500 resource entries,
  32 nesting levels, 100,000 content operations or 64 MiB of decoded content streams.
- Extracted text: at most 1 MiB per page and 16 MiB in total.
- PDF inspection runs in a separate process with a 30 second wall limit.
  POSIX hosts also have a 25 second CPU budget. Linux hosts with address-space
  limits have a 2 GiB parser memory budget.
- Each Poppler operation has a 30 second wall limit, including pipe draining.
  POSIX hosts also limit CPU to 25 seconds and individual output files to 256 MiB;
  Linux hosts with address-space limits cap memory at 2 GiB. Limits are applied
  in an isolated exec helper. A timeout terminates the POSIX process group.
  Captured diagnostics stay within 4 KiB; extracted text is streamed with a byte cap.

Windows retains file, page, pixel, output and wall limits. macOS also has the
POSIX CPU and file-size limits. Neither platform has an OS-enforced parser
address-space limit in this release. Existing path confinement, source snapshots
and per-image failure reporting still apply.

## Images and fonts

- Supplied raster images and individual font files: at most 16 MiB.
- Raster images: positive dimensions and at most 16 million pixels, checked
  from the header before verification, loading or conversion.
- Accepted raster decoders are PNG, JPEG, WebP, GIF, BMP and TIFF. A workflow
  can restrict that set further to match its supported file extensions.
- Pillow decompression-bomb warnings and errors reject the image.
- Brand image imports, provider downloads and base64 image results have byte
  caps before decoding. Requests still use the existing provider boundaries.
- Brand image requests accept at most eight references or imports and 64 MiB
  of encoded input in total. Prepared reference images also have a 64 MiB
  aggregate cap before a provider request.
- Sermon-logo conversion works in bounded tiles rather than allocating Python
  lists for the entire image. SVG logos keep their existing vector path.
- Brand guides have a 1 MiB source limit. Their font files must stay inside
  the private church folder and cannot be symbolic links.

WOFF2 remains supported with the patched Brotli dependency. Updating only a
system codec does not repair a different codec bundled with a Python wheel;
verify the actual runtime artifacts when changing package pins.
