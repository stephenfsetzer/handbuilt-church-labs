#!/usr/bin/env python3
"""Prepare private sermon review packages with reproducible media checks."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from string import Template

SKILL = Path(__file__).resolve().parents[1]
PLUGIN = SKILL.parents[1]
OBSERVATIONS = ("desktop_playback", "mobile_playback", "seeking", "opening_complete",
                "ending_complete", "caption_panel_clear", "thumbnail_readable")
# Measured on a 12 minute sermon with two different ffmpeg builds (7.1 and 8.1.1). At 192 kbps the audio
# came out 31 to 34 dB from the original and differed by build; at 320 kbps both builds reached 45 dB or
# better, so the build stops mattering for about 7 MB more per sermon. A finished file that falls below
# the floor, or whose sound is even one audio frame out of step with the picture (about -3 dB), is rejected.
AUDIO_BITRATE = "320k"
AUDIO_FIDELITY_DB = 30
UNIFORM_AUDIO = "aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def private_dir(path):
    path = Path(path).expanduser().resolve()
    if path == PLUGIN or PLUGIN in path.parents:
        raise ValueError("Church files must be outside the public plugin.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def local(root, value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def fetch(url):
    validate_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def validate_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP or HTTPS source URL without embedded credentials.")


def discover_candidates(text, page_url):
    results = []
    for raw in re.findall(r'''(?:src|href)\s*=\s*["']([^"']+)["']''', text, re.I):
        url = urllib.parse.urljoin(page_url, html.unescape(raw))
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in ("youtu.be", "youtube.com", "www.youtube.com", "www.youtube-nocookie.com"):
            results.append({"provider": "youtube", "url": url})
        elif host in ("vimeo.com", "www.vimeo.com", "player.vimeo.com"):
            results.append({"provider": "vimeo", "url": url})
        elif host in ("boxcast.tv", "www.boxcast.tv"):
            results.append({"provider": "boxcast", "url": url})
        elif urllib.parse.urlparse(url).path.lower().endswith((".mp4", ".m3u8", ".mov")):
            results.append({"provider": "direct", "url": url})
    channels = re.findall(r"boxcast-widget-([a-z0-9]{20})", text)
    channels += re.findall(r'''loadChannel\s*\(\s*["']([a-z0-9]{20})''', text)
    for channel in channels:
        results.append({"provider": "boxcast", "channel": channel, "page_url": page_url})
    return list({json.dumps(item, sort_keys=True): item for item in results}.values())


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", path], capture_output=True, text=True).stdout)


def plan(path):
    path = Path(path).resolve()
    root = private_dir(path.parent)
    data = load(path)
    if not data.get("church", {}).get("name"):
        raise ValueError("The plan needs a church name.")
    source = local(root, data["source"]["path"])
    if not source.is_file() and not (root / ".receipts/master.json").exists():
        raise ValueError("The source recording is missing.")
    sermon = data["sermon"]
    points = [float(sermon[k]) for k in ("start", "first_word", "last_word", "end")]
    if not all(math.isfinite(p) for p in points) or not (0 <= points[0] < points[1] < points[2] < points[3]):
        raise ValueError("Sermon boundaries must contain the first and last words with buffers.")
    if not sermon.get("boundary_evidence"):
        raise ValueError("Save evidence for the sermon boundaries.")
    for key, label in data.get("labels", {}).items():
        if label.get("status") not in ("verified", "provisional", "unknown", "editorial"):
            raise ValueError(f"Unsupported label status: {key}")
        if label.get("text") and not label.get("evidence"):
            raise ValueError(f"Save evidence for the {key} label.")
        if key != "title" and label.get("status") == "editorial":
            raise ValueError("Only the title can be an editorial label.")
    video = {"width": 1920, "height": 1080, "intro_seconds": 2.5, "outro_seconds": 3,
             "lower_start": 7, "lower_duration": 10, **data.get("video", {})}
    if (video["width"], video["height"]) not in ((1920, 1080), (1280, 720)):
        raise ValueError("Choose 1920x1080 or 1280x720 video.")
    for key in ("intro_seconds", "outro_seconds", "lower_start", "lower_duration"):
        if not math.isfinite(float(video[key])) or video[key] < 0:
            raise ValueError(f"Invalid video setting: {key}")
    data["video"] = video
    data["source"]["path"] = str(source)
    return root, data


def visible(data, key):
    item = data.get("labels", {}).get(key, {})
    allowed = ("verified", "editorial") if key == "title" else ("verified",)
    return item.get("text", "") if item.get("status") in allowed else ""


def escape(value):
    return html.escape(str(value), quote=True)


def knock_out_light_background(source, target):
    """Make a dark mark on an opaque light background transparent, keeping its own colors.

    A logo saved as a flat image shows as a pale box on any colored card. Returns True when the logo
    was converted and saved to target, and False when it is left alone (already transparent, no light
    background, or Pillow is unavailable). Written without numpy, which the managed runtime does not have."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return False
    try:
        image = Image.open(source)
    except UnidentifiedImageError:       # a vector logo (SVG) is drawn by the browser as it is
        return False
    if image.mode in ("RGBA", "LA", "P") and image.convert("RGBA").getchannel("A").getextrema()[0] < 250:
        return False
    rgb = image.convert("RGB")
    width, height = rgb.size
    edge = [rgb.getpixel(point) for x in (0, width // 2, width - 1) for point in ((x, 0), (x, height - 1))]
    edge += [rgb.getpixel(point) for y in (height // 2,) for point in ((0, y), (width - 1, y))]
    if not all(min(pixel) >= 240 for pixel in edge):
        return False
    pixels = list(rgb.get_flattened_data() if hasattr(rgb, "get_flattened_data") else rgb.getdata())   # getdata is going away in Pillow 14
    darkest = min(min(pixel) for pixel in pixels)          # the mark's own ink, so a gray mark stays fully opaque
    if darkest > 200:
        return False
    span = 255 - darkest
    converted = []
    for red, green, blue in pixels:
        alpha = min(1.0, (255 - min(red, green, blue)) / span)
        if alpha < .03:
            converted.append((0, 0, 0, 0))
            continue
        converted.append(tuple(max(0, min(255, round((value - 255 * (1 - alpha)) / alpha))) for value in (red, green, blue))
                         + (round(alpha * 255),))
    result = Image.new("RGBA", rgb.size)
    result.putdata(converted)
    bounds = result.getchannel("A").getbbox()
    (result.crop(bounds) if bounds else result).save(target)
    return True


def thumbnail_title_size(title):
    """The thumbnail title's size in pixels: smaller for a longer title, so it stays within three lines of its column."""
    return 76 if len(title) <= 24 else 64 if len(title) <= 40 else 56


def artwork(root, data):
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    if not (assets / "fonts.css").exists():           # the pages import it; without it the system fonts apply
        (assets / "fonts.css").write_text("/* No custom fonts. The system fonts named in the plan are used. */\n")
    values = {"church": escape(data["church"]["name"]),
              "title": escape(visible(data, "title") or "A Sunday sermon"),
              "preacher": escape(visible(data, "preacher")),
              "scripture": escape(visible(data, "scripture")),
              "sunday": escape(visible(data, "sunday")),
              "date": escape(visible(data, "service_date"))}
    brand = {"background": "#193a48", "accent": "#d8ac68", "foreground": "#fffaf0",
             "heading_font": "Georgia", "body_font": "Arial", **data.get("brand", {})}
    for key in ("background", "accent", "foreground"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", brand[key]):
            raise ValueError(f"Use a six-digit hex color for {key}.")
    for key in ("heading_font", "body_font"):
        if not re.fullmatch(r"[\w ,'-]+", brand[key]):
            raise ValueError("Use a plain font family name.")
    values.update(brand)
    for key in ("portrait", "logo"):
        name = data.get("assets", {}).get(key)
        if name:
            source = local(root, name)
            if not source.is_file():
                raise ValueError(f"Missing {key} asset.")
            target = assets / ("review-" + key + source.suffix.lower())
            if key == "logo" and knock_out_light_background(source, assets / "review-logo.png"):
                target = assets / "review-logo.png"
                if source.suffix.lower() != ".png":
                    (assets / ("review-logo" + source.suffix.lower())).unlink(missing_ok=True)
            elif source != target:
                shutil.copy2(source, target)
            values[key] = escape("assets/" + target.name)
        else:
            values[key] = ""
    position = data.get("assets", {}).get("portrait_position", "50% 30%")
    if not re.fullmatch(r"\d{1,3}% \d{1,3}%", position):
        raise ValueError("Portrait position needs two percentages.")
    values["portrait_position"] = position
    values["portrait_html"] = f'<img class="portrait" src="{values["portrait"]}" alt="">' if values["portrait"] else ""
    values["logo_html"] = f'<img class="logo" src="{values["logo"]}" alt="">' if values["logo"] else f'<div class="church">{values["church"]}</div>'
    values["church_footer"] = values["church"] if values["logo"] else ""      # without a logo the name is already at the top
    values["title_size"] = str(thumbnail_title_size(visible(data, "title") or "A Sunday sermon"))
    values["metadata"] = escape(" · ".join(filter(None, [visible(data, k) for k in ("scripture", "sunday", "service_date")])))
    values["panel_metadata"] = escape(" · ".join(filter(None, [visible(data, k) for k in ("scripture", "service_date")])))
    for name in ("thumbnail", "intro", "outro", "lower-third"):
        template = Template((SKILL / "assets" / (name + ".html")).read_text())
        (root / (name + ".html")).write_text(template.substitute(values), encoding="utf-8")
    review_page(root, data, values)


def review_page(root, data, values):
    labels = []
    for key, label in data.get("labels", {}).items():
        if label.get("text"):
            labels.append(f'<dt>{escape(key.replace("_", " "))} <small>{escape(label["status"])}</small></dt><dd>{escape(label["text"])}</dd>')
    notes = list(data.get("review_notes", []))
    notes.extend(f'{k.replace("_", " ").capitalize()}: {v.get("evidence", "Not established")}'
                 for k, v in data.get("labels", {}).items() if v.get("status") in ("unknown", "provisional"))
    values = {**values, "labels": "".join(labels), "notes": "".join(f"<li>{escape(n)}</li>" for n in notes),
              "source_url": escape(data["source"].get("url", data["church"].get("website", ""))),
              "ending": str(max(0, data["sermon"]["end"] - data["sermon"]["start"] + data["video"]["intro_seconds"] - 20)),
              "panel": str(data["video"]["intro_seconds"] + data["video"]["lower_start"] + 1)}
    if values["source_url"]:
        validate_url(html.unescape(values["source_url"]))
    values["caption_track"] = '<track kind="captions" src="sermon.en.vtt" srclang="en" label="English (review draft)">' if (root / "sermon.en.vtt").exists() else ""
    values["caption_links"] = '<a href="sermon.en.srt" download>Download captions</a><a href="sermon-transcript.txt">Read transcript</a>' if (root / "sermon.en.srt").exists() else ""
    values["caption_notice"] = "Captions are a draft for parish review." if values["caption_track"] else "Captions are not available in this review copy."
    (root / "review.html").write_text(Template((SKILL / "assets/review.html").read_text()).substitute(values), encoding="utf-8")
    (root / "upload-copy.txt").write_text(visible(data, "title") + "\n\n" + data["church"]["name"] + "\n" +
                                        "\n".join(f'{k}: {v.get("text", "")} ({v["status"]})' for k, v in data.get("labels", {}).items()) +
                                        "\n\n" + "\n".join(notes) + "\n", encoding="utf-8")


def timestamp(seconds, separator="."):
    n = round(seconds * 1000)
    h, n = divmod(n, 3600000)
    m, n = divmod(n, 60000)
    s, ms = divmod(n, 1000)
    return f"{h:02}:{m:02}:{s:02}{separator}{ms:03}"


CAPTION_SUFFIXES = (".json3", ".vtt", ".srt")
TIMESTAMP = r"(?:\d+:)?\d{2}:\d{2}[.,]\d{3}"


def seconds_from(stamp):
    parts = stamp.replace(",", ".").split(":")
    return sum(float(part) * 60 ** i for i, part in enumerate(reversed(parts)))


def read_platform_captions(path):
    """A word-timed transcription, in source seconds, from a platform's own caption file.

    YouTube's automatic captions (json3, or WebVTT with inline times) time every word and matched the
    soundtrack within about a tenth of a second on a real sermon. Plain WebVTT or SRT times only each cue,
    so its words are spread across the cue by length. Either way the result is a draft for review."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    timed, spread = [], []            # (start, word) with true times; (start, end, [words]) for cue-level times
    inline = bool(re.search(r"<\d\d:\d\d:\d\d\.\d{3}>", text))
    if path.suffix.lower() == ".json3":
        for event in json.loads(text).get("events", []):
            base = event.get("tStartMs", 0) / 1000
            for seg in event.get("segs") or []:
                timed.append((base + seg.get("tOffsetMs", 0) / 1000, seg.get("utf8", "")))
    else:
        previous = set()              # the lines of the cue before; YouTube's rolling captions repeat them
        for block in re.split(r"\n\n+", text.replace("\r\n", "\n")):     # a line holding one space is not a blank line
            lines = block.strip().split("\n")
            index = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if index is None:
                continue
            found = re.match(rf"\s*({TIMESTAMP})\s*-->\s*({TIMESTAMP})", lines[index])
            if not found:
                continue
            begin, finish, body = seconds_from(found.group(1)), seconds_from(found.group(2)), lines[index + 1:]
            body = [html.unescape(line) for line in body]
            plain = [re.sub(r"^[>\s]+", "", re.sub(r"<[^>]+>", "", line)).strip() for line in body]   # ignore a leading speaker mark
            if inline:
                for line, shown in zip(body, plain):
                    if not shown or shown in previous:
                        continue          # blank, or a line already shown in the cue before
                    if re.search(r"<\d\d:\d\d:\d\d\.\d{3}>", line):
                        pieces = re.split(r"<(\d\d:\d\d:\d\d\.\d{3})>", line)
                        timed.append((begin, re.sub(r"</?c[^>]*>", "", pieces[0])))
                        for stamp, piece in zip(pieces[1::2], pieces[2::2]):
                            timed.append((seconds_from(stamp), re.sub(r"</?c[^>]*>", "", piece)))
                    else:                 # a new line with no inline times, often a single word, begins with its cue
                        timed.extend((begin + .3 * i, word) for i, word in enumerate(shown.split()))
                previous = {shown for shown in plain if shown}
            else:
                cue_words = " ".join(plain).split()
                if cue_words and finish > begin:
                    spread.append((begin, finish, cue_words))
    words, seen = [], set()
    for start, raw in timed:
        for word in re.sub(r"^>+\s*", "", raw.strip()).split():
            if re.fullmatch(r"\[[^\]]*\]", word) or (round(start, 2), word) in seen:
                continue                          # sound labels such as [music], and rolling-caption repeats
            seen.add((round(start, 2), word)); words.append((start, None, word))
    for begin, finish, cue_words in spread:
        weights = [len(word) + 1 for word in cue_words]
        cursor = begin
        for word, weight in zip(cue_words, weights):
            share = (finish - begin) * weight / sum(weights)
            words.append((cursor, cursor + share, word)); cursor += share
    if not words:
        raise ValueError("No words could be read from the caption file.")
    words.sort(key=lambda item: item[0])
    items = []
    for i, (start, end, word) in enumerate(words):
        if end is None:                           # true word times give only a start; estimate how long it is said
            following = words[i + 1][0] if i + 1 < len(words) else start + .5
            end = min(start + min(.7, max(.2, .12 + .065 * len(word))), max(following, start + .04))
        items.append({"start": round(start, 3), "end": round(end, 3), "word": " " + word})
    segments, current = [], []
    for i, item in enumerate(items):
        current.append(item)
        following = items[i + 1]["start"] if i + 1 < len(items) else None
        if item["word"].strip().endswith((".", "?", "!")) or following is None or following - item["end"] > 1.1:
            segments.append({"start": current[0]["start"], "end": current[-1]["end"],
                             "text": "".join(w["word"] for w in current).strip(), "words": current})
            current = []
    return {"segments": segments, "provenance": {"origin": path.name, "word_times": "measured" if timed else "estimated from cues",
                                                  "status": "draft for parish review"}}


def caption_cues(data, transcription, origin):
    start, end = data["sermon"]["start"], data["sermon"]["end"]
    offset = data["video"]["intro_seconds"]
    words = []
    for segment in transcription.get("segments", []):
        for item in segment.get("words", []):
            a, b = float(item["start"]) + origin, float(item["end"]) + origin
            if not all(math.isfinite(v) for v in (a, b)) or b < a:
                continue
            if b == a:
                b = min(a + .04, end)
            if b <= a:
                continue
            if start <= a and b <= end:
                words.append({"start": a - start + offset, "end": b - start + offset, "word": item["word"]})
    words.sort(key=lambda w: w["start"])
    if not words:
        raise ValueError("No word timestamps fall inside the sermon.")
    cues, group = [], []
    def flush():
        if group:
            cues.append([group[0]["start"], group[-1]["end"], "".join(w["word"] for w in group).strip()])
            group.clear()
    def split_at_clause():
        """Break a cue that has grown too long at its last comma, so the next cue does not open with an orphan."""
        for i in range(len(group) - 2, 0, -1):
            if group[i]["word"].strip().endswith((",", ";", ":")) and len("".join(w["word"] for w in group[:i + 1])) > 18:
                tail = group[i + 1:]
                del group[i + 1:]
                flush(); group.extend(tail)
                return True
        return False
    for word in words:
        if group and word["start"] - group[-1]["end"] > 1.1:
            flush()
        elif group and (len("".join(w["word"] for w in group) + word["word"]) > 76 or word["end"] - group[0]["start"] > 6):
            if not split_at_clause():
                flush()
        group.append(word)
        if word["word"].strip().endswith((".", "?", "!")) and len("".join(w["word"] for w in group)) > 18:
            flush()
    flush()
    for i, cue in enumerate(cues):
        ceiling = cues[i + 1][0] if i + 1 < len(cues) else end - start + offset
        cue[1] = min(max(cue[1], cue[0] + 1), ceiling)
        if cue[1] <= cue[0]:
            raise ValueError("Overlapping word timestamps prevent readable captions.")
    return cues


def write_captions(root, data, given, origin=0.0):
    """Write the draft captions and transcript, and refresh a review page made before them so it offers them."""
    transcription = read_platform_captions(given) if given.suffix.lower() in CAPTION_SUFFIXES else load(given)
    cues = caption_cues(data, transcription, origin)
    vtt, srt = ["WEBVTT", ""], []
    panel_start = data["video"]["intro_seconds"] + data["video"]["lower_start"]
    panel_end = panel_start + data["video"]["lower_duration"]
    for i, (a, b, text) in enumerate(cues, 1):
        wrapped = "\n".join(textwrap.wrap(text, width=40, break_long_words=False, break_on_hyphens=False))
        position = " line:45%" if a < panel_end and b > panel_start else ""
        vtt.extend([f"{timestamp(a)} --> {timestamp(b)}{position}", wrapped, ""])
        srt.extend([str(i), f'{timestamp(a, ",")} --> {timestamp(b, ",")}', wrapped, ""])
    (root / "sermon.en.vtt").write_text("\n".join(vtt)); (root / "sermon.en.srt").write_text("\n".join(srt))
    (root / "sermon-transcript.txt").write_text("Draft transcript for parish review.\n\n" + "\n\n".join(c[2] for c in cues) + "\n")
    if (root / "review.html").exists():
        artwork(root, data)
    return {"status": "draft_captions_ready", "cues": len(cues)}


MASTER_LEAD = 10.0     # seconds of recording kept on each side of the sermon
MASTER_MATCH_DB = 60   # a stream copy decodes identically, so anything below this is a real mismatch


def receipt_if_present(path):
    return load(path) if Path(path).exists() else {}


def recorded_source_hash(root, data):
    """The hash of the full recording, kept in receipts so they stay valid after the recording is removed."""
    original = Path(data["source"]["path"])
    if original.is_file():
        return digest(original)
    for name, key in (("master", "original_hash"), ("acquisition", "hash")):
        saved = receipt_if_present(root / f".receipts/{name}.json")
        if saved.get(key):
            return saved[key]
    raise ValueError("The recording is missing and no receipt records it.")


def master_info(root, data):
    """The saved sermon master, when it still exists and still matches its receipt."""
    saved = receipt_if_present(root / ".receipts/master.json")
    if not saved or saved.get("removed_at"):
        return None
    media = local(root, saved["path"])
    if not media.is_file() or digest(media) != saved["hash"]:
        return None
    return {**saved, "file": media}


def source_view(root, data):
    """Where to read the sermon from: the full recording, or the saved master once the recording is removed."""
    original, sermon = Path(data["source"]["path"]), data["sermon"]
    if original.is_file():
        return {"path": original, "start": sermon["start"], "end": sermon["end"]}
    master = master_info(root, data)
    if not master:
        raise ValueError("The full recording was removed to save space and no sermon master is saved. "
                         "Download or choose the recording again.")
    if sermon["start"] < master["offset"] or sermon["end"] > master["offset"] + master["duration"]:
        raise ValueError("The sermon now reaches outside the saved master. Download or choose the recording again.")
    return {"path": master["file"], "start": sermon["start"] - master["offset"], "end": sermon["end"] - master["offset"]}


def check_master(original, master, offset, length):
    """Prove the master matches the recording, sound and picture, at three points before the recording can be removed."""
    def compare(args):
        return subprocess.run([str(a) for a in ["ffmpeg", "-hide_banner", "-nostats"] + args], capture_output=True, text=True)
    for t in sorted({round(min(1.0, length / 4), 2), round(length / 2, 2), round(max(0.0, length - 6), 2)}):
        window = min(3.0, length - t)
        sound = compare(["-ss", offset + t, "-t", window, "-i", original, "-ss", t, "-t", window, "-i", master,
                         "-filter_complex", f"[0:a:0]{UNIFORM_AUDIO}[a];[1:a:0]{UNIFORM_AUDIO}[b];[a][b]asdr", "-f", "null", "-"])
        # Compare the same window of pictures as of sound. With a single frame, FFmpeg can stop on a VP9
        # recording before psnr reports its score, and a recording proven identical was then kept.
        picture = compare(["-ss", offset + t, "-t", window, "-i", original, "-ss", t, "-t", window, "-i", master,
                           "-filter_complex", "[0:v:0][1:v:0]psnr=shortest=1:repeatlast=0", "-f", "null", "-"])
        sdr = re.findall(r"SDR ch\d+: (-?[\d.]+|inf) dB", sound.stderr)
        psnr = re.findall(r"average:(-?[\d.]+|inf)", picture.stderr)
        if sound.returncode or picture.returncode or not sdr or not psnr:
            raise ValueError("Could not compare the sermon master with the recording, so the recording was kept.")
        if min(float(value) for value in sdr + psnr) < MASTER_MATCH_DB:
            raise ValueError("The sermon master does not match the recording, so the recording was kept.")


def make_master(root, data):
    """Copy just the sermon, with a little margin, out of the full recording without re-encoding it."""
    original, sermon = Path(data["source"]["path"]), data["sermon"]
    total = float(probe(original)["format"]["duration"])
    begin, stop = max(0.0, sermon["start"] - MASTER_LEAD), min(total, sermon["end"] + MASTER_LEAD)
    (root / "source").mkdir(exist_ok=True)
    target, pending = root / "source/sermon-master.mp4", root / "source/sermon-master.pending.mp4"
    require_space(root, int(original.stat().st_size * (stop - begin) / total * 1.2) + 50_000_000, "the sermon master")
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", begin, "-to", stop, "-i", original,
             "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart", pending])
        length = float(probe(pending)["format"]["duration"])
        check_master(original, pending, begin, length)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    pending.replace(target)
    record = {"path": str(target.relative_to(root)), "hash": digest(target), "offset": begin, "duration": length,
              "original_hash": digest(original), "created_at": datetime.now(timezone.utc).isoformat()}
    save(root / ".receipts/master.json", record)
    return record


def finish_source(root, data, keep=False):
    """Make the full recording safe to remove, then remove it unless the pastor asked to keep it.

    Only a copy this helper downloaded into the run folder is ever removed. A recording the pastor
    supplied is never touched, and nothing is removed unless the master has been proven to match."""
    original, sermon = Path(data["source"]["path"]), data["sermon"]
    if not original.is_file():
        return {"recording": "already_removed", "master_kept": master_info(root, data) is not None}
    master = master_info(root, data)
    if not (master and master["original_hash"] == digest(original) and master["offset"] <= sermon["start"]
            and sermon["end"] <= master["offset"] + master["duration"]):
        make_master(root, data)
    if keep:
        return {"recording": "kept_at_your_request", "master_kept": True}
    ledger = receipt_if_present(root / ".receipts/acquisition.json")
    ours = (ledger.get("method") != "supplied_local_recording" and bool(ledger.get("url"))
            and (root / "source").resolve() in original.resolve().parents)
    if not ours:
        return {"recording": "left_in_place", "master_kept": True,
                "reason": "This recording is your own file, so it was not removed."}
    freed = original.stat().st_size
    acquisition = root / "source/acquisition"
    if acquisition.exists():
        freed += sum(f.stat().st_size for f in acquisition.rglob("*") if f.is_file())
        shutil.rmtree(acquisition)
    original.unlink()
    save(root / ".receipts/retention.json", {"recording_removed_at": datetime.now(timezone.utc).isoformat(), "freed_bytes": freed})
    return {"recording": "removed", "freed_mb": round(freed / 1e6), "master_kept": True}


def mark_published(root, data):
    """The pastor says the sermon is published: the sermon master is no longer needed."""
    saved, master = receipt_if_present(root / ".receipts/master.json"), master_info(root, data)
    freed = 0
    if master:
        freed = master["file"].stat().st_size
        master["file"].unlink()
        save(root / ".receipts/master.json", {**saved, "removed_at": datetime.now(timezone.utc).isoformat()})
    save(root / ".receipts/published.json", {"marked_at": datetime.now(timezone.utc).isoformat(), "freed_bytes": freed})
    return {"status": "marked_published", "master_removed": master is not None, "freed_mb": round(freed / 1e6),
            "full_recording_present": Path(data["source"]["path"]).is_file()}


def fingerprints(root, data):
    names = ("intro.png", "outro.png", "lower-third.png")
    render_plan = {key: data[key] for key in ("source", "sermon", "video")}
    result = {"plan": hashlib.sha256(json.dumps(render_plan, sort_keys=True).encode()).hexdigest(),
              "source": recorded_source_hash(root, data),
              "implementation": digest(Path(__file__))}
    result.update({name: digest(root / "assets" / name) for name in names})
    return result


def render(root, data):
    view = source_view(root, data)
    source = view["path"]
    source_probe = probe(source)
    duration = float(source_probe["format"]["duration"])
    start, end = view["start"], view["end"]
    if end > duration:
        raise ValueError("The sermon ends after the recording.")
    if not any(s["codec_type"] == "audio" for s in source_probe["streams"]):
        raise ValueError("The recording has no audio stream.")
    inputs = fingerprints(root, data)
    receipt_path = root / ".receipts/render.json"
    if receipt_path.exists():
        previous = load(receipt_path)
        if previous.get("inputs") == inputs and (root / "sermon-review.mp4").exists() and previous.get("video_hash") == digest(root / "sermon-review.mp4"):
            return {"status": "reused", **previous}
    receipts = root / ".receipts"
    receipts.mkdir(exist_ok=True)
    common = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    speech_duration = end - start
    measure = run(["ffmpeg", "-hide_banner", "-ss", start, "-i", source, "-t", speech_duration,
                   "-vn", "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                  capture_output=True, text=True)
    match = re.search(r'\{\s*"input_i".*?\}', measure.stderr, re.S)
    if not match:
        raise ValueError("Could not measure sermon audio.")
    levels = json.loads(match.group())
    if not all(math.isfinite(float(levels[k])) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
        raise ValueError("Sermon audio is silent or cannot be normalized.")
    af = loudness_filter(levels)
    video = data["video"]
    w, h = video["width"], video["height"]
    encoding = ["-c:v", "libx264", "-preset", "fast", "-crf", "21", "-threads", "4", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000", "-ac", "2", "-video_track_timescale", "90000"]
    panel_end = video["lower_start"] + video["lower_duration"]
    fade = min(.4, video["lower_duration"] / 3)
    # One pass. Encoding the opening card, the cut, and the closing card as separate audio files and
    # joining them without re-encoding stacks each file's encoder delay and padding, which put the
    # sound about 55 to 60 milliseconds behind the picture. One encode has one delay, which players remove.
    uniform = UNIFORM_AUDIO
    command, graph, segments = [], [], []

    def add_input(*args):
        command.extend(args)
        return sum(1 for item in command if item == "-i") - 1

    def card(name, seconds):
        picture = add_input("-loop", "1", "-framerate", "30", "-t", seconds, "-i", root / "assets" / (name + ".png"))
        silence = add_input("-f", "lavfi", "-t", seconds, "-i", "anullsrc=channel_layout=stereo:sample_rate=48000")
        graph.append(f"[{picture}:v]scale={w}:{h},setsar=1,fps=30,format=yuv420p[{name}v];[{silence}:a]{uniform}[{name}a]")
        segments.append(f"[{name}v][{name}a]")

    if video["intro_seconds"] > 0:
        card("intro", video["intro_seconds"])
    recording = add_input("-ss", start, "-t", speech_duration, "-i", source)
    panel = add_input("-i", root / "assets/lower-third.png")
    graph.append(
        f"[{recording}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[cut];"
        f"[{panel}:v]scale={w}:{h},format=rgba,loop=loop=-1:size=1:start=0,setpts=N/30/TB,"
        f"fade=t=in:st={video['lower_start']}:d={fade}:alpha=1,fade=t=out:st={panel_end-fade}:d={fade}:alpha=1[panel];"
        f"[cut][panel]overlay=0:0:shortest=1:enable='between(t,{video['lower_start']},{panel_end})',format=yuv420p[sermonv];"
        f"[{recording}:a:0]{af},{uniform}[sermona]")
    segments.append("[sermonv][sermona]")
    if video["outro_seconds"] > 0:
        card("outro", video["outro_seconds"])
    graph.append("".join(segments) + f"concat=n={len(segments)}:v=1:a=1[v][a]")
    temporary = root / "sermon-review.pending.mp4"
    run(common + command + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
                            "-t", speech_duration + video["intro_seconds"] + video["outro_seconds"]]
        + encoding + ["-movflags", "+faststart", temporary])
    temporary.replace(root / "sermon-review.mp4")
    for leftover in ("main.mp4", "intro.mp4", "outro.mp4", "concat.txt"):   # from earlier versions
        (receipts / leftover).unlink(missing_ok=True)
    receipt = {"inputs": inputs, "video_hash": digest(root / "sermon-review.mp4"),
               "expected_duration": speech_duration + video["intro_seconds"] + video["outro_seconds"],
               "audio_measurement": levels, "tools": {"ffmpeg": ffmpeg_version()},
               "rendered_at": datetime.now(timezone.utc).isoformat()}
    save(receipt_path, receipt)
    return receipt


# Zones to keep clear, each measured or published. Fractions are of the height of the video the zone applies to.
PANEL_SAFE_BOTTOM = 0.95      # the name panel sits at the lower left, but keeps at least this margin from the bottom edge
CAPTION_ZONE_BOTTOM = 0.60    # captions raised to 45 percent run to about this far down on a phone
# Where the review page's play button sits over the thumbnail, as fractions of the picture (left, top, right,
# bottom). It is centered across, on the seam between the words and the photo, and set a little below the middle
# (56 percent down) so it clears the end of a title's first line. Measured in Chrome: the full button on a desktop
# player (1440 and 1024 px wide) and the round one on a phone (390 and 340 px wide).
PLAY_ZONES = {"desktop": (0.40, 0.505, 0.60, 0.615), "phone": (0.43, 0.44, 0.57, 0.68)}
BADGE_ZONE = (130, 70)        # YouTube's duration badge, bottom right of a 1280 by 720 thumbnail (design guidance: about 120 by 60)
THUMBNAIL_MARGIN = 60         # design guidance for a thumbnail; a note, not a failure
LAYOUT_NAMES = {"logo": "logo", "church": "church name", "kicker": "small heading", "title": "title", "meta": "scripture line",
                "portrait": "photo", "footer": "church name", "panel": "name panel", "preacher": "preacher's name"}


def overlay_audit(root):
    """Check the measured positions of everything on the cards, thumbnail, and name panel.

    The renderer writes assets/layout.json (a box for each element, in the pixels of its page). Anything off its
    page, anything overlapping another element, thumbnail words under YouTube's duration badge or under the review
    page's play button, or a name panel too close to the bottom edge or inside the zone raised captions occupy is
    a problem. The thumbnail photo runs to the edges by design, so only the words are held to those zones."""
    path = root / "assets/layout.json"
    if not path.exists():
        return {"status": "not_measured", "problems": [], "notes": []}
    problems, notes = [], []
    def overlap(a, b):
        return min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]) > 2 and min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]) > 2
    for page, entry in load(path).items():
        width, height = entry["canvas"]
        names = list(entry["elements"])
        for name in names:
            box = entry["elements"][name]
            if box["x"] < -2 or box["y"] < -2 or box["x"] + box["w"] > width + 2 or box["y"] + box["h"] > height + 2:
                problems.append(f"On the {page}, the {LAYOUT_NAMES.get(name, name)} runs past the edge. A shorter title may fix it.")
        for i, first in enumerate(names):
            for second in names[i + 1:]:
                if overlap(entry["elements"][first], entry["elements"][second]):
                    problems.append(f"On the {page}, the {LAYOUT_NAMES.get(first, first)} and the {LAYOUT_NAMES.get(second, second)} "
                                    "overlap. A shorter title may fix it.")
        if page == "thumbnail":
            badge = {"x": width - BADGE_ZONE[0], "y": height - BADGE_ZONE[1], "w": BADGE_ZONE[0], "h": BADGE_ZONE[1]}
            plays = [{"x": left * width, "y": top * height, "w": (right - left) * width, "h": (bottom - top) * height}
                     for left, top, right, bottom in PLAY_ZONES.values()]
            for name, box in entry["elements"].items():
                if name == "portrait":
                    continue
                if overlap(box, badge):
                    problems.append(f"On the thumbnail, the {LAYOUT_NAMES.get(name, name)} sits under YouTube's video length badge.")
                if any(overlap(line, play) for line in box.get("lines", [box]) for play in plays):
                    problems.append(f"On the thumbnail, the review page's play button would cover the {LAYOUT_NAMES.get(name, name)}.")
                if box["x"] < THUMBNAIL_MARGIN - 4 or box["y"] < THUMBNAIL_MARGIN - 4 or \
                        box["x"] + box["w"] > width - THUMBNAIL_MARGIN + 4 or box["y"] + box["h"] > height - THUMBNAIL_MARGIN + 4:
                    notes.append(f"On the thumbnail, the {LAYOUT_NAMES.get(name, name)} is within {THUMBNAIL_MARGIN} px of an edge.")
        panel = entry["elements"].get("panel") if page == "lower-third" else None
        if panel:
            if panel["y"] + panel["h"] > PANEL_SAFE_BOTTOM * height + 1:
                problems.append("The name panel sits too close to the bottom edge of the video.")
            if panel["y"] < CAPTION_ZONE_BOTTOM * height - 1:
                problems.append("The name panel reaches the part of the video that raised captions occupy.")
    return {"status": "failed" if problems else "passed", "problems": problems, "notes": notes}


def loudness_filter(levels):
    return (f'loudnorm=I=-18:TP=-1.5:LRA=11:measured_I={levels["input_i"]}:measured_TP={levels["input_tp"]}'
            f':measured_LRA={levels["input_lra"]}:measured_thresh={levels["input_thresh"]}:offset={levels["target_offset"]}:linear=true')


def ffmpeg_version():
    """The version line of the ffmpeg that made the video, kept in the receipt."""
    try:
        first = run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        return "unknown"
    return first.replace("ffmpeg version ", "").split(" Copyright")[0].strip() or "unknown"


def audio_check(root, data, receipt, output):
    """Compare the finished audio with the sermon's own sound, rebuilt without compression.

    Returns the signal-to-distortion ratio in decibels for each channel, or None when this computer's
    ffmpeg cannot measure it. Raises when the audio is badly degraded or out of step with the picture."""
    view = source_view(root, data)
    length = view["end"] - view["start"]
    graph = (f"[0:a:0]{loudness_filter(receipt['audio_measurement'])},{UNIFORM_AUDIO}[reference];"
             f"[1:a:0]{UNIFORM_AUDIO}[finished];[reference][finished]asdr")
    measured = subprocess.run([str(a) for a in ["ffmpeg", "-hide_banner", "-nostats", "-ss", view["start"], "-t", length,
                                                  "-i", view["path"], "-ss", data["video"]["intro_seconds"], "-t", length,
                                                  "-i", output, "-filter_complex", graph, "-f", "null", "-"]],
                              capture_output=True, text=True)
    if measured.returncode != 0 and "No such filter" in measured.stderr:
        return None
    found = re.findall(r"SDR ch\d+: (-?[\d.]+|inf) dB", measured.stderr)
    if measured.returncode != 0 or len(found) < 2:
        raise ValueError("Could not compare the finished audio with the recording.")
    decibels = [min(float(value), 99.0) for value in found]    # identical audio reads as infinite
    if min(decibels) < AUDIO_FIDELITY_DB:
        raise ValueError(f"The finished audio is not close enough to the recording ({min(decibels):.1f} dB; at least "
                         f"{AUDIO_FIDELITY_DB} needed). It may be out of step with the picture or too compressed. Render again.")
    return decibels


def current_render(root, data):
    receipt = load(root / ".receipts/render.json")
    if receipt["inputs"] != fingerprints(root, data) or receipt["video_hash"] != digest(root / "sermon-review.mp4"):
        raise ValueError("The render is stale. Render the changed inputs again.")
    return receipt


def verify(root, data):
    receipt = current_render(root, data)
    output = root / "sermon-review.mp4"
    run(["ffmpeg", "-v", "error", "-xerror", "-i", output, "-f", "null", "-"], capture_output=True)
    media = probe(output)
    duration = float(media["format"]["duration"])
    video = next(s for s in media["streams"] if s["codec_type"] == "video")
    audio = next(s for s in media["streams"] if s["codec_type"] == "audio")
    if abs(duration - receipt["expected_duration"]) > .35:
        raise ValueError("The exported duration does not match the plan.")
    if video["codec_name"] != "h264" or audio["codec_name"] != "aac":
        raise ValueError("Export needs H.264 video and AAC audio.")
    if (video["width"], video["height"]) != (data["video"]["width"], data["video"]["height"]):
        raise ValueError("Export dimensions do not match the plan.")
    fidelity = audio_check(root, data, receipt, output)
    layout = overlay_audit(root)
    if layout["status"] == "failed":
        raise ValueError(" ".join(layout["problems"]))
    captions = root / "sermon.en.vtt"
    cues = []
    if captions.exists():
        def seconds(value):
            a, b, c = value.split(":")
            return float(a) * 3600 + float(b) * 60 + float(c)
        for a, b in re.findall(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})", captions.read_text()):
            cues.append((seconds(a), seconds(b)))
        if not cues or any(a < 0 or a >= b or b > duration for a, b in cues) or any(cues[i][1] > cues[i + 1][0] for i in range(len(cues) - 1)):
            raise ValueError("Caption timestamps are invalid or overlapping.")
    page = root / "review.html"
    if page.exists() and captions.exists() != ('src="sermon.en.vtt"' in page.read_text(encoding="utf-8")):
        raise ValueError("The review page does not match the captions. Run artwork again, then verify.")
    hashes = {name: digest(root / name) if (root / name).exists() else None for name in
              ("sermon-review.mp4", "review.html", "assets/thumbnail.png", "sermon.en.vtt", "sermon.en.srt",
               "sermon-transcript.txt", "upload-copy.txt")}
    if any(hashes[k] is None for k in ("sermon-review.mp4", "review.html", "assets/thumbnail.png", "upload-copy.txt")):
        raise ValueError("The review package is incomplete.")
    result = {"status": "mechanically_verified", "hashes": hashes, "duration": duration,
              "decode": "passed", "caption_cues": len(cues), "audio_fidelity_db": fidelity,
              "overlay_audit": layout["status"], "overlay_notes": layout["notes"],
              "checked_at": datetime.now(timezone.utc).isoformat()}
    save(root / ".receipts/verification.json", result)
    return result


def checked_verification(root, data):
    current_render(root, data)
    verified = load(root / ".receipts/verification.json")
    if any((digest(root / name) if (root / name).exists() else None) != value for name, value in verified["hashes"].items()):
        raise ValueError("Package changed after verification. Verify again.")
    return verified


def record_review(root, data, observations, keep_recording=False):
    checked = checked_verification(root, data)
    if checked.get("overlay_audit") != "passed":
        raise ValueError("The artwork layout has not been measured. Render the artwork with the current renderer, "
                         "render the video, and verify again before marking the package ready.")
    if any(observations.get(k) is not True for k in OBSERVATIONS) or not observations.get("notes"):
        raise ValueError("Record all actual playback and visual observations before marking ready.")
    save(root / ".receipts/review.json", {"status": "ready_for_review", "hashes": checked["hashes"], "observations": observations})
    try:    # the review stands even if the recording could not be made safe to remove
        recording = finish_source(root, data, keep=keep_recording)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        recording = {"recording": "kept", "reason": str(error)}
    return {"status": "ready_for_review", "publication": "local_only", "recording": recording}


def require_space(folder, needed, what):
    free = shutil.disk_usage(folder).free
    if free < needed:
        raise ValueError(f"There is not enough free space for {what}: about {needed / 1e9:.1f} GB is needed and "
                         f"{free / 1e9:.1f} GB is free. Free up some space and try again.")


def download_selector(max_height):
    return f"bv*[height<={max_height}]+ba/b[height<={max_height}]"


def estimate_download_bytes(url, max_height):
    """The provider's own size estimate for the chosen formats, or None when it gives none."""
    try:
        info = json.loads(run(["yt-dlp", "--no-playlist", "--no-update", "--skip-download", "--dump-single-json",
                               "-f", download_selector(max_height), url], capture_output=True, text=True).stdout)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    sizes = [part.get("filesize") or part.get("filesize_approx") for part in (info.get("requested_formats") or [info])]
    return int(sum(sizes)) if sizes and all(sizes) else None


def acquire_recording(root, url, max_height):
    validate_url(url)
    source = root / "source"; source.mkdir(exist_ok=True)
    ledger = root / ".receipts/acquisition.json"
    if ledger.exists():
        saved = load(ledger); media = local(root, saved["file"])
        if saved["url"] == url and media.is_file() and saved["hash"] == digest(media):
            return {"status": "reused", **saved}
    # Peak use is the video and audio parts plus the merged file, then room for the sermon master and the render.
    estimate = estimate_download_bytes(url, max_height)
    require_space(source, int(estimate * 2.2) + 300_000_000 if estimate else 3_000_000_000, "the download")
    pending = source / "acquisition" / hashlib.sha256(url.encode()).hexdigest()[:16]
    pending.mkdir(parents=True, exist_ok=True)
    run(["yt-dlp", "--no-playlist", "--no-update", "--write-info-json", "--write-subs", "--write-auto-subs",
         "--sub-langs", "en.*", "--sub-format", "json3/vtt/best", "--concurrent-fragments", "8", "-f", download_selector(max_height),
         "--merge-output-format", "mp4", "-o", pending / "service.%(ext)s", url], stdout=sys.stderr)
    matches = [f for f in pending.iterdir() if f.suffix in (".mp4", ".mkv", ".webm", ".mov")]
    if len(matches) != 1:
        raise ValueError("The downloader did not produce one complete recording.")
    probe(matches[0])
    media = source / matches[0].name
    shutil.move(str(matches[0]), media)          # move, never copy: a second copy of a service is over half a gigabyte
    for other in pending.iterdir():
        if other.suffix in (".json", ".json3", ".vtt", ".srt"):
            shutil.copy2(other, source / other.name)
    shutil.rmtree(pending)
    try:
        pending.parent.rmdir()
    except OSError:
        pass
    result = {"url": url, "file": str(media.relative_to(root)), "hash": digest(media), "method": "downloaded"}
    save(ledger, result); return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    p = commands.add_parser("discover"); p.add_argument("--url", required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("boxcast"); p.add_argument("--channel", required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("acquire"); p.add_argument("--url", required=True); p.add_argument("--run-dir", required=True); p.add_argument("--max-height", type=int, default=1080)
    p = commands.add_parser("adopt"); p.add_argument("--url", required=True); p.add_argument("--run-dir", required=True); p.add_argument("--path", required=True)
    p = commands.add_parser("status"); p.add_argument("--run-dir", required=True)
    for name in ("artwork", "render", "verify", "captions", "review", "finish", "published"):
        p = commands.add_parser(name); p.add_argument("--plan", required=True)
        if name == "captions":
            p.add_argument("--transcription", required=True)
            p.add_argument("--origin-seconds", type=float, default=0.0,
                           help="Source time of transcription time zero. Platform caption files (.json3, .vtt, .srt) already use source time.")
        if name == "review":
            p.add_argument("--observations", required=True)
        if name in ("review", "finish"):
            p.add_argument("--keep-recording", action="store_true",
                           help="Keep the full service recording instead of removing it once the sermon master is proven.")
    args = parser.parse_args()
    if args.command == "doctor":
        return {"tools": {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "yt-dlp", "node")},
                "artwork_renderer": "Use an available browser renderer or render_artwork.cjs with an installed Playwright module."}
    if args.command in ("discover", "boxcast"):
        output = Path(args.output).resolve(); private_dir(output.parent)
        if args.command == "discover":
            result = {"page_url": args.url, "candidates": discover_candidates(fetch(args.url).decode("utf-8", "replace"), args.url)}
        else:
            if not re.fullmatch(r"[a-z0-9]{20}", args.channel):
                raise ValueError("Invalid BoxCast channel identifier.")
            query = urllib.parse.urlencode({"q": "timeframe:past", "s": "-starts_at", "l": 10})
            records = json.loads(fetch(f"https://rest.boxcast.com/channels/{args.channel}/broadcasts?{query}"))
            result = [{"id": r["id"], "title": r["name"], "starts_at": r["starts_at"], "timeframe": r["timeframe"],
                       "viewer_url": f'https://boxcast.tv/view/{r["channel_id"]}?b={r["id"]}'} for r in records]
        save(output, result); return result
    if args.command == "adopt":
        root = private_dir(args.run_dir)
        media = Path(args.path).expanduser().resolve()
        probe(media)
        result = {"url": args.url, "file": str(media), "hash": digest(media), "method": "supplied_local_recording"}
        save(root / ".receipts/acquisition.json", result)
        return result
    if args.command == "acquire":
        return acquire_recording(private_dir(args.run_dir), args.url, args.max_height)
    if args.command == "status":
        root = private_dir(args.run_dir)
        try:
            _, data = plan(root / "plan.json")
            verified = checked_verification(root, data)
            observations = load(root / ".receipts/review.json")
            if observations["hashes"] != verified["hashes"]:
                raise ValueError("Review observations refer to an older package.")
            return {"status": "ready_for_review", "publication": "local_only", "review_page": str(root / "review.html")}
        except (OSError, KeyError, ValueError) as error:
            return {"status": "needs_preparation_or_checks", "reason": str(error)}
    root, data = plan(args.plan)
    if args.command == "artwork":
        artwork(root, data); return {"status": "artwork_documents_ready", "run_dir": str(root)}
    if args.command == "captions":
        return write_captions(root, data, Path(args.transcription), args.origin_seconds)
    if args.command == "render":
        return render(root, data)
    if args.command == "verify":
        return verify(root, data)
    if args.command == "review":
        return record_review(root, data, load(args.observations), args.keep_recording)
    if args.command == "finish":
        return finish_source(root, data, keep=args.keep_recording)
    if args.command == "published":
        return mark_published(root, data)


if __name__ == "__main__":
    try:
        print(json.dumps(main(), indent=2))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "needs_attention", "reason": str(error)}), file=sys.stderr)
        sys.exit(1)
