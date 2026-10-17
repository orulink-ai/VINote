# Repository Guidelines

## Current product direction (2026-10-12)

Cross-device meeting/note synchronization has been cancelled by the user. Desktop and App must save, edit, trash, restore, version, export and share the content available on the current device without a workspace pull/push, background retry or sync status gate. Do not surface repeated "local" labels in ordinary content views; explain file location only in file management and when playback or reprocessing needs the original. Historical workspace code/API and receipts may remain for safe recovery, but no new client operation may dispatch to them. Keep account sign-in, deliberate Feishu publication and confirmed MCP calls independent from synchronization. Preserve original audio/video and frozen publication/tool receipts. The older shared-content notes below describe historical implementation, not the active client contract.

2026-10-12 interaction review: MeetingWorkbench's related-note count is a count of content objects, not generated versions. Keep each object and retained recording reachable in separate disclosure sections. FileLibrary deletion confirmation temporarily replaces the selected file Sheet; cancellation preserves the same file/query/source and restores focus. Changed accounts or routes must not restore or delete the old selection. A concurrently missing original is unavailable, not proof that its saved notes were deleted.

## Latest reviewed workflow contracts (2026-10-12)

- 2026-10-17 public video intake: cloud content exposes Bilibili only via `video_url_platforms`, strict HTTPS source validation and per-hop DNS-pinned API/CDN downloads. No generic yt-dlp/curl/network FFmpeg is exposed; no credentials leave the content/model service. Read-only POST `/api/content-service/video-source` creates no operation and invokes no model. Downloads precede ASR/LLM; preserve canonical BV/part identity and signed URLs remain ephemeral. HTTP 412 is a source-access failure, not proof of video deletion or model failure. Download-only acceptance is not end-to-end inference acceptance.
- Desktop Bilibili intake downloads the source audio on-device through `bilibili_source_service`, binds the retained original to its owner/task with canonical BV/part identity, and never fetches remote video for screenshots.


- 2026-10-14 candidate independent generation: authenticated GET `/api/task/{task_id}/new-generation-context` reads the original cloud model/source context; explicitly confirmed POST `/api/task/{task_id}/new-generation` creates a distinct durable owner-scoped operation/task. Only a newly reserved operation queues once; reserved/accepted recovery is GET-only. It inherits the original model snapshot without current defaults, references the canonical retained original without copying media, and protects referenced originals from deletion. Interrupted new jobs remain unknown/non-retryable; no automatic restart or old `/retry` dispatch is allowed. Desktop `?task=<id>` opens an exact read-only task without replacing the global intake receipt or saving/generating; new operations use separate per-operation records. Local/unexposed snapshots fail closed. These are source/offline-test contracts, not proof of deployment or provider/device acceptance.

- 2026-10-16 independent ASR execution: only the first durable `NewGenerationService.run_once` claim can bind an accepted owner/task/fingerprint DB receipt to a revocable ContextVar lease. Disk JSON and arbitrary new IDs never authorize a namespace. Owner/task/canonical original/hash/frozen Origin and concrete ASR/LLM snapshot are rechecked; `copy_context` carries the lease into parallel ASR, and `finally` revokes/resets it. Checkpoints live under the child task's `transcription_chunks/vilab_stream`; the same operation's unknown/inflight cannot switch namespaces or replay. The old global checkpoint may seed only a contiguous integer-sample confirmed prefix with identical owner/Origin/model/normalized WAV identity, never its plan/inflight. Its OS lock is held through the new execution; legacy sentinels, lock contention, corrupt or uncommitted donor records block submission rather than restart at zero. Seed is fsynced before planning/sending remaining audio, and saved prefix progress is reported immediately through the existing callback. Old evidence bytes/markers remain intact; only the existing lock backing file may be created. No API/schema changes. Offline evidence and counterexamples: `docs/reviews/2026-10-16-independent-asr-namespace.md`; actual provider acceptance remains unverified. Ordinary UI does not expose namespace/seed/lock terminology.

- 2026-10-14 retained upload originals: `task_original_service.py` owns the account/task/workflow-bound `source_original.json` index, referencing existing media without copying it. Explicit owner, workflow, canonical task mapping and contained media are required for historical discovery. `/api/files` includes these originals before a saved content object exists; Meetings shows them in a separate “会议资料” section. Task-owned originals have query/preview/export actions, not blind generation or deletion. Structured unconfirmed ASR outcomes remain non-retryable through status reads and recovery routes; this safety rule does not establish successful transcription or add a provider-result lookup API.

- Complete-child cache exception: after its own execution stamp, normalized WAV identity, absence of inflight/legacy sentinel and strict full confirmed coverage are verified, an independent operation reads its complete child cache without locking/reading the donor or fetching token/catalog/ASR. Donor safety gates still apply to seeding and partial-child remaining submissions.

- User-approved navigation is Meeting & Notes (Meeting / Notes), File Library, Plugins, Settings and avatar Account; historical classifications below must not restore duplicate entry points. Notes keeps explicit link/file intake and a lightweight writing action. Cached background errors belong to the browsing status area; a failed first read is not an empty library.
- Content tools operate on a frozen saved body/version. Version/source browsing and originals management remain distinct; history labels use actual kind/revision, never inferred V1 or deduplication by title/time. Translation is an outbound MCP task supporting zh/en, with real service/tool grant/model and one explicit execution confirmation; management appears on demand, unknown runs are queried rather than replayed.
- Contextual return routes are validated and preserve actual list query/project/archive state. Source task recovery carries original owner, generation Origin and operation/task identity; it may not replace a newer input slot or start another submission on navigation.
- Settings sections return to their overview before a validated external source. Loading and loaded pages share this hierarchy; an overview without a valid source does not invent a return link. Validate query and state parents independently, and do not rebind an already resolved parent inside PageReturn.
- Feishu publication freezes source, destination, recipient identity and operation before POST. `feishu_publish_receipts` and `feishu_write_batches` persist account-scoped original receipts/write outcomes. Exact GET `/api/feishu/deliveries/by-id/{job_id}` and `/api/feishu/deliveries/by-operation/{operation_id}` require authentication; status reports `publish_receipt_protocol=1`. Unknown writes and legacy absent receipts must not be automatically replayed or substituted with the latest job. The shared service stores encrypted credentials; originals remain on their source device.
- Record source/code/test/actual-device evidence separately in `docs/reviews/2026-10-12-actual-ui-verification.md`. A healthy deployment or passing component tests does not establish complete product acceptance or recipient reading permissions.

## Architecture Overview
 VINote is a full-stack video-to-note workspace with three moving parts:

- Backend: FastAPI API for downloading media, receiving local audio/video/transcript uploads, transcribing audio when needed, generating Markdown notes, managing per-user LLM model profiles plus STT profiles, and handling team workspaces plus team membership.
- Frontend: Vite + React + TypeScript app for authentication, note generation from URL or local uploads, personal/team note browsing, editing, team management, and settings.
- Database/Auth: Postgres-backed storage plus FastAPI-issued JWT auth stored in an HttpOnly cookie.

The backend can also run as a lightweight MCP server through `mcp_server.py`.

### 2026-10-11 shared content and tools

- `/api/workspace` stores account-scoped text, all saved versions, immutable transcript/speaker evidence revisions and sync operations. Originals are not accepted by this API. `workspace_service.py` owns compare-and-swap revisions and tombstones; `workspace_generation.py` generates new text versions without re-uploading media. Only acknowledged writes display synced. Conflicts preserve drafts; failed generation preserves previous content.
- Workspace and `/api/mcp-connections` use the verified identity from `feishu.principal`; Cookie clients may proxy to the configured shared integration service. Mobile Bearer expiry must remain HTTP 401 to permit its bounded refresh; provider outages are not authentication failures.
- MCP outbound tools use HTTPS Streamable HTTP, account-isolated encrypted credentials, explicit tool grants, bound per-call confirmation and durable execution records. Unknown remote results must not be automatically replayed. This is separate from VINote's existing inbound `/mcp` server.
- Latest confirmed navigation: desktop Meetings & Notes (Meetings / Notes), File Library, Plugins, bottom Settings and Account. App has Meetings & Notes / File Library / Plugins tabs, with Account and Settings through the avatar. Projects/archive are workspace filters; tasks use a global status entry. Feishu is a built-in connector under Plugins. Preserve historical data and compatible deep links.
- Shared content deployment uses VINOTE_WORKSPACE_URL separately from VINOTE_INTEGRATION_URL, PostgreSQL and private Supabase Storage content attachments. VINOTE_WORKSPACE_CLOUD requires verified Supabase Bearer identity and rejects SQLite fallback; cloud runtime does not expose device-original or Cookie auth APIs. See docs/shared-workspace.md. Local /api/files retains originals without starting generation; deletion preserves text and versions.

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
4. `LLMService` resolves the active model configuration and generates Markdown from transcript segments. `default` and `oneshot` submit the complete source once; meeting drafts then receive the existing whole-source fact review. Only explicit legacy `accurate` opts into chunk/merge. Provider context errors preserve source and fail without automatic splitting, model changes or replay. Transcript uploads skip STT and enter summarization directly.
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
- Source desktop: `yarn dev:desktop:lan` / `yarn dev:desktop:public`; source web: `yarn dev:web:lan` / `yarn dev:web:public`. All start the local backend and Vite. See `docs/running-scripts.md`.
- Root backend-only entry point: `yarn dev:api`
- Root browser entry points: `yarn dev:web:lan` / `yarn dev:web:public` (backend + Vite + browser).
- Merge-ready project validation: `yarn verify`
  - `yarn dev` auto-selects a Python executable with backend dependencies; `VINOTE_PYTHON=/path/to/python` overrides it.
  - Configured database failures are reported; the startup script does not switch to another database. Without DATABASE_URL the backend uses its SQLite default.
- Frontend install: `cd frontend && npm install`
- Frontend web dev server only: `cd frontend && npm run web:dev`
- Source desktop: `yarn dev:desktop:lan` / `yarn dev:desktop:public`; source web: `yarn dev:web:lan` / `yarn dev:web:public`. All start the local backend and Vite. See `docs/running-scripts.md`.
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
- `SUMMARY_DEFAULT_MAX_CHARS`, `SUMMARY_DEFAULT_MAX_SEGMENTS`: retained legacy configuration fields; they no longer split or change the `default` strategy.
- `SUMMARY_CHUNK_MAX_CHARS`, `SUMMARY_CHUNK_MAX_SEGMENTS`, `SUMMARY_CHUNK_OVERLAP_SEGMENTS`: chunk sizing controls only for explicitly requested legacy `accurate` summarization.
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
- Direct Tauri invocation retains `beforeDevCommand` (`ensure-web-dev.mjs`). Canonical source commands use `dev.mjs` to own Vite and disable that hook; occupied ports are rejected rather than reused. No Bash is required on Windows.
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
- The note generator UI exposes LLM and STT service selection, but no summary-strategy selector. Meeting minutes and note organization submit `default`: the backend sends the complete source in one draft call, then applies whole-source fact review for meetings, regardless of fixed char/segment thresholds. Explicit legacy `accurate` remains compatible without a UI entry. Context errors are surfaced through existing service error handling, never automatic splitting, model changes or replay. No model-name context-limit branch is allowed.
- Share links are public read-only links backed by `notes.share_token` and can be disabled from the note editor.
- Saved notes are now explicitly scoped as either personal notes or team notes. Team notes require `scope="team"` plus a valid `team_id`, and any signed-in team member can open them through the normal note APIs.
- If documentation and code disagree, trust the code, then fix the documentation in the same change.

## Cloud account integration development

- App 登录页提供邮箱验证码重置密码，复用 `/api/auth/password/code` 与 `/api/auth/password/reset`，成功后返回密码登录。登录来源仅后台记录，不在产品界面展示。普通 `/api/auth/sign-out` 只清除当前客户端 Cookie（手机同时清除 Keychain Token），不调用共享云端账号 `disconnect`，以支持手机与桌面同时在线及独立退出。JWT 仍沿用原有到期机制，普通退出不是全设备令牌撤销。

- 手机和桌面端复用同一套云端账号与本地用户映射。App 通过 `/api/auth/config` 选择邮箱验证注册流程；云端配置启用时不可回退本地注册。成功登录及注册验证写入 `auth_login_events`，保存用户 ID、UTC 时间、客户端来源和平台。来源来自白名单化的 `X-VINote-Client` / `X-VINote-Platform`，属于客户端自报备注，不参与鉴权。桌面端现有请求标记为 `desktop`；App 标记为 `mobile` 并区分 `android` / `ios`。新表由启动时 `init_db()` 创建。
- Cloud session linking must match the current local user's normalized email and must never replace an existing issuer/subject. Registration keeps email/password fixed after sending the code; switching back to login resets the form.
- `cloud_account_service.py` owns VINote Supabase email OTP linking, encrypted sessions and token rotation. `VINOTE_SUPABASE_URL` / `VINOTE_SUPABASE_PUBLISHABLE_KEY` enable personal authentication; configured personal auth never falls back to the deployment key.
- Cloud account endpoints under `/api/vilab/account` require local VINote authentication. `cloud_accounts` maps local users to unique `(issuer, subject)` identities.
- `scripts/service-environments.mjs` fixes LAN to `http://192.168.1.143:9876` and public to `官方公网服务`. The six product entry points ignore all VILab URL environment overrides. Standalone `dev:api` retains the generic override.

Desktop packaging: scripts/desktop_backend.py initializes per-install secrets and SQLite in the user app data directory. Release-only desktop_backend.rs starts the bundled backend on a persisted per-install loopback port and stops it on exit. `yarn package:release` fixes the public VILab Origin; `yarn package:test` fixes LAN. Installation identities remain separate. VINote and VILab remain independent processes/repos.

Fresh-checkout startup: yarn dev runs bootstrap-dev.mjs to install frontend dependencies, create .venv and install requirements, and create .env with unique local secrets and config/desktop-public.json account defaults. Existing .env is preserved. --setup-only performs initialization without opening a window. Node 22+, Python, Rust/platform compilers and FFmpeg are system prerequisites.

Cloud shared runtime startup creates registered VINote tables and revokes PUBLIC/anon/authenticated direct access with RLS in one PostgreSQL transaction. `workspace_bootstrap.py` initializes a private content-image bucket using server credentials; existing public buckets fail startup. Configure once and start with `deploy/workspace/compose.yml`; never claim deployment or cloud migration from a local/mock regression.

## Meeting recording and speaker diarization

- 2026-10-16 Feishu recipient access: only new explicitly confirmed requests may send `recipient_access_policy="grant_view_and_notify"`; status advertises `recipient_access_protocol=1`. Freeze policy in the request fingerprint, revision and delivery snapshot; absent policy keeps historical contact check-only behavior. Selected contacts/groups receive only `view`, never downgrade existing access, and grant dispatch is journaled before the provider call. Legacy group grants use the same ambiguity journal without adding contact consent. `permission_unknown` blocks normal retry/resume. Explicit POST `/api/feishu/deliveries/{job_id}/verify-permissions` reads original provider ACLs and updates internal evidence only: no document/ACL/message writes and no worker scheduling. Positive evidence returns the recipient to pending for an explicit later notification retry; absent/failed evidence never re-grants. Body/message unknown remain protected. This is a VINote integration deployment, independent from VILab; mock/contract tests are not recipient delivery acceptance.

- 2026-10-16 user-approved adaptive request planning: segmentation is allowed, but model names must never select fixed request seconds. Recorded-audio policy comes from the selected model's `capabilities.recordedAudio` service budget, not an inferred provider duration limit. Prefer acoustic pauses within the PCM byte budget, retain exact contiguous sample boundaries and final-only checkpoints, preserve unknown inflight requests without replay, and never change the selected model automatically. Missing/invalid policy is a service configuration/update problem, not proof that the model cannot transcribe long recordings. See `docs/plans/2026-10-16-adaptive-asr.md`; source/offline evidence does not establish deployment or device acceptance.

- 2026-10-15 App credential refresh is serialized across independent same-identity request contexts. A queued caller reuses a preceding rotation only while its own identity, Origin and cancellation guards remain valid; MCP/Feishu request leases stay strict. Parallel meeting fact extraction must not rotate the same refresh token concurrently or misreport normal rotation as an account switch. Complete v5 ASR coverage and saved summary parts remain reusable on explicit recovery without model changes or another ASR submission. Actual App Aliyun 22m57s evidence is in `docs/reviews/2026-10-15-asr-terminal-22m-acceptance.md`; Doubao remains unaccepted.

- 2026-10-15 ASR wait/replay contract: desktop `asr_stream_service.py` and App `asrStream.ts` keep separate bounded upload and finalization windows derived from the selected audio interval. Only a confirmed LAST send/enqueue may start the finalization window once; partials and late/unconfirmed LAST cannot renew it. This covers the current default provider finish budget, not arbitrary administrator overrides. Once desktop binary audio has been attempted, transport ambiguity is `unknown_result` and cannot automatically replay; explicit provider codes remain intact but do not authorize audio replay. See `docs/asr-stream-timeouts.md`. Offline and rejection-only device checks are not real-provider acceptance.

- Generation persists account-bound `model_source_snapshot.json` before the media request and restores it on retry; changed preferences never replace a frozen task's concrete models/Origin. Authenticated `GET /api/task/{task_id}/model-confirmation` only reads failed-task recovery context. Legacy cloud tasks without a snapshot require an explicit NoteGenerator Sheet confirmation, then POST the same task retry with `{confirmed:true,mode:"cloud",server_url,asr_model,llm_model}`. Existing snapshots cannot be replaced; unknown confirmation outcomes are queried, not automatically replayed. Legacy local tasks without snapshots remain blocked pending a new confirmed operation.

- Mobile `recordingService.ts` accepts a preparation AbortSignal. Cancellation waits for the original native request and releases late capture before becoming idle. Failed release or native Stop retains the active guard and foreground service, exposes an unconfirmed state, and requires explicit Stop retry. A confirmed stop with a failed file save reuses the same pending record without calling native Stop again. The root mini bar labels preparation, cancellation, recording, pause, uncertain release and saving separately; busy is not synonymous with saving.

- Desktop custom recorder commands are explicitly allowed by `frontend/src-tauri/permissions/meeting-recorder.toml` and the default capability, scoped to the main/recorder windows and local backend Origin. Native WebView regression must check command errors as well as media playback.

- Actual meeting wall-clock start/end must come from explicitly supplied metadata/context, never from audio duration or the last transcript timestamp. Paused recordings have a shorter accumulated duration. Transcript/heading timestamps are recording offsets, not wall-clock times.

- `audio_preprocessing_service.py` owns conservative FFmpeg denoising on temporary audio, without trimming time. Explicit upstream empty recognition is recorded in `unrecognized_segments`; other STT failures remain errors. `DIARIZATION_CLUSTER_THRESHOLD` controls the diagnostic clustering threshold.
- `speaker_clustering_service.py` refines automatic grouping using sustained-turn embeddings, average linkage and silhouette selection. Short uncertain turns remain unknown; overlap remains explicit. Group count and silhouette are not identity accuracy guarantees.
- Meeting summaries synthesize themes, confirmed decisions and explicit actions; omit unsupported owners/deadlines/open questions. Both one-shot and hierarchical prompts keep wall-clock metadata separate from media offsets and avoid a duplicate closing AI summary.
- `app/llm/meeting_review.py` owns fact-review prompts. Meeting one-shot drafts are reviewed against original transcripts; hierarchical chunks are reviewed before merge, and final consistency is checked against reviewed chunks. Empty/failed reviews fail rather than returning the draft. Cloud review prefers available `MEETING_REVIEW_MODEL` (default `gpt-6-astra`), falls back to the primary model when absent, and never changes global preferences. Custom/local providers reuse their current model. Packaging includes this non-secret preference; calls and actual review model remain traced.
- `bootstrap-dev.mjs` prepares speaker runtime/models; web startup skips Rust checks. `dev.mjs` owns all four source modes, their process lifecycle and port checks. `desktop-build-profile.mjs` owns package identity/configuration and uses shared fixed origins. See `docs/running-scripts.md` and `docs/desktop-packaging.md`; never package `.env` or private meeting artifacts.

- `/meetings` owns meeting setup/history; `meetingCapture.ts` captures selected microphone plus optional display/system audio. Main-window `MeetingRecorderDock` owns the stream; `MeetingRecorderController` forwards native floating-window actions via Tauri events.
- Capture acquisition is cancellable. Screen selection waits for the user without a fixed timeout; microphone acquisition has a 20-second timeout. Cancel/reset/unmount releases acquired sources and stops late permission results. Runtime recorder errors release tracks and update the dock; stopping releases devices before async file finalization. Pausing retains capture for resuming; stopping/discarding releases it.
- Source development writes capture-stage events and original exceptions through Vite's local WebSocket to `data/desktop-capture.log` (bounded to approximately 1 MiB). These diagnostics exclude device IDs, device labels and media content; they are disabled in production builds. Backend logs do not contain WebView capture failures.
- `speaker_diarization_service.py` runs whole-recording local sherpa-onnx Pyannote/3D-Speaker clustering independently from cloud STT covering the entire recording (chunked when necessary). Provider timestamps are aligned by interval overlap; whole-file-only text is aligned in sequence by detected speaking duration and marked estimated. IDs are local to the recording; overlap labels indicate uncertain attribution, not separated overlapping audio.
- `speaker_worker.py` isolates sherpa detection and embedding refinement in one disposable spawned process per backend, using disk-backed PCM and bounded nonblocking progress IPC. The parent validates results and source/model identity before atomically saving speaker evidence; cached evidence is reused without rewriting. Windows Job Objects and Linux parent-death signals prevent inference workers surviving backend replacement. Packaged spawn uses the existing `multiprocessing.freeze_support()` entry; actual packaged execution still needs release verification. `scripts/check_speaker_worker_heartbeat.py` measures real inference responsiveness without printing speech or credentials.
- Media generation routes accept `diarize` and optional `speaker_count` (1–20); authenticated `GET /api/meeting-capabilities` returns `diarization.available`. Source development installs optional `requirements.diarization.txt` and models via `scripts/setup_diarization.py`; `DIARIZATION_MODEL_DIR` defaults to `data/models/diarization`. Desktop packaging stages these models.
- Uploaded video reuses its source file for screenshot extraction. Audio-only notes remove screenshot placeholders. Meeting video notes use `meeting_video`; audio uses `meeting_recording`.
- `scripts/check_meeting_generation.py --live` uses real cloud services through in-process desktop API routes and saves a personal test note; it is not native UI evidence. VILab ASR now uses paced VLA2 PCM WebSocket frames on desktop and App, with no model-name-based 12/60-second caps. Only explicit service `audio_duration_exceeded` with a valid declared limit changes the remaining interval layout; network errors never infer duration limits or switch models. Completed final intervals are cached by source/model/account. Partial `audioMs` may reflect submitted audio position rather than confirmed recognition coverage; label received progress as audio submitted for recognition, and only saved final intervals as durable. Explicit safe service error categories preserve the session UUID; only known transient failures retry the same model, and unknown final outcomes never auto-replay. The receive deadline is `duration * 1.5 + 90` seconds, independent of model duration capability. Desktop heartbeat failure cannot cut off provider finalization (`ping_timeout=None`); the receive deadline still bounds stalls. Recording itself performs no ASR; after stopping, ASR and independent speaker analysis run concurrently, both finish before LLM summary. Automatic meeting visualizations are cancelled. Actual public Aliyun framed tests covered 120 and 340 seconds; complete user recordings and other models remain separate acceptance work.

## Langfuse observability

Source-run HTTP tests may register task IDs and short labels in ignored `data/dev-tasks.json`. `frontend/devTasksPlugin.ts` serves these registrations only in Vite development; `SourceTaskProgress` uses authenticated task APIs to show live status in the open desktop/web UI. Production bundles exclude this panel. All four canonical source launchers use Vite HMR and Uvicorn reload; backend edits can interrupt active generation workers.

`app/services/tracing_service.py` owns Langfuse SDK 4 tracing for desktop requests only. Tauri identifies itself with `X-VINote-Client: desktop`; browser, Pi and ordinary backend calls must not initialize tracing. Business root names are exactly `桌面端｜会议纪要` and `桌面端｜笔记整理`, selected by product workflow rather than media type. Source desktop, test packages and release packages all trace; source desktop startup and packaging reject missing project configuration, while ordinary backend startup does not. Network/export failures remain fail-open for business tasks. Root chains correlate task_id/sessionId, hash local user IDs, use Chinese stage names, and record complete STT/LLM inputs and outputs, actual model parameters, usage and latency. Never record media binary, credentials, auth headers, local absolute paths or raw speaker embeddings. Configure LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and optional LANGFUSE_RELEASE. Both package profiles bundle the build-managed Langfuse credentials in backend resources; these are extractable by package holders, never commit or log them. This exception does not permit bundling .env, model keys or user credentials. Old per-install langfuse.env is ignored. Environments are development/test/production. Both builds require frozen-backend synthetic trace ingestion plus API readback and store a credential-free receipt in manifest.json. See docs/langfuse.md for scope and limitations.

Meeting setup automatically enables speaker diarization with automatic speaker count; do not expose diarization/count controls in the meeting UI. Users rename speakers in the transcript. Cloud ModelSourcePanel lists deployed ASR/LLM choices, persists selections per user and applies them to the next task. VILabCloudService.defaults resolves saved selections over service defaults, falling back only to a validated available service default when a saved selection is unavailable; explicit select() requests still reject invalid models; running task snapshots remain unchanged.

## Recording history and media lifecycle

### Final navigation contract (2026-10-11)

The user's latest approved structure supersedes historical navigation below: Meetings & Notes (Meetings / Notes), Files (All / Audio recordings / Screen recordings / Imported videos / Other files), Plugins (Feishu / MCP tools), Settings, and account via avatar. File types are page filters, not a long sidebar tree; projects/archive/trash belong inside content. Feishu authorization/defaults live in Plugins; version-specific publishing lives in content detail. Do not add a second Plugin Management entry routing to the same MCP page. See `docs/plans/2026-10-11-workspace-v3/navigation-final.md` for responsibilities, contextual returns, and unimplemented account/privacy capabilities.

### Workspace navigation and containers (2026-10-11)

The current desktop navigation is Meetings & Notes (Meetings / Notes), File Library and Plugins, with Settings and Account at the bottom. Meetings owns recording and meeting history; Notes owns writing, link/file intake and generated text. File Library owns current-device originals, without duplicating note bodies. Projects and archive are content filters; processing records are contextual recovery reached from status, not a primary sidebar item. Storage & Sync belongs only to Settings. `Projects.tsx` derives views from actual note project metadata; it does not create duplicate notes or pretend favorites are persisted. `Connections.tsx` owns the Feishu/MCP catalog; their detail pages return there unless given a validated contextual parent.

`lib/navigation.ts` validates contextual parent routes and preserves project/archive queries. Content rows open detail directly. `WorkspaceNote.tsx` owns the source/version Sheet and closes it before another task Dialog. Shared modal layers are task 50, selection 55, confirmation 60, tooltip 70; confirmations use AlertDialog. `RetainedOriginals.tsx` sequentially verifies recording metadata without preloading media and lists only available retained files. MainLayout owns the sole main landmark and lazy-page loading without unmounting navigation. Do not restore the duplicated content preview or completed-minutes list in the originals page.

Meeting capture uses the selected microphone as its required audio source. Screen recording requests video only, and the screen picker chooses only the recorded window or display. Persisted legacy options may still contain a system-audio flag, but capture ignores it so Windows/WebView system-audio failures never block recording. Display capture support depends on the runtime and screen picker.

Stopping saves its blob and PendingMeeting metadata in IndexedDB and releases capture resources. All captures return to /meetings?recordingSaved=<id> without STT/LLM, including persisted legacy minutes-mode settings. SavedRecordingChoice verifies ownership and durable idle status, then asks whether to generate notes; only an explicit choice starts processing complete media. Declining preserves local history. Failed local saves must succeed before offering generation. LocalRecordingCard owns replay/download/confirmed deletion/later generation. A saved recording is visible without a note; generation retains the local original and history until explicit user deletion. Preserve actual recording start/end separately from generation time and meeting wall-clock context.

MeetingMediaService owns GET/DELETE /api/notes/{note_id}/recording. File deletion preserves notes, transcripts, screenshots and the user's imported original. Deletion requires the note creator, matching recording_owner marker, and a single referencing note; unverified legacy/shared recordings remain downloadable. Only regular audio/video files under the task's media directory may be deleted. A recording_deleted marker prevents playback fallback to cached source audio. Local user-visible deletion uses a strict IndexedDB transaction and reports failures.

OPFS-backed recording blobs reference their source file. After IndexedDB history metadata commits, transfer that file out of the hook's temporary-file cleanup ownership; keep its fileName in PendingMeeting. Delete it only through verified local-history deletion. Automatic post-generation cleanup is disabled. Never remove the OPFS file on reset immediately after saving its Blob to IndexedDB: the Blob becomes unreadable.

Successful local saving sets `localRecordingSaved` independently of generation state and closes capture controls immediately. Background generation failure must restore history retry actions without reopening recording controls; unsaved recordings remain protected. History generation/retry starts directly without a second recorder confirmation. Per-card generation labels must match the active recording ID and processing phase, not the global busy flag.

`TranscriptionService.get_audio_duration` falls back to bounded ffprobe packet-timestamp scanning when container duration is missing, zero or nonfinite (common with MediaRecorder WebM). This does not modify the source recording; media offsets are never substituted for meeting wall-clock metadata.


### Meeting minutes completion (2026-09-18)

- `meeting_video_analysis_service.py` samples up to 24 timestamped frames and sends actual images to a dynamically resolved deployed model: prefer the task-snapshotted LLM selection; if explicitly unsupported/unavailable, use a deployed available model with explicit vision support. Missing vision metadata permits an actual call of the selected model, not an assumption of support. Visual evidence is included in summary and fact review separately from speech. This is sampled frame analysis, not exhaustive video understanding; absent vision service fails the task while local media remains available. `visual_observations.json` records evidence and offsets. Langfuse records offsets/text/model/usage, never image binaries.
- Saved unavailable cloud model preferences resolve to a validated service default for new tasks. Explicit invalid selections still fail; running snapshots do not change. The fallback has its own trace stage.
- Desktop main capture uses the native controller without a simultaneous in-page recording dock. Terminal main-window states close the native controller. A saved server note must retain the original recording before deleting the local pending copy.

- Desktop source startup isolates child process groups/consoles on Windows as well as Unix, so Python reload control signals cannot terminate the sibling Tauri window. Shutdown still terminates each owned process tree.

LAN/public source desktop identities remain `app.vinote.desktop.test.dev` / `app.vinote.desktop.dev`; both trace as development. Web does not enable desktop tracing. Source databases follow repository configuration, and web modes share the browser Origin/storage. Run one source instance at a time; reject occupied ports 8900/3100. All six canonical commands support `:plan` without launching or bootstrapping.

## 会后统一处理（2026-09-21）

会议页只确认麦克风；点击“开始会议”后再选择是否共享屏幕，选择共享才打开系统选择器，不预选是否生成纪要。录制期间不调用 ASR 或总结模型；结束后先保存完整原始媒体、释放设备并关闭控制，再由用户选择“生成会议纪要”或“暂不生成”。暂不生成时保留本地历史，之后仍可手动生成。说话人区分继续使用本地模型，VILab 负责完整音频转写和总结，结果按时间戳对齐。视频使用实际代表帧证据，不代表逐帧理解。

分段转写显示已完成音频时长、比例及基于实际分段耗时估算的剩余转写时间；整段请求没有中间结果时不虚构进度。所有进度采集仅在录制结束后运行。

### 完整录音证据与交付恢复（2026-10-10）

- VILab 的成功响应明确包含空字符串 `text` 且无有效 segments 时记为未识别区间；缺失字段、非字符串或矛盾响应仍报错。`NoteService` 将这些区间与“不得推断缺失发言”的说明传给总结模型。未识别不等于已确认静音。
- 详情独立重试逐字稿/媒体/飞书状态；飞书状态尚未读取成功时不可新建交付。异步请求按当前纪要序号校验，操作期间暂停状态轮询，失败保留输入与已成功阶段。
- 原生 Android 说话人运行时与持续发言特征修正在 App 仓库维护；声音编号、聚类分数与分组数均不保证参会身份准确。私人实测录音/产物仅保存在忽略目录。

本地历史持久化任务 ID、草稿 ID、失败阶段和进度。POST /api/task/{task_id}/retry 校验录制所有者与媒体后复用任务和有效产物。旧进程中断任务显示可重试。保存笔记后保留本地原始媒体直到用户明确删除。

MeetingCaptureWorkspace renders capture preview and controls. User end actions send request-stop; MeetingRecorderDock confirms in the main window, never in the native controller. The internal stop action remains available for source-ended/save flows. Recording uses no realtime ASR. Audio-meter failures are fail-open and must never stop media capture.

Meeting postprocessing workers live in frontend/src/lib/meetingProcessing.ts and never own capture state. Both history and note retry reuse the task. PATCH /api/notes/{note_id} accepts status-only changes, preserving title/content. Verification scope and remaining media-management gaps are documented in docs/plans/2026-09-21-meeting-postprocessing.md.


## App 录音库与纪要来源（2026-09-23）

VINote-app 的 recordingLibrary 按账号持久化原音频和录音草稿；generateRecording 直连 VILab 分段转写和总结，保存检查点供失败重试。录音库支持播放、导出、导入、后续生成和确认删除。仅录音模式不调用模型。Android 已加入麦克风前台服务；iOS 后台音频与转换源码待 Mac/iPhone 验证。生成纪要仍需前台，公网入口尚未配置。App 当前直连 Supabase 认证，不经过下述后端登录审计端点；纪要本机保存，未实现跨端同步。详见子仓库 README 和真机验证文档。

上传生成入口在任务目录写入不可覆盖的 generation_client 标记，保存笔记时从任务读取到 notes.generation_client（启动时兼容迁移旧表）。App 与桌面列表/详情显示 App 生成或桌面端生成；历史缺失显示来源未知，不能用当前保存/编辑客户端猜测。登录来源审计仍不向用户显示。

App 文档与脚本：子仓库 README.md / README.en.md 与 docs/build-and-deployment{,.en}.md 为当前直接 Supabase/VILab 架构说明；父仓库 docs/app-integration.md / docs/en/app-integration.md 记录边界。App npm android:standalone 是调试签名验收包；android:release / android:bundle 必须使用 VINOTE_ANDROID_* 签名环境变量，禁止回退调试证书。父仓库桌面运行和打包命令不隐式构建 App。

Video analysis never hardcodes a model name. `/api/vilab/models` retains capability metadata; model selection, traces and visual cache use the actual model, with cache also scoped to the server Origin. Source progress hides already-terminal tasks on initial load; results observed during the current session can be dismissed without deleting artifacts.

Cloud chat transport: VINote summary, fact review and sampled video analysis request SSE (`stream=true`) from VILab. `cloud_chat_stream.py` aggregates only final content, preserves usage, consumes reasoning/heartbeat events without storing them as answers, and rejects missing completion markers, truncation, provider errors and overlong streams. This avoids waiting for a complete non-streaming response behind the public proxy; silent upstream stalls can still time out. Model selection remains deployment-driven.
Transient SSE transport failures retry once with a fresh collector and the original stream time budget. Partial answers are discarded; HTTP/auth errors and invalid completion markers are not retried. Diagnostic logs include only exception type, attempt, header-receipt status and elapsed seconds, never raw exception text, endpoints, credentials or meeting content. Installed desktop builds require repackaging to receive this behavior.

会议标题默认采用 `YYYY-MM-DD HH:mm｜内容`：以已记录的录制开始时间创建“待生成纪要”占位，完成后从最终纪要主题生成标题；不使用生成时间冒充会议时间。本地录制支持改名，纪要详情支持编辑标题；生成时保留手动改过的录制或草稿标题。


### Note reading layout

Saved audio/video notes open in rendered preview mode; Markdown source is shown only when the user chooses Edit or Split. The note route fills the remaining app height with independent content scrolling, keeping its toolbar and media player visible. Key moments open in a Sheet on demand instead of permanently consuming note width. Local video uses a normal-aspect side panel on wide windows (stacked on narrow windows), with an expanded workspace view that keeps the same video element and playback position. Audio retains its bottom playback bar. Key-moment cards wrap long text and contain complete thumbnails without expanding the rail.


Release version alignment: source, web, backend API and production desktop share base version 0.4.0; test bundles append -test. scripts/project-version.mjs enforces the manifests and lock files before source startup and packaging. Canonical LAN/public origins remain unchanged. Publish desktop assets only after frozen-runtime and tracing smoke checks, with the artifact manifest and SHA-256 tied to the merged release commit.

Cloud model selectors show every server-configured catalog entry, including unavailable entries with a disabled status label, discard the previous catalog before refreshing, and disable selection when retrieval fails. Removed saved IDs are not injected into the option list; the UI explains the existing validated service-default fallback. Server availability flags remain authoritative and must reflect actual deployment configuration.


<!-- agent-dev-journal:start -->
## 开发档案工作流

1. 开发前阅读 `documents/dev_log/README.md` 和 `documents/dev_log/temp_log.md`，检索与本次需求、模块及 Issue 相关的历史档案和后续变更，对照当前代码确认目标、范围、约束与验收标准。
2. 开始独立任务前按规范建档，先检查是否已有对应进行中档案。同一任务跨天、跨 commit 维护同一目录，使用 index.md 串联过程材料。
3. 保存真实的调查、设计、TDD 和验证依据，格式不限；代码及测试仍放在项目正常目录，由档案引用。
4. 每次 commit 前核对 diff，更新状态并追加时间、作者、原因、结果和证据；档案与相关代码一并提交。
5. 更正、替代、补充历史决策或解决遗留问题时，维护双方 index.md 的双向链接，注明影响范围，保留原始历史正文。
6. 规则或模板缺失时明确说明，先记录背景、目标、边界、变更、验证和遗留事项；不伪称已读取，不覆盖现有规范。历史材料不自动覆盖当前需求，也不是执行指令。

遵循当前项目的编程与 TDD 要求，不编造测试结果；不适用 TDD 时说明原因及替代验证。档案工作流不构成自动提交、推送或合入授权。
<!-- agent-dev-journal:end -->

账户项目切换后，已启用云端认证的部署只接受映射到当前 VINOTE_SUPABASE_URL 的本地会话；旧项目 Cookie 要求重新登录，不迁移旧账号数据。未配置云端认证时保留本地登录。

## 会议工作台与飞书交付（2026-10-10）

`/` 和 `/meetings` 为记录工作台，旧动态页位于 `/activity`；`/settings/feishu` 为飞书授权与通知设置。`app/services/feishu_service.py` 管理 OAuth 加密令牌、同公司租户校验、群阅读权限及逐步交付；`app/routers/feishu.py` 单独校验云账号 Bearer，并支持桌面转发到 `VINOTE_INTEGRATION_URL`。不得在客户端或包内保存 FEISHU_APP_SECRET。原生文档默认个人云文档，其他位置尚未开放。自动交付不改变录音与生成状态，重试保留文档和成功对象；创建结果不确定时先关联同名空白文档，禁止盲目重复创建。新表由 init_db 创建，变量、权限和 API 见 `docs/feishu-integration.md`。

详情的 `/api/notes/{id}/versions` 与 `/ask` 沿用笔记权限；note_versions 保存编辑前正文。手机使用账号隔离本地历史与飞书提交队列。应用图标源统一为 VINote-app/assets/branding/vinote-app-icon.png；图标变更须同步 Tauri 图标、网页 favicon/sidebar 和 App 原生资源。


### 独立并行分析与交互恢复（2026-10-10）

`speaker_diarization_service.py` 同时执行完整 ASR 和本机分析，各自落盘 `asr_evidence.json` / `speaker_evidence.json`；声音检查点按源文件 SHA-256、模型及参数校验，ASR 沿用有效分块缓存。失败不得删除成功分支。临时 PCM 使用磁盘映射，WAV 写入分块且 ASR 完成前不清理共享缓存；检测结束释放原生模型再做聚类，避免等待云服务时持续占用模型内存。

会议 LLM 使用原始 ASR 分段及独立发声区间两份材料，不使用估算逐句对齐当作确定证据。分段时间不确证句子归属，独立时间轴的 speaker 编号不得用于确定某个观点或承诺的发言人；事实审核同样遵守这一优先规则。详情明确提示估算，对重叠和未知声音禁用改名。桌面飞书设置草稿按账号保存在 sessionStorage，失败/导航后可恢复；异步旧账号返回不得覆盖新账号。删除原录音仅成功后解绑对应播放器，失败保留播放与重试。

开发时保持一份 Tauri/Vite/Uvicorn 和一份手机 Metro；实际长录音核对顺序执行，构建/测试单工作进程。App Metro 的 maxWorkers=2 在下一次启动生效，不能为宣称配置生效而中断用户要求保留的当前热更新。

自动声音分组修正规则 revision=2：最多 128 个代表和 128 个补充窗口，每窗不超过八秒；一个有效组至少两段代表发言、累计特征时长六秒。孤立短声音为未知，重叠保留，拒绝组中心参与竞争以防误归。该版本纳入声音源签名，旧产物不冒充新规则结果；ASR 成功缓存继续独立保留。组数和 silhouette 均不能当作真实身份准确性。

工作台的本地历史/纪要读取错误在列表显示独立重试；空筛选有清除入口。飞书群读取失败不冒充账号状态读取失败，授权核验不得覆盖未保存通知设置。会议对话成功 HTTP 的空白回答仍按失败处理，保留输入并提供重试。

## 工作台界面与录音预览

`docs/ui-design.md` 记录两端页面结构与视觉约束。桌面 `MeetingWorkbench` 使用记录行与 `LocalRecordingPreview`，不再使用旧 `LocalRecordingCard`/`NoteGrid`。`RecordingWaveform` 调用鉴权 `GET /api/notes/{note_id}/waveform`，沿用原媒体权限/删除标记检查；`recording_waveform_service.py` 单并发、8kHz 聚合96点、FFmpeg60秒超时，缓存仅在源文件指纹及格式版本一致时复用。波形失败不影响回听或导出。`FeishuDocumentFooter` 只读已有交付状态，关闭交付弹窗后重新读取。

四个源码入口通过 `scripts/backend-dev.py` 的 Uvicorn supervisor 每秒轮询 app、main.py、mcp_server.py；不递归监听整个仓库或媒体/模型目录。Windows继续经过隐藏信号隔离控制台，工作目录及数据库配置不变。SourceTaskProgress 仅活动/失败读取时2秒轮询，全部终态后30秒；不属于生产功能。

### 账户与内容入口改造（2026-10-11）

桌面默认进入 /meetings；当前产品主导航将会议、笔记分为独立一级入口，另有文件库、插件，底部设置与账号。App 默认进入会议，底栏分别显示会议、笔记、文件库、插件。会议导入只接受音视频和逐字稿，网页、PDF、Word 与普通文档从笔记进入。存储与同步归设置；处理记录是任务恢复页，不再占一级导航。独立 MeetingAssistant 页面删除，/assistant 兼容跳转到内容页，对话仍在详情。ContentIntake 唯一装配内容来源选择，/write 保存文字笔记；待确认保存使用既有 durable workspace operation，不重新创建副本。旧顶部搜索栏样式删除，不恢复重复标题与操作。

authStore 区分 checking/authenticated/offline-known/expired/signed-out；连接失败不能清除已核验身份，冷启动未核验时提供重试而不开放缓存。退出与切换立即重置内容、工作空间、团队、LLM/STT 内存状态；读取请求通过代次丢弃旧返回。本机退出仍不撤销其他设备。资料迁移、服务端设备撤销和注销尚未实现，不得显示假成功。App 回前台先核验原账号，再恢复同步与交付；登录过期时先保护尚未保存录音。

MicrophoneCheck 仅做实时输入测量，不保存或上传测试声音。10 秒自动停止，取消、隐藏页面、关闭面板和切换设备均释放音轨及 AudioContext，迟到的授权结果也释放。音量测试期间禁止同时开始会议；原音保存/生成流程保持既有规则。


## 页面返回与导入结果恢复（2026-10-11）

笔记列表提供“写笔记”及两项清晰来源入口：“粘贴链接”和“导入文件”；录制与会议文件导入仍归会议。`sourceInput.ts` / App `noteIntake.ts` 解析公开视频分享链接。`document_source_service.py` / `source_note_job.py` 处理普通公开网页、PDF、DOCX；文档上限 20 MB、PDF 200 页，登录页、扫描件、加密文件及旧版 DOC 给出可操作错误。文档不进入 STT 或伪造音视频时间戳。App `NoteIntakeScreen` 按账号持久保存来源与任务回执，返回重入查询原任务；结果保存失败不能再次 POST，未知提交不得自动重发。App 笔记音频入口使用 `importLocalFile({ keepAudioInFiles: true })`，不创建会议录音记录；原录制导入默认行为保持兼容。

`generation_auth_service.py` 仅供 note 生成／状态／任务媒体路由使用：接受原有本地会话，或通过 Supabase 验证的已确认、非匿名 Bearer，必须匹配已有 `CloudAccountDB` issuer/subject 后映射本地用户。禁止仅按邮箱关联、新建映射或保存客户端令牌；未绑定返回 403、认证失效返回 401、提供方故障保留原错误。新 URL／文字任务写入录制所有者标记，沿用任务产物访问校验。此适配不代表正式共享部署的媒体生成服务已经接通。

导入页面按账号和 note/meeting 流程把已接收 task_id 回执保存在 localStorage。页面重入查询原任务；结果保存失败保留回执并恢复保存，不重新提交生成。处理记录提供恢复入口。该回执不是跨浏览器/跨端任务存储；收到 task_id 前的未知提交由独立来源请求回执机制核验，未接通该机制的调用不得自动重发。详情页通过显式 returnTo 保留内容列表/录制/处理来源；原文件页返回所属内容详情。App 外观、模型、连接、数据与同步为独立账号子页，返回保留真实来源。

本轮导航重新规划提案在 docs/plans/2026-10-11-workspace-v3/navigation-containers-replan.md；用户已退回现有侧边栏，提案中的项目与收藏尚不等于已落地功能。不要把旧截图和当前代码外观直接作为最终设计规范。

## 第一方翻译 MCP 与内容操作（2026-10-12）

`first_party_translation_service.py` owns the first-party Chinese/English adapter and account/run-scoped receipts. `POST /api/mcp-connections/first-party/translation {}` provisions an account-owned managed connection; `/api/mcp-first-party/translation` implements HTTPS Streamable HTTP initialize/notifications/tools/list/tools/call. `GET /api/mcp-connections/first-party/translation/receipts/{run_id}` reads the original result without replay. The server requires `VILAB_SERVER_URL` for the existing VINote cloud model Origin; current validated cloud JWT is used only in request memory. Never accept managed URL/auth spoofing or persist this JWT as a connection credential. Discovery and explicit tool grant precede bound per-call confirmation. Provider calls are bounded to 90 seconds with zero automatic retries; the bridge is bounded to 120 seconds. Unknown outcomes are read back, not replayed. Incomplete/refused/truncated output cannot be saved as a completed translation. Generic inbound `/mcp` remains independent.

Desktop NoteEditor is a reading page with one object heading and at most two primary actions; title inputs appear only while editing. Secondary actions are grouped in one content-operation disclosure. App NoteDetailScreen owns the content operation, version and text-generation sheets; close the preceding sheet before opening another. FileLibrary preserves category/search context when entering selected-file intake; selecting a file does not submit generation. Existing unresolved source receipts are protected, and preparation failures provide retry plus a usable return. Ordinary document pages must not label content or templates as meeting minutes.

`GET /api/mcp-connections/first-party/translation/models` returns the current verified owner's available LLM catalog and validated optional default. Both clients require an explicit model choice when the default is absent; never choose the first catalog item or replace an unavailable choice silently. `vinote_translate_text` binds the selected optional `model` alongside text and `target_language` to the preview and confirmed request. Changed tool definitions require discovery and explicit grants again; old receipts remain readable without replay or rewriting their arguments.

App retains independent `NotesView` snapshots for Meetings, Notes and each project in the authenticated root. Detail returns restore search/filter/project; sign-out clears these view snapshots and pending navigation context. Translation saving fixes the original account namespace and checks it before and after asynchronous reads/writes; a later account with the same note ID must never receive the previous account's result. These checks do not establish acceptance of all offline/conflict or account-switch flows.

Top-level App headers consume `MainAccountActionContext`, keeping the avatar beside the page title; subpages keep Back instead. The root no longer creates an empty account-only row. Notes list reads use one account-bound local/workspace snapshot, coalesce background notifications, and retain this account's already-read rows on return; only acknowledged cloud operations establish synced status. Compact source cards remain explicit, stack on narrow/high-font-scale screens, and never submit on selection.

Desktop source lookup from a workspace detail uses `/files?note=<verified-local-note-id>` and a validated detail return context. File Library filters only actual owner-scoped `note_id` / recording associations; file selection uses an existing row's file ID, never the note ID or a title guess. Missing associations are reported as not found on this device, not deleted. The original source lookup must not open a legacy duplicate note body. Legacy document uploads which only retained extracted text cannot reconstruct the original PDF/Word; current document intake registers a real local original before submitting generation.

Local `/api/files` now records a purpose (`meeting` or `note`) independently from format; upload accepts multipart `purpose`, and owner-only `PATCH /api/files/{id}` reclassifies an original without moving/deleting it. Existing rows infer purpose only from linked content; unlinked originals remain in a review group until the user classifies them. File Library groups by purpose first and format second. Links have no device-original file and belong only to Notes intake. Deleting an original does not delete a meeting or note.
File Library format filters are All / Audio / Video / Document; a screen recording is a Video subtype identified by a source badge, never a sibling format filter beside Video.

Source-only FileLibrary views hide global import/search/type controls and show only verified associated originals. Recovery links select the actual retained recording ID; absent IDs show an honest unavailable state rather than another recording. Server file timestamps from SQLite are UTC even when the offset is omitted; `serverTimestamp` normalizes that channel only, never user-supplied meeting wall-clock times.

App original-recording details omit library-wide import/navigation actions. Externally opened details return to their source; list-selected details return to the recording list first, for header and hardware Back alike. Local original reads resolve independently of cloud minutes reads, so a notes outage cannot hide playback/export. Unknown minutes status blocks new generation until readback/retry succeeds; missing originals, failed reads and empty libraries remain distinct. Settings preserve validated source/query/hash through subsection and overview returns; self-referential or external parents use the safe notes fallback.

### Device-local per-item workspace policy (2026-10-12)
New App content is local-only unless explicitly enabled. Existing acknowledged authorized content retains its policy; mappings/cache alone are not authorization. Canonical workspace keys stay unchanged, and device policy is not a global cloud deletion. GET /api/workspace/operations/{operation_id}?note_key=... returns the original owner-scoped committed revision only, without replay/latest content. /status advertises item_sync_policy=1, operation_receipts=1 and explicit_import=1 with policy_scope=device-local. POST /import-local requires {keys:[...],sync_authorized:true}; omitted/empty selection never imports all content. No new DB table or main.py registration is required: receipts use the existing registered workspace_operations table. This source contract is not evidence of deployment.
