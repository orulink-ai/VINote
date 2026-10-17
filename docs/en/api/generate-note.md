---
title: Generate Note
description: Create a note-generation task from a URL or upload input.
---

# Generate Note

Common async endpoints:

- `POST /api/generate`
- `POST /api/generate_from_upload`

Common sync endpoints:

- `POST /api/generate_sync`
- `POST /api/generate_from_upload_sync`

Use JSON for URL input. Use `multipart/form-data` for local media or transcript uploads. When `source_type=transcript`, the backend skips STT and moves straight into summarization.
