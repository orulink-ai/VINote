# Repository Guidelines

## Architecture Overview
 VINote is a full-stack video-to-note workspace with three moving parts:

- Backend: FastAPI API for downloading media, receiving local audio/video/transcript uploads, transcribing audio when needed, generating Markdown notes, managing per-user LLM model profiles plus STT profiles, and handling team workspaces plus team membership.
- Frontend: Vite + React + TypeScript app for authentication, note generation from URL or local uploads, personal/team note browsing, editing, team management, and settings.
- Database/Auth: Postgres-backed storage plus FastAPI-issued JWT auth stored in an HttpOnly cookie.

The backend can also run as a lightweight MCP server through `mcp_server.py`.

## Project Structure
- `app/`
  - `routers/`: FastAPI route modules. `note.py` exposes generation/status APIs, browser upload generation endpoints, plus task-artifact media routes. `note_library.py` also exposes authenticated saved-note media playback routes. `teams.py` exposes authenticated team and membership APIs. `share.py` exposes authenticated share-link APIs plus public shared-note routes. `model_profiles.py` exposes authenticated LLM model-profile APIs. `stt_profiles.py` exposes authenticated STT profile APIs. `mcp.py` exposes the LAN HTTP MCP endpoint at `/mcp`.
  - `services/`: orchestration and domain services.
    - `note_service.py`: main pipeline coordinator.
    - `mcp_service.py`: shared MCP tool definitions and JSON-RPC request handling used by both the stdio server and the HTTP `/mcp` endpoint.
    - `note_media_service.py`: selects key moments, then adds heading timestamps and screenshot markers for those moments after summarization.
    - `transcription_service.py`: per-task transcriber selection, chunking, ffmpeg/ffprobe helpers.
    - `llm_service.py`: resolves LLM config from request overrides, saved model profiles, or env defaults.
    - `stt_profile_service.py`: resolves STT config from per-run selection, saved STT profiles, or env defaults.
    - `task_artifact_service.py`: persists status/result/transcript/markdown artifacts under `output/`.
    - `model_profile_*`: encrypted model profile CRUD and connection testing.
    - `stt_profile_*`: encrypted STT profile CRUD and provider-specific normalization.
    - `auth_service.py`: local email/password auth plus JWT cookie validation for protected APIs.
    - `team_repository.py`: team CRUD, membership management, and team access checks.
    - `share_service.py`: builds public share URLs and renders read-only shared-note HTML.
    - `screenshot_service.py`: replaces `[[Screenshot:mm:ss]]` placeholders with extracted frame images.
  - `downloaders/`: media download/extraction adapters built around `yt-dlp`.
  - `transcribers/`: speech-to-text providers (`groq`, `whisper`, `faster-whisper`, `sensevoice`, `sensevoice-local`).
  - `llm/`: summarizer implementations and prompt templates.
  - `models/`: Pydantic/dataclass request, response, and domain models.
- `frontend/src/`
  - `pages/`: route-level screens such as home, generator, notes, editor, login, team, and settings.
  - `components/`: reusable UI building blocks.
  - `stores/`: Zustand stores for auth, theme, note generation, note library, team workspace selection, model profiles, STT profiles, and language.
  - `lib/`: API wrapper, Supabase client, i18n copy, and model/STT profile client helpers.
- `frontend/src-tauri/`: Tauri 2 desktop shell. `tauri.conf.json` starts Vite for desktop hot reload and bundles `frontend/dist` for desktop releases.
- `supabase/`: local Supabase config, start scripts, and SQL migrations.
- `scripts/`: repository-level diagnostics and deployment smoke checks such as `check_reverse_proxy.py` for validating backend health plus frontend `/api` proxying.
- `tests/`: backend unit tests.
- `docs/plans/`: product/design implementation notes.
- `docs/.vitepress/`: standalone VitePress docs site config and navigation.
- `docs/en/`: English docs pages paired with the default Simplified Chinese docs.
- `data/`: downloaded audio/video cache and temporary transcription chunks.
- `output/`: per-task artifacts and generated Markdown notes.

## Runtime Flow
1. Frontend signs users in against FastAPI auth endpoints and browser requests carry the HttpOnly auth cookie to `/api/*`.
2. `NoteService` creates a task directory under `output/`, downloads remote media, stages an uploaded local file, or prepares an uploaded transcript, and updates `status.json`.
3. `TranscriptionService` loads the selected transcriber, optionally chunks long audio, and saves `transcript.json` when the task input is media.
4. `LLMService` resolves the active model configuration and generates Markdown from transcript segments using the requested summary mode (`default`, `accurate`, or `oneshot`). Transcript uploads skip the STT step and enter summarization directly.
5. `TranscriptionService` resolves the active STT configuration in this order: request `stt_profile_id` > signed-in user's default STT profile > `.env` `TRANSCRIBER_*` defaults.
6. `NoteMediaService` enriches the generated Markdown with section-level timestamp jump links and screenshot markers, then `ScreenshotService` downloads the full video and injects extracted frames.
7. `TaskArtifactService` writes `note.md`, `result.json`, `status.json`, and the `.task_id` mapping.
8. Frontend polls `/api/task/{task_id}`, stores the final note row together with `task_id` in the backend `notes` table under either the current personal workspace or a selected team workspace, renders key moments as timestamp-and-screenshot cards, shows the source media beside preview content when available, seeks embedded video or extracted audio when note timestamps are clicked, supports URL, local media, and local transcript generation entry points, and can optionally generate a public `/share/{token}` link for LAN access.

## Build, Run, and Dev Commands
- Backend install: `pip install -r requirements.txt`
- Optional local transcriber extras: `pip install -r requirements.local-transcribers.txt` when using `TRANSCRIBER_TYPE=faster-whisper`
- Backend dev server: `uvicorn main:app --host 0.0.0.0 --port 8900 --reload`
- Backend direct run: `python main.py`
- Root desktop + backend shortcut: `yarn dev`
- Root backend-only shortcut: `yarn api:dev`
- Root desktop + backend shortcut (Node.js 22+): `yarn client:dev`
- Root browser frontend shortcut: `yarn web:dev`
  - `yarn dev` auto-selects a Python executable with backend dependencies; `VINOTE_PYTHON=/path/to/python` overrides it.
  - Configured database failures are reported; the startup script does not switch to another database. Without DATABASE_URL the backend uses its SQLite default.
- Frontend install: `cd frontend && npm install`
- Frontend web dev server only: `cd frontend && npm run web:dev`
- Tauri desktop hot-reload dev: `cd frontend && yarn dev` or `cd frontend && npm run dev`
- Frontend build: `cd frontend && npm run build`
- Frontend preview: `cd frontend && npm run preview`
- Desktop app bundle build: `cd frontend && npm run desktop:build`
- Docs install: `cd docs && npm install`
- Docs dev server: `cd docs && npm run docs:dev`
- Docs build: `cd docs && npm run docs:build`
- Raspberry Pi bootstrap (PowerShell): `.\deploy\pi\bootstrap-pi.ps1`
- Raspberry Pi bootstrap (Bash): `./deploy/pi/bootstrap-pi.sh`
- Raspberry Pi interactive deploy (PowerShell): `.\deploy\pi\deploy-pi-interactive.ps1`
- Raspberry Pi interactive deploy (Bash): `./deploy/pi/deploy-pi-interactive.sh`
- Raspberry Pi self-hosted runner deploy: `./deploy/pi/deploy-from-checkout.sh`
- Windows convenience launcher: `.\start-dev.ps1` or `.\start-dev.bat`

Default local ports:
- Backend API/docs: `http://127.0.0.1:8900`
- Frontend dev server: `http://localhost:3100`
- Docs dev server: `http://localhost:3101`
- Backend MCP endpoint: `http://127.0.0.1:8900/mcp`
- Tauri desktop dev window: loads `http://127.0.0.1:3100`

## Environment and Configuration
Backend settings live in root `.env` and are loaded by `app/config.py`.

Important backend variables:
- `LLM_*`: default summarizer provider/model/base URL/API key.
- `TRANSCRIBER_TYPE`: `groq`, `whisper`, `faster-whisper`, `sensevoice`, or `sensevoice-local`. This is still the fallback when no STT profile is selected.
- `TRANSCRIBER_TYPE=faster-whisper` also requires `requirements.local-transcribers.txt` to be installed.
- `GROQ_API_KEY`: required when using `groq`.
- `WHISPER_*`, `FASTER_WHISPER_COMPUTE_TYPE`, `SENSEVOICE_*`: provider-specific transcription settings.
- `SUMMARY_DEFAULT_MAX_CHARS`, `SUMMARY_DEFAULT_MAX_SEGMENTS`: thresholds that decide when `default` mode upgrades from one-shot to hierarchical summarization.
- `SUMMARY_CHUNK_MAX_CHARS`, `SUMMARY_CHUNK_MAX_SEGMENTS`, `SUMMARY_CHUNK_OVERLAP_SEGMENTS`: chunk sizing controls for hierarchical summarization.
- `YTDLP_REQUEST_SLEEP_SECONDS`, `YTDLP_DOWNLOAD_SLEEP_SECONDS`, `YTDLP_MAX_DOWNLOAD_SLEEP_SECONDS`: anonymous YouTube request pacing controls used to reduce rate-limit and bot challenges without requiring account cookies.
- `APP_JWT_SECRET`, `AUTH_COOKIE_*`: backend-issued session cookie settings.
- `DATABASE_URL`: required database connection string.
- `SHARE_BASE_URL`: optional override for generated public share links; when empty, the backend tries to infer a LAN URL automatically.
- `MODEL_PROFILE_ENCRYPTION_KEY`: required to store/decrypt model profile API keys.
  - the same encryption key is also used for Groq STT profile API keys
- `VILAB_SERVER_URL` and `VILAB_API_KEY`: administrator-managed cloud service Origin and external API key. VINote users do not enter cloud credentials or sign in to ViTalk. Cloud model choices and cloud/local mode are stored per user in `vilab_preferences`.
- `AppModeSwitch` in the app header and `ModelSourcePanel` share `appModeStore`. `PUT /api/vilab/mode` persists mode independently of cloud availability. The backend enforces global mode over stale per-request profile ids; each pipeline snapshots mode while transcribing and summarizing. Profile lists expose only the active mode's models.
- `vilab_cloud_service.py` calls the deployed server's `/v1/models`, `/v1/asr/transcriptions`, and `/openai/v1/chat/completions`. `ModelSourcePanel` exposes cloud versus local/custom settings. Authenticated VINote endpoints: `GET/PUT /api/vilab/config`, `GET /api/vilab/models`; custom profile keys can be revealed by their owner through `POST /api/{model,stt}-profiles/{id}/reveal-key` with no-store responses.
- `CORS_ALLOW_ORIGINS`: defaults include browser dev origins plus Tauri desktop origins such as `http://tauri.localhost` and `tauri://localhost`.

Frontend Vite settings live in `frontend/.env.local`:
- `VITE_API_BASE_URL` (leave empty for the local Vite proxy, or set an absolute backend URL)
- `VITE_DOCS_BASE_URL` (optional absolute docs-site URL; when empty the app falls back to backend Swagger docs)
  - local dev special case: when the frontend runs on port `3100`, the sidebar `Document` link defaults to `http://localhost:3101/`

Tauri desktop settings live in `frontend/src-tauri/tauri.conf.json`:
- `beforeDevCommand` runs `node ../scripts/ensure-web-dev.mjs`, so Tauri desktop development reuses an existing Vite server on port `3100` or starts one when needed, without requiring Bash on Windows.
- Use root `yarn desktop:build`: scripts/build-desktop.mjs packages the Python backend and FFmpeg, builds the frontend with same-origin requests, and invokes Tauri with a generated resource/bundle config. Direct `tauri build` does not prepare these resources.
- Desktop bundles are generated under `frontend/src-tauri/target/release/bundle/`; macOS defaults to a `.app` bundle.

Raspberry Pi deployment defaults live in `deploy/pi/local.env`:
- `PI_HOST`, `PI_USER`, `PI_PORT`: SSH connection target for bootstrap and deploy scripts
- `PI_REMOTE_DIR`: remote app directory used by bootstrap and deploy scripts
- `PI_ENV_FILE`: root-level env file that should be uploaded to the Pi during deploy

GitHub Actions `dev` auto-deploy defaults:
- workflow: `.github/workflows/deploy-pi-dev.yml`
- environment: `pi-test`
- secret: `PI_TEST_ENV_FILE` contains the full root `.env` for the Pi test environment
- variables: `PI_REMOTE_DIR`, `FRONTEND_PORT`, `BACKEND_PORT`, `DOCS_PORT`
- runner labels: `self-hosted`, `linux`, `arm`, `pi`, `vinote-test`

## Testing and Verification
The repository already contains backend tests under `tests/`.

Recommended checks after code changes:
- Backend unit tests: `pytest tests`
- Reverse-proxy smoke check: `python scripts/check_reverse_proxy.py --host 127.0.0.1 --backend-port 8900 --frontend-port 3100 --docs-port 3101`
- Frontend type/build check: `cd frontend && npm run build`
- Tauri config/environment check: `cd frontend && npm run tauri -- info`
- Docs build check: `cd docs && npm run docs:build`
- Raspberry Pi CI deploy script syntax check: `bash -n deploy/pi/deploy-from-checkout.sh`
- API smoke check: open `http://127.0.0.1:8900/docs`
- MCP smoke check: `POST http://127.0.0.1:8900/mcp` with JSON-RPC `initialize` or `tools/list`
- Pipeline smoke check: run one sample generation and inspect the created folder under `output/`
- Share-link smoke check: generate one note, click Share in the editor, and open the returned `/share/{token}` URL from another LAN device

## Coding and Collaboration Rules
- Python: follow PEP 8, keep route handlers thin, keep orchestration in `app/services/`.
- TypeScript: keep `strict` compatibility intact, use `PascalCase` for components and `camelCase` for helpers/hooks.
- Prefer focused modules over large multi-purpose files.
- Do not commit generated artifacts from `data/`, `output/`, frontend build output, or local Supabase temp files unless the change explicitly targets them.
- Preserve user changes in a dirty worktree; do not revert unrelated edits.

## Documentation Maintenance
Update `README.md`, this `AGENTS.md`, or both whenever you change:
- runtime ports or startup commands
- environment variables or required services
- API routes or authentication requirements
- project structure or module ownership
- major user-facing flows in the frontend

## Versioning
- Use semantic-style versioning for user-visible releases.
- Small fixes or minor tweaks: increment the patch version, for example `0.1.0 -> 0.1.1`.
- Larger features or meaningful product-facing changes: increment the minor version, for example `0.1.0 -> 0.2.0`.
- Prefer updating versions once per merge-ready PR or release unit, not on every intermediate commit.

## Notes for Agents
- Cloud generation validates model selections before downloading/preparing input. Task directory titles are trimmed after truncation for Windows compatibility; `.task_id` is written before renaming so subsequent failures remain discoverable. The generator treats `not_found` as a terminal error.
- The current frontend supports local audio/video uploads and direct transcript uploads from the browser.
- The note generator UI exposes both LLM profile selection and STT profile selection; `default` summary mode still auto-switches to hierarchical summarization for longer transcripts.
- Share links are public read-only links backed by `notes.share_token` and can be disabled from the note editor.
- Saved notes are now explicitly scoped as either personal notes or team notes. Team notes require `scope="team"` plus a valid `team_id`, and any signed-in team member can open them through the normal note APIs.
- If documentation and code disagree, trust the code, then fix the documentation in the same change.

## Cloud account integration development
- Cloud session linking must match the current local user's normalized email and must never replace an existing issuer/subject. Registration keeps email/password fixed after sending the code; switching back to login resets the form.
- `cloud_account_service.py` owns VINote Supabase email OTP linking, encrypted sessions and token rotation. `VINOTE_SUPABASE_URL` / `VINOTE_SUPABASE_PUBLISHABLE_KEY` enable personal authentication; configured personal auth never falls back to the deployment key.
- Cloud account endpoints under `/api/vilab/account` require local VINote authentication. `cloud_accounts` maps local users to unique `(issuer, subject)` identities.
- Local VILab Server integration uses configurable `http://127.0.0.1:9878`; do not change the deployed LAN server until the user deploys the modified branch.

Desktop packaging: scripts/desktop_backend.py initializes per-install secrets and SQLite in the user app data directory. Release-only desktop_backend.rs starts the bundled backend on a persisted per-install loopback port and stops it on exit. Packaged cloud defaults to http://192.168.1.143:9876; source development uses VILAB_SERVER_URL or http://127.0.0.1:9878. The two products remain independent processes/repos.

Fresh-checkout startup: yarn client:dev runs bootstrap-dev.mjs to install frontend dependencies, create .venv and install requirements, and create .env with unique local secrets and config/desktop-public.json account defaults. Existing .env is preserved. --setup-only performs initialization without opening a window. Node 22+, Python, Rust/platform compilers and FFmpeg are system prerequisites.

## Meeting recording and speaker diarization

- Actual meeting wall-clock start/end must come from explicitly supplied metadata/context, never from audio duration or the last transcript timestamp. Paused recordings have a shorter accumulated duration. Transcript/heading timestamps are recording offsets, not wall-clock times.

- `audio_preprocessing_service.py` owns conservative FFmpeg denoising on temporary audio, without trimming time. Explicit upstream empty recognition is recorded in `unrecognized_segments`; other STT failures remain errors. `DIARIZATION_CLUSTER_THRESHOLD` controls the diagnostic clustering threshold.
- `speaker_clustering_service.py` refines automatic grouping using sustained-turn embeddings, average linkage and silhouette selection. Short uncertain turns remain unknown; overlap remains explicit. Group count and silhouette are not identity accuracy guarantees.
- Meeting summaries synthesize themes, confirmed decisions and explicit actions; omit unsupported owners/deadlines/open questions. Both one-shot and hierarchical prompts keep wall-clock metadata separate from media offsets and avoid a duplicate closing AI summary.
- `app/llm/meeting_review.py` owns fact-review prompts. Meeting one-shot drafts are reviewed against original transcripts; hierarchical chunks are reviewed before merge, and final consistency is checked against reviewed chunks. Empty/failed reviews fail rather than returning the draft. Cloud review prefers available `MEETING_REVIEW_MODEL` (default `gpt-6-astra`), falls back to the primary model when absent, and never changes global preferences. Custom/local providers reuse their current model. Packaging includes this non-secret preference; calls and actual review model remain traced.
- `bootstrap-dev.mjs` checks/prepares local speaker runtime/models. `desktop-build-profile.mjs` owns release/test identity and configuration isolation. Both packages default to the deployed LAN ViLab Origin; source development uses localhost. Build entry points and artifacts are documented in `docs/desktop-packaging.md`; never package `.env` or private meeting artifacts.

- `/meetings` owns meeting setup/history; `meetingCapture.ts` captures selected microphone plus optional display/system audio. Main-window `MeetingRecorderDock` owns the stream; `MeetingRecorderController` forwards native floating-window actions via Tauri events.
- Capture acquisition is cancellable with a 20-second permission timeout; cancel/reset/unmount releases acquired sources and stops late permission results. Runtime recorder errors release tracks and update the dock; stopping releases devices before async file finalization. Pausing retains capture for resuming; stopping/discarding releases it.
- `speaker_diarization_service.py` performs whole-recording local sherpa-onnx Pyannote/3D-Speaker clustering, then calls the configured STT per turn. IDs are local to the recording; overlap labels indicate uncertain attribution, not separated overlapping audio.
- Media generation routes accept `diarize` and optional `speaker_count` (1–20); authenticated `GET /api/meeting-capabilities` returns `diarization.available`. Source development installs optional `requirements.diarization.txt` and models via `scripts/setup_diarization.py`; `DIARIZATION_MODEL_DIR` defaults to `data/models/diarization`. Desktop packaging stages these models.
- Uploaded video reuses its source file for screenshot extraction. Audio-only notes remove screenshot placeholders. Meeting video notes use `meeting_video`; audio uses `meeting_recording`.
- `scripts/check_meeting_generation.py --live` uses real cloud services through in-process desktop API routes and saves a personal test note. This is not a native capture/UI test. Explicit transient STT HTTP 502/503/504 responses retry at most twice; other errors fail immediately.

## Langfuse observability

`app/services/tracing_service.py` owns always-enabled Langfuse SDK 4 tracing. Source, test packages and release packages must all trace; legacy LANGFUSE_ENABLED=false is ignored. Source startup and packaging reject missing project configuration; network/export failures remain fail-open for business tasks. Root chains correlate task_id/sessionId, hash local user IDs, use Chinese stage names and record actual model parameters/usage. Content remains redacted unless LANGFUSE_CAPTURE_CONTENT=true. Configure LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and optional LANGFUSE_RELEASE. Per the user's explicit direct-integration requirement, both package profiles bundle the build-managed Langfuse credentials in backend resources; these are extractable by package holders, never commit or log them. This exception does not permit bundling .env, model keys or user credentials. Old per-install langfuse.env is ignored. Environments are development/test/production. Both builds require frozen-backend synthetic trace ingestion plus API readback and store a credential-free receipt in manifest.json. Unit tests disable settings.langfuse_enabled in tests/conftest.py only. See docs/langfuse.md for scope and limitations.
