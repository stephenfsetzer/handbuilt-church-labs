# Private editing plan

Paths in the plan are relative to its private run folder or absolute local
paths. The helper rejects run folders inside the public plugin. Values below
are synthetic examples, not defaults for a real church.

For a supplied or already obtained local recording, use `adopt --run-dir
<folder> --path <recording> --url <durable-source-url>` to save its acquisition
hash without copying or downloading it again. `acquire` can then verify and
reuse that same recording.

```json
{
  "church": {"name": "Example Church", "website": "https://example.invalid"},
  "source": {"path": "source/service.mp4", "url": "https://example.invalid/service"},
  "sermon": {
    "start": 1200, "end": 1800,
    "first_word": 1202, "last_word": 1797,
    "boundary_evidence": "Invocation begins at 20:02; final Amen ends at 29:57. Boundary clips inspected."
  },
  "labels": {
    "title": {"text": "An invitation to hope", "status": "editorial", "evidence": "Repeated theme in the sermon"},
    "preacher": {"text": "The Rev. Alex Example", "status": "verified", "evidence": "Service bulletin names the preacher", "source": "https://example.invalid/bulletin"},
    "scripture": {"text": "Luke 17:5-10", "status": "verified", "evidence": "Recorded Gospel and bulletin agree"},
    "service_date": {"text": "October 4, 2026", "status": "verified", "evidence": "Service bulletin cover"},
    "sunday": {"text": "A Sunday sermon", "status": "unknown", "evidence": "Liturgical designation not established"}
  },
  "brand": {"background": "#193a48", "accent": "#d8ac68", "foreground": "#fffaf0", "heading_font": "Georgia", "body_font": "Arial"},
  "assets": {"portrait": "assets/preacher.jpg", "portrait_position": "50% 25%", "logo": "assets/logo.png"},
  "video": {"width": 1920, "height": 1080, "intro_seconds": 2.5, "outro_seconds": 3, "lower_start": 7, "lower_duration": 10},
  "review_notes": ["Captions need parish review."]
}
```

Supported label statuses: `verified`, `provisional`, `unknown`, and `editorial`.
Every populated label needs evidence. Only verified factual labels appear in
video artwork; editorial titles may appear. Unknown/provisional labels appear
with their status on the review page. A church-stated Sunday can be verified
as the parish's label while a conflicting derived lectionary label stays omitted.
Explain the distinction in review notes. Do not hide disagreements.

The rendering helper binds the source hash, editing settings, and video artwork
to a render receipt. Verification also records captions and review-page hashes;
observations refer to those verified outputs.
Changing an input invalidates prior readiness. `status --run-dir <folder>`
reports the current state rather than trusting file presence.

Render artwork with an installed Playwright module:

```bash
node <skill>/scripts/render_artwork.cjs --run-dir <folder> \
  --playwright-module <installed-playwright-path> --channel chrome
```

The renderer also writes `assets/layout.json`, an object keyed by page
(`thumbnail`, `intro`, `outro`, `lower-third`). Each page has `canvas`
(`[width, height]`) and `elements`, a map from element name to `{x, y, w, h}` in
that page's pixels. Text boxes are tight around the words, and a text element
also carries `lines`, one box per line, which the play-button check uses. Any other renderer
must produce the same file, because `verify` and `review` depend on it.

`assets/fonts.css` is optional and can define local font faces. Keep any font
licensing files in the private church folder. Without custom fonts, the artwork
uses the selected system families.

Transcription JSON accepts Whisper-style `segments`, each with a `words` array
of objects containing `start`, `end`, and `word`. `--origin-seconds` is the
source-video timestamp corresponding to transcription time zero. The helper
includes words inside the selected sermon and offsets for the opening card.
The browser caption file uses a higher position for cues that overlap the name
panel. Downloadable SRT captions retain normal timing without browser layout
instructions; check their placement when uploading to another player.

After mechanical verification, record actual observations in private JSON:

```json
{
  "desktop_playback": true,
  "mobile_playback": true,
  "seeking": true,
  "opening_complete": true,
  "ending_complete": true,
  "caption_panel_clear": true,
  "thumbnail_readable": true,
  "notes": "Inspected opening, name panel with captions, ending, and mobile player."
}
```

```bash
python3 <skill>/scripts/sermon_video.py review --plan <folder>/plan.json \
  --observations <folder>/review-observations.json
```

These observations are an agent's recorded checks, not parish approval.
`ready_for_review` never means approved or published. The page keeps caption
draft status and factual uncertainty visible.
