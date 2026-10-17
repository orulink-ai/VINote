---
title: Quickstart
description: Fastest way to run VINote locally and make the first call.
---

# Quickstart

## Run the app

Backend:

```bash
pip install -r requirements.txt
python main.py
```

Frontend:

```bash
cd frontend
npm install
npm run web:dev
```

Docs:

```bash
cd docs
npm install
npm run docs:dev
```

Default local addresses:

- App: `http://localhost:3100`
- Backend API: `http://127.0.0.1:8900`
- Swagger: `http://127.0.0.1:8900/docs`
- Docs site: `http://localhost:3101`

## First browser workflow

1. Sign in
2. Click `New`
3. Choose a source mode: video URL, local audio/video file, or local transcript
4. Paste the URL or upload a local file
5. Pick a summary mode and start generation
6. Wait for the task to finish
7. Open the generated note in the editor

## First API workflow

1. Sign in first and keep the HttpOnly session cookie
2. Call `POST /api/generate` for URL input
3. Call `POST /api/generate_from_upload` for local media or transcript uploads
4. Poll `GET /api/task/{task_id}`
5. Save or read notes through `/api/notes`
