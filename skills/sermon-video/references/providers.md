# Recording sources

Keep provider-specific acquisition here. After obtaining a local recording,
use the same plan, editing, artwork, and review workflow.

## YouTube

Discover the channel through the official parish website or saved church
settings. Choose a completed service, not an upcoming stream. Save the video
ID and metadata. Prefer the original church file or owner download when
available. Studio downloads can be lower resolution than the original.

- [Owner downloads](https://support.google.com/youtube/answer/56100)
- [Upload API](https://developers.google.com/youtube/v3/docs/videos/insert)
- [Custom thumbnail API](https://developers.google.com/youtube/v3/docs/thumbnails/set)

The helper uses the installed yt-dlp for supported public acquisition when
appropriate to the authorized task. It does not obtain credentials or supply
access to private channels. Obtain account access through the host's supported
account routing, never by copying a personal browser profile into this skill.

### When a YouTube download stops with HTTP 403

Symptom: the captions download, then the video stops with
`HTTP Error 403: Forbidden` after a few megabytes, at the same point on every
retry. YouTube hides its video addresses behind a small JavaScript puzzle.
yt-dlp 2025.11.12 and later solve it with two things: a JavaScript runtime
(a program that runs JavaScript outside a browser, such as Deno or Node.js)
and its `yt-dlp-ejs` helper scripts. Without both, YouTube refuses the video.

Run `doctor` and read its `downloader` section. It reports the yt-dlp version,
the JavaScript runtime yt-dlp turned on, whether `yt-dlp-ejs` is installed,
and a fix when something is missing. Typical fixes:

- Update yt-dlp with its helpers: `pip install -U "yt-dlp[default]"`, or
  `brew upgrade yt-dlp` when Homebrew installed it.
- Install Deno (`brew install deno`) or Node.js.

yt-dlp turns on only Deno by itself. When Deno is missing and Node.js or Bun
is installed, the helper passes `--js-runtimes node` (or `bun`) for you, so a
manual run of yt-dlp needs the same option. Other providers and local
recordings do not need any of this.

## Vimeo

Inspect the official embedded video or parish library. Use enabled downloads,
an original church file, or an authenticated API file link for an eligible
account. Expiring file links are acquisition inputs, not durable website URLs.

- [Enabled downloads](https://help.vimeo.com/hc/en-us/articles/12426502581265-How-to-download-a-video-on-Vimeo)
- [API video files](https://developer.vimeo.com/api/files/video-links)

yt-dlp refuses vimeo.com pages without a sign-in, so `acquire` reads Vimeo
through `player.vimeo.com/video/<id>` (with `?h=` for an unlisted video). A
video set to play only on the church's website is refused there with 401 or
403; `acquire` checks for that first and stops before downloading. The church's
own signed-in account (`--cookies-from-browser`, with the pastor's permission)
or the original file are the two ways forward.

Do not assume a Vimeo account's plan supports direct file access. Record the
durable video page URL separately from a temporary media URL.

## BoxCast and other embedded libraries

The website may load a player using JavaScript rather than an iframe. Discovery
recognizes `boxcast-widget-<channel>` and `loadChannel` identifiers. Inspect the
rendered library or public channel response to select a past broadcast.
The helper can list public BoxCast broadcasts with:

```bash
python3 <skill>/scripts/sermon_video.py boxcast --channel <channel-id> \
  --output <run-folder>/source/broadcasts.json
```

The result contains broadcast IDs, titles, dates, and durable viewer URLs.
Inspect attached broadcast metadata for a bulletin. The installed downloader
can obtain a supported public viewer URL. Private/ticketed material requires
authorized access; this helper never removes those restrictions.

For another provider, inspect its actual public player and supported media
access. Record the acquired file and provider evidence in the same plan. Add
another provider helper only when real use demonstrates the need.

## Local file

Use a supplied recording directly. Keep its original location unchanged and
record its hash. A local file must still have evidence for the church and sermon
labels; a filename is not proof of the service date or preacher.
