---
title: Note Workflow
description: End-to-end lifecycle from a URL, local media file, or transcript to a Markdown note.
---

# Note Workflow

## Input modes

- Video URL: the backend downloads the remote media and runs the normal transcription pipeline
- Local audio/video: the browser uploads media with `multipart/form-data`, then the backend transcribes it
- Local transcript: the browser uploads `TXT`, `MD`, `SRT`, `VTT`, or `JSON`, and the backend skips STT

## Lifecycle

1. Submit a URL, local media, or transcript generation request
2. Create a task directory under `output/`
3. Download remote media, stage the uploaded file, or parse the uploaded transcript
4. Transcribe media input or skip STT for transcript-first input
5. Generate Markdown with the configured model
6. Inject key moments, timestamps, and screenshots when source media is available
7. Persist artifacts and save the note record
