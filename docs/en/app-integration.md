# App and desktop integration boundaries

[简体中文](../app-integration.md) · [App README](../../VINote-app/README.en.md) · [App build guide](../../VINote-app/docs/build-and-deployment.en.md)

`VINote-app/` is an independent React Native Git submodule at https://github.com/orulink-ai/VINote-app with `main` as its main branch. The parent integrates into `dev`. Initialize with `git submodule update --init --recursive`; do not use `--remote` to bypass the reviewed pinned commit. Push app commits before updating the parent gitlink.

## Accounts, origins and data

The app connects directly to the shared Supabase project and VILab, without the desktop FastAPI process. Shared accounts do not imply shared data: app audio, processing checkpoints and notes remain local to the phone, isolated per account. Desktop note synchronization is not implemented.

The parent's `auth_login_events` table records successful logins through FastAPI sign-in/registration verification endpoints: user, UTC timestamp, allowlisted client and platform. Headers are self-reported hints, never authorization. Direct Supabase app logins do not enter this table; centralized auditing remains incomplete. Ordinary sign-out clears this client's credentials without disconnecting the cloud account used by other clients. Existing JWTs follow expiry rules; sign-out does not revoke every device.

Upload tasks persist the first `generation_client` marker; saving notes reads that marker, and editing/retry does not rewrite origin. Legacy notes or corrupt/missing markers have unknown origin; saving-request headers are not used to guess it. App-local notes have mobile origin; this does not provide synchronization. Database startup initializes the audit table and compatibly adds the notes origin column.

Complete valid saved ASR/LLM selections can bypass an older service's default-model endpoint. Unavailable selections still fall back to validated service defaults; personal authentication is never bypassed.

## Development and packaging

Existing parent commands `yarn client:dev`, `yarn client:test:dev`, `yarn client:test` and `yarn client:production` remain desktop-only. They do not launch or package the app. In the submodule, use `npm ci`, `npm start` and `npm run android` for development. `npm run android:standalone` creates a debug-signed acceptance APK with embedded JS; `android:release` and `android:bundle` require your signing environment variables. Follow the app's bilingual build guide. Never commit APKs, private recordings, tokens or keys to either repository.

App 1.1.0 currently uses LAN endpoints, including the Android account proxy. Independence from USB/Metro does not remove LAN requirements. No public tunnel has been deployed. iOS requires Mac/iPhone build and validation. Generation requires the foreground. App speaker diarization is deferred; desktop diarization is not automatically available on mobile.

## Merge and verification

Merge the app into `main`, update the parent to the exact app commit, then merge the parent into `dev`. Do not force-push or rewrite history. Pushes to `dev` normally run `.github/workflows/deploy-pi-dev.yml` to deploy the Pi test environment. For merge-only changes without deployment, use GitHub's supported `[skip ci]` marker in the merge commit. This leaves workflow configuration unchanged and does not deploy VILab.

Review checks include app tests/types/configuration regressions, parent auth/note-origin/cloud-model tests and a frontend production build. Historical device evidence is documented separately in the app repository; passing checks does not certify iOS, public access or background processing.
