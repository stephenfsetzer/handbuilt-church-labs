# Sermon video

Sermon video turns a recorded service into a short video of just the sermon,
ready for you to review. It works on your computer and does not upload or
publish anything.

Start it when the service recording is online or on your computer:

```text
Prepare this Sunday's sermon video.
```

## What it needs

- **The recording.** Give the agent your church's video page, a link to the
  service on YouTube or Vimeo, or a recording file on your computer. The agent
  uses only recordings that are public or that your church can access.
- **Tools on your computer.** The agent checks for FFmpeg (a free video
  editing tool), a downloader for online recordings, and a browser to draw the
  artwork. It tells you what is missing before it starts.
- **Your church's look.** Your saved colors and logo, and a portrait of the
  preacher if you have one.

## What happens

1. The agent finds the full service and saves it in your church folder under
   `sermon-videos/`.
2. It finds where the sermon begins and ends, keeping any opening prayer and
   the final Amen. When the edges are unclear, it shows you the choices.
3. It checks who preached, the Scripture, and the date against the bulletin,
   the recording, or you. It does not guess from a face. Anything it cannot
   confirm stays off the video and is marked on the review page.
4. It proposes a short title and tells you it is a suggestion.
5. It makes the opening card, the name panel, the closing card, and a
   thumbnail, then puts the video together and checks the sound and picture.
6. It drafts captions from the platform's own captions or a transcription.
   Captions are a draft until you read them.
7. It opens a review page with the video, thumbnail, captions, and download
   links.

## What you decide

You decide whether the video is right: the sermon's edges, the title, the
labels, and the captions. A review page marked ready means the checks passed,
not that the sermon is approved or published. Posting the video is a separate
step you take.

## Saving space

A full service recording is large. Once the review is recorded, the agent
keeps a copy of just the sermon and removes the full recording it downloaded.
Ask it to keep the full recording if you want it. A recording you supplied
yourself is never removed. When you tell the agent the sermon is published, it
removes the sermon copy as well.
