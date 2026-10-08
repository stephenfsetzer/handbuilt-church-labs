#!/usr/bin/env python3
"""Serve a private review locally with video byte-range support."""
import argparse
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def handler_for(root):
    root = Path(root).resolve()
    class ReviewHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_file(False)

        def do_GET(self):
            self.send_file(True)

        def send_file(self, body):
            relative = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).lstrip("/") or "review.html"
            target = (root / relative).resolve()
            if root not in target.parents or not target.is_file():
                self.send_error(404)
                return
            if any(part.startswith(".") for part in target.relative_to(root).parts):
                self.send_error(404)
                return
            size = target.stat().st_size
            start, end, partial = 0, size - 1, False
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or not any(match.groups()):
                    self.send_error(416)
                    return
                a, b = match.groups()
                if a:
                    start = int(a); end = min(int(b), size - 1) if b else size - 1
                else:
                    start = max(0, size - int(b)); end = size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                partial = True
            self.send_response(206 if partial else 200)
            media_types = {".vtt": "text/vtt", ".srt": "application/x-subrip", ".mp4": "video/mp4"}
            self.send_header("Content-Type", media_types.get(target.suffix.lower()) or mimetypes.guess_type(target)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if body:
                try:
                    with target.open("rb") as stream:
                        stream.seek(start)
                        remaining = end - start + 1
                        while remaining > 0:
                            chunk = stream.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk); remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def log_message(self, format, *args):
            pass
    return ReviewHandler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    root = Path(args.run_dir).expanduser().resolve()
    if not (root / "review.html").is_file():
        parser.error("The review page has not been prepared.")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(root))
    url = f"http://127.0.0.1:{server.server_port}/review.html"
    (root / "preview-url.txt").write_text(url + "\n")
    print(url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
