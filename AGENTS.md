# Repository Guidelines

## Architecture Overview
 VINote is a full-stack video-to-note workspace with three moving parts:

- Backend: FastAPI API for downloading media, receiving local audio/video/transcript uploads, transcribing audio when needed, generating Markdown notes, managing per-user LLM model profiles plus STT profiles, and handling team workspaces plus team membership.
- Frontend: Vite + React + TypeScript app for authentication, note generation from URL or local uploads, personal/team note browsing, editing, team management, and settings.
- Database/Auth: Postgres-backed storage plus FastAPI-issued JWT auth stored in an HttpOnly cookie.

The backend can also run as a lightweight MCP server through `mcp_server.py`.

## Project Structure
- `app/`
  - `routers/`: FastAPI route modules. `note.py` exposes generation/status APIs, browser upload generation endpoints, plus task-artifact media routes. `note_library.py` also exposes authenticated saved-note media playback routes. `teams.py` exposes authenticated team and membership APIs, including owner-only team deletion that returns team notes to their creators' personal workspaces. `share.py` exposes authenticated share-link APIs plus public shared-note routes. `model_profiles.py` exposes authenticated LLM model-profile APIs. `stt_profiles.py` exposes authenticated STT profile APIs. `mcp.py` exposes the LAN HTTP MCP endpoint at `/mcp`.
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
- Fresh-checkout setup without starting the app: `yarn setup`
- Desktop + backend entry points: `yarn client:test:dev` (LAN test development), `yarn client:dev` (local development). `yarn dev` remains a test-development compatibility alias. See `docs/running-scripts.md`.
- Root backend-only entry point: `yarn dev:api`
- Root browser frontend entry point: `yarn dev:web`
- Merge-ready project validation: `yarn verify`
  - `yarn dev` auto-selects a Python executable with backend dependencies; `VINOTE_PYTHON=/path/to/python` overrides it.
  - Configured database failures are reported; the startup script does not switch to another database. Without DATABASE_URL the backend uses its SQLite default.
- Frontend install: `cd frontend && npm install`
- Frontend web dev server only: `cd frontend && npm run web:dev`
- Tauri desktop hot-reload dev: `yarn client:test:dev` or `yarn client:dev` from the repository root
- Windows source development keeps Tauri/Vite output in the invoking terminal. `scripts/windows-backend-dev.py` isolates Uvicorn reload signals in a hidden console with output forwarded to that terminal; do not use Windows `detached: true` for the desktop toolchain.
- Frontend build: `cd frontend && npm run build`
- Frontend preview: `cd frontend && npm run preview`
- Test/release package build: `yarn client:test` / `yarn client:production`; legacy `package:test` / `package:release` remain aliases.
- Package configuration preview: `yarn package:test:plan` / `yarn package:release:plan`
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
- Use root `yarn package:test` or `yarn package:release`: scripts/build-desktop.mjs packages the Python backend and FFmpeg, builds the frontend with same-origin requests, and invokes Tauri with a generated resource/bundle config. Direct `tauri build` does not prepare these resources.
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
- The note generator UI exposes LLM and STT service selection, but no summary-strategy selector. Meeting minutes and note organization always submit `default`; the backend automatically chooses one-shot or hierarchical processing by transcript length. Legacy API strategy values remain supported.
- Share links are public read-only links backed by `notes.share_token` and can be disabled from the note editor.
- Saved notes are now explicitly scoped as either personal notes or team notes. Team notes require `scope="team"` plus a valid `team_id`, and any signed-in team member can open them through the normal note APIs.
- If documentation and code disagree, trust the code, then fix the documentation in the same change.

## Cloud account integration development

- App 登录页提供邮箱验证码重置密码，复用 `/api/auth/password/code` 与 `/api/auth/password/reset`，成功后返回密码登录。登录来源仅后台记录，不在产品界面展示。普通 `/api/auth/sign-out` 只清除当前客户端 Cookie（手机同时清除 Keychain Token），不调用共享云端账号 `disconnect`，以支持手机与桌面同时在线及独立退出。JWT 仍沿用原有到期机制，普通退出不是全设备令牌撤销。

- 手机和桌面端复用同一套云端账号与本地用户映射。App 通过 `/api/auth/config` 选择邮箱验证注册流程；云端配置启用时不可回退本地注册。成功登录及注册验证写入 `auth_login_events`，保存用户 ID、UTC 时间、客户端来源和平台。来源来自白名单化的 `X-VINote-Client` / `X-VINote-Platform`，属于客户端自报备注，不参与鉴权。桌面端现有请求标记为 `desktop`；App 标记为 `mobile` 并区分 `android` / `ios`。新表由启动时 `init_db()` 创建。
- Cloud session linking must match the current local user's normalized email and must never replace an existing issuer/subject. Registration keeps email/password fixed after sending the code; switching back to login resets the form.
- `cloud_account_service.py` owns VINote Supabase email OTP linking, encrypted sessions and token rotation. `VINOTE_SUPABASE_URL` / `VINOTE_SUPABASE_PUBLISHABLE_KEY` enable personal authentication; configured personal auth never falls back to the deployment key.
- Cloud account endpoints under `/api/vilab/account` require local VINote authentication. `cloud_accounts` maps local users to unique `(issuer, subject)` identities.
- Source development and desktop packages use the deployed LAN VILab Server at `http://192.168.1.143:9876` by default. An explicit `VILAB_SERVER_URL` override remains available for isolated service development.

Desktop packaging: scripts/desktop_backend.py initializes per-install secrets and SQLite in the user app data directory. Release-only desktop_backend.rs starts the bundled backend on a persisted per-install loopback port and stops it on exit. Test development and packaged builds default to http://192.168.1.143:9876; ordinary development defaults to http://127.0.0.1:9878. Desktop channels use VINOTE_TEST_VILAB_SERVER_URL / VINOTE_DEV_VILAB_SERVER_URL / VINOTE_RELEASE_VILAB_SERVER_URL rather than the generic VILAB_SERVER_URL; standalone backend commands still use the generic variable. The two products remain independent processes/repos.

Fresh-checkout startup: yarn dev runs bootstrap-dev.mjs to install frontend dependencies, create .venv and install requirements, and create .env with unique local secrets and config/desktop-public.json account defaults. Existing .env is preserved. --setup-only performs initialization without opening a window. Node 22+, Python, Rust/platform compilers and FFmpeg are system prerequisites.

## Meeting recording and speaker diarization

- Desktop custom recorder commands are explicitly allowed by `frontend/src-tauri/permissions/meeting-recorder.toml` and the default capability, scoped to the main/recorder windows and local backend Origin. Native WebView regression must check command errors as well as media playback.

- Actual meeting wall-clock start/end must come from explicitly supplied metadata/context, never from audio duration or the last transcript timestamp. Paused recordings have a shorter accumulated duration. Transcript/heading timestamps are recording offsets, not wall-clock times.

- `audio_preprocessing_service.py` owns conservative FFmpeg denoising on temporary audio, without trimming time. Explicit upstream empty recognition is recorded in `unrecognized_segments`; other STT failures remain errors. `DIARIZATION_CLUSTER_THRESHOLD` controls the diagnostic clustering threshold.
- `speaker_clustering_service.py` refines automatic grouping using sustained-turn embeddings, average linkage and silhouette selection. Short uncertain turns remain unknown; overlap remains explicit. Group count and silhouette are not identity accuracy guarantees.
- Meeting summaries synthesize themes, confirmed decisions and explicit actions; omit unsupported owners/deadlines/open questions. Both one-shot and hierarchical prompts keep wall-clock metadata separate from media offsets and avoid a duplicate closing AI summary.
- `app/llm/meeting_review.py` owns fact-review prompts. Meeting one-shot drafts are reviewed against original transcripts; hierarchical chunks are reviewed before merge, and final consistency is checked against reviewed chunks. Empty/failed reviews fail rather than returning the draft. Cloud review prefers available `MEETING_REVIEW_MODEL` (default `gpt-6-astra`), falls back to the primary model when absent, and never changes global preferences. Custom/local providers reuse their current model. Packaging includes this non-secret preference; calls and actual review model remain traced.
- `bootstrap-dev.mjs` checks/prepares local speaker runtime/models. `desktop-build-profile.mjs` owns release/test identity and configuration isolation. Test development, test packages and release packages default to the deployed LAN ViLab Origin at `http://192.168.1.143:9876`; ordinary development defaults to local port 9878. Channel-specific overrides and command semantics are documented in `docs/running-scripts.md`. Build entry points and artifacts are documented in `docs/desktop-packaging.md`; never package `.env` or private meeting artifacts.

- `/meetings` owns meeting setup/history; `meetingCapture.ts` captures selected microphone plus optional display/system audio. Main-window `MeetingRecorderDock` owns the stream; `MeetingRecorderController` forwards native floating-window actions via Tauri events.
- Capture acquisition is cancellable. Screen selection waits for the user without a fixed timeout; microphone acquisition has a 20-second timeout. Cancel/reset/unmount releases acquired sources and stops late permission results. Runtime recorder errors release tracks and update the dock; stopping releases devices before async file finalization. Pausing retains capture for resuming; stopping/discarding releases it.
- Source development writes capture-stage events and original exceptions through Vite's local WebSocket to `data/desktop-capture.log` (bounded to approximately 1 MiB). These diagnostics exclude device IDs, device labels and media content; they are disabled in production builds. Backend logs do not contain WebView capture failures.
- `speaker_diarization_service.py` runs whole-recording local sherpa-onnx Pyannote/3D-Speaker clustering independently from cloud STT covering the entire recording (chunked when necessary). Provider timestamps are aligned by interval overlap; whole-file-only text is aligned in sequence by detected speaking duration and marked estimated. IDs are local to the recording; overlap labels indicate uncertain attribution, not separated overlapping audio.
- Media generation routes accept `diarize` and optional `speaker_count` (1–20); authenticated `GET /api/meeting-capabilities` returns `diarization.available`. Source development installs optional `requirements.diarization.txt` and models via `scripts/setup_diarization.py`; `DIARIZATION_MODEL_DIR` defaults to `data/models/diarization`. Desktop packaging stages these models.
- Uploaded video reuses its source file for screenshot extraction. Audio-only notes remove screenshot placeholders. Meeting video notes use `meeting_video`; audio uses `meeting_recording`.
- `scripts/check_meeting_generation.py --live` uses real cloud services through in-process desktop API routes and saves a personal test note. This is not a native capture/UI test. Explicit transient STT HTTP 502/503/504 and transport/timeouts retry at most twice; authentication and unknown errors fail immediately. VILab transcription requests are capped at 300 seconds (approximately 9.6 MB PCM WAV), including when optional generic chunking is disabled. Successful chunks are cached for retry; explicit no-speech sections are retained as unrecognized intervals. This bound is not a guarantee against upstream outages.

## Langfuse observability

`app/services/tracing_service.py` owns Langfuse SDK 4 tracing for desktop requests only. Tauri identifies itself with `X-VINote-Client: desktop`; browser, Pi and ordinary backend calls must not initialize tracing. Business root names are exactly `桌面端｜会议纪要` and `桌面端｜笔记整理`, selected by product workflow rather than media type. Source desktop, test packages and release packages all trace; source desktop startup and packaging reject missing project configuration, while ordinary backend startup does not. Network/export failures remain fail-open for business tasks. Root chains correlate task_id/sessionId, hash local user IDs, use Chinese stage names, and record complete STT/LLM inputs and outputs, actual model parameters, usage and latency. Never record media binary, credentials, auth headers, local absolute paths or raw speaker embeddings. Configure LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and optional LANGFUSE_RELEASE. Both package profiles bundle the build-managed Langfuse credentials in backend resources; these are extractable by package holders, never commit or log them. This exception does not permit bundling .env, model keys or user credentials. Old per-install langfuse.env is ignored. Environments are development/test/production. Both builds require frozen-backend synthetic trace ingestion plus API readback and store a credential-free receipt in manifest.json. See docs/langfuse.md for scope and limitations.

Meeting setup automatically enables speaker diarization with automatic speaker count; do not expose diarization/count controls in the meeting UI. Users rename speakers in the transcript. Cloud ModelSourcePanel lists deployed ASR/LLM choices, persists selections per user and applies them to the next task. VILabCloudService.defaults resolves saved selections over service defaults, falling back only to a validated available service default when a saved selection is unavailable; explicit select() requests still reject invalid models; running task snapshots remain unchanged.

## Recording history and media lifecycle

Meeting capture uses the selected microphone as its required audio source. Screen recording requests video only, and the screen picker chooses only the recorded window or display. Persisted legacy options may still contain a system-audio flag, but capture ignores it so Windows/WebView system-audio failures never block recording. Display capture support depends on the runtime and screen picker.

Stopping saves its blob and PendingMeeting metadata in IndexedDB and releases capture resources. Recording-only mode returns to /meetings without STT/LLM; minutes mode automatically generates and saves the note, always using complete media for audio and video. LocalRecordingCard owns replay/download/confirmed deletion/later generation. A saved recording is visible without a note; generation retains the local original and history until explicit user deletion. Preserve actual recording start/end separately from generation time and meeting wall-clock context.

MeetingMediaService owns GET/DELETE /api/notes/{note_id}/recording. File deletion preserves notes, transcripts, screenshots and the user's imported original. Deletion requires the note creator, matching recording_owner marker, and a single referencing note; unverified legacy/shared recordings remain downloadable. Only regular audio/video files under the task's media directory may be deleted. A recording_deleted marker prevents playback fallback to cached source audio. Local user-visible deletion uses a strict IndexedDB transaction and reports failures.

OPFS-backed recording blobs reference their source file. After IndexedDB history metadata commits, transfer that file out of the hook's temporary-file cleanup ownership; keep its fileName in PendingMeeting. Delete it only through verified local-history deletion. Automatic post-generation cleanup is disabled. Never remove the OPFS file on reset immediately after saving its Blob to IndexedDB: the Blob becomes unreadable.

Successful local saving sets `localRecordingSaved` independently of generation state and closes capture controls immediately. Background generation failure must restore history retry actions without reopening recording controls; unsaved recordings remain protected. History generation/retry starts directly without a second recorder confirmation. Per-card generation labels must match the active recording ID and processing phase, not the global busy flag.

`TranscriptionService.get_audio_duration` falls back to bounded ffprobe packet-timestamp scanning when container duration is missing, zero or nonfinite (common with MediaRecorder WebM). This does not modify the source recording; media offsets are never substituted for meeting wall-clock metadata.


### Meeting minutes completion (2026-09-18)

- `meeting_video_analysis_service.py` samples up to 24 timestamped frames and sends actual images to the deployed `gpt-5.6-luna` model. Visual evidence is included in summary and fact review separately from speech. This is sampled frame analysis, not exhaustive video understanding; absent vision service fails the task while local media remains available. `visual_observations.json` records evidence and offsets. Langfuse records offsets/text/model/usage, never image binaries.
- Saved unavailable cloud model preferences resolve to a validated service default for new tasks. Explicit invalid selections still fail; running snapshots do not change. The fallback has its own trace stage.
- Desktop main capture uses the native controller without a simultaneous in-page recording dock. Terminal main-window states close the native controller. A saved server note must retain the original recording before deleting the local pending copy.

- Desktop source startup isolates child process groups/consoles on Windows as well as Unix, so Python reload control signals cannot terminate the sibling Tauri window. Shutdown still terminates each owned process tree.

Development channels use separate Tauri identities (`app.vinote.desktop.dev` and `app.vinote.desktop.test.dev`) and tracing environments, while the source backend database still follows repository configuration. Run one source instance at a time; the launcher rejects an occupied backend port rather than reusing unknown settings. `client:*:dev:plan` is a read-only configuration preview without bootstrapping or launching services.

## 会后统一处理（2026-09-21）

两种模式在录制期间均不调用 ASR 或总结模型。结束后先保存完整原始媒体、释放设备并关闭控制；纪要模式自动执行会后处理。说话人区分继续使用本地模型，VILab 负责完整音频转写和总结，结果按时间戳对齐。视频使用实际代表帧证据，不代表逐帧理解。

分段转写显示已完成音频时长、比例及基于实际分段耗时估算的剩余转写时间；整段请求没有中间结果时不虚构进度。所有进度采集仅在录制结束后运行。

本地历史持久化任务 ID、草稿 ID、失败阶段和进度。POST /api/task/{task_id}/retry 校验录制所有者与媒体后复用任务和有效产物。旧进程中断任务显示可重试。保存笔记后保留本地原始媒体直到用户明确删除。

MeetingCaptureWorkspace renders capture preview and controls. User end actions send request-stop; MeetingRecorderDock confirms in the main window, never in the native controller. The internal stop action remains available for source-ended/save flows. Recording uses no realtime ASR. Audio-meter failures are fail-open and must never stop media capture.

Meeting postprocessing workers live in frontend/src/lib/meetingProcessing.ts and never own capture state. Both history and note retry reuse the task. PATCH /api/notes/{note_id} accepts status-only changes, preserving title/content. Verification scope and remaining media-management gaps are documented in docs/plans/2026-09-21-meeting-postprocessing.md.


## App 录音库与纪要来源（2026-09-23）

VINote-app 的 recordingLibrary 按账号持久化原音频和录音草稿；generateRecording 直连 VILab 分段转写和总结，保存检查点供失败重试。录音库支持播放、导出、导入、后续生成和确认删除。仅录音模式不调用模型。Android 已加入麦克风前台服务；iOS 后台音频与转换源码待 Mac/iPhone 验证。生成纪要仍需前台，公网入口尚未配置。App 当前直连 Supabase 认证，不经过下述后端登录审计端点；纪要本机保存，未实现跨端同步。详见子仓库 README 和真机验证文档。

上传生成入口在任务目录写入不可覆盖的 generation_client 标记，保存笔记时从任务读取到 notes.generation_client（启动时兼容迁移旧表）。App 与桌面列表/详情显示 App 生成或桌面端生成；历史缺失显示来源未知，不能用当前保存/编辑客户端猜测。登录来源审计仍不向用户显示。
