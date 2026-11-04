# Speaker identity and Feishu delivery implementation plan

**Goal:** Connect audio/video speaker evidence to verified Feishu contacts and reuse confirmed meeting identities for opted-in document publication and recipient notification.

**Architecture:** Extend the existing owner/canonical-meeting/evidence/Feishu-connection-bound participant confirmation. Original transcript speaker IDs remain immutable; human-confirmed mappings are separate metadata. Exact name and visual evidence produce explainable candidates, never unconditional recipients. Existing frozen automatic delivery/outbox remains the sole publication path. Existing user direction delegates routine implementation choices and asks to proceed without a new design approval loop.

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy, React/TypeScript, existing Feishu CLI transport.

- [x] Backend: expose speaker segments and candidate contact associations from retained transcript and visual evidence. Accept explicitly confirmed speaker/contact assignments, validate real speaker IDs and selected contact proofs, persist with CAS/evidence and account binding. Preserve existing participant-only API compatibility. No automatic biometric enrollment.
- [x] UI: evolve existing meeting participant panel into speaker/contact review, show short utterances/time/evidence, unknown/ambiguous distinction, exact contact picker, edit/clear mapping. No page-blocking requirement to read minutes. Gate contact-dependent UI on actual Feishu enablement.
- [x] Delivery: simplify opt-in for future meetings into a comprehensible auto-publish-and-notify choice. Respect existing destinations, manual recipients and saved consent; keep unconfirmed identities out. Confirmed mappings feed existing participants and waiting-unsent intents, never replay accepted/unknown sends. No actual external sends during automated testing.
- [x] Integration: ensure mappings are reachable in recording and screen-recording notes, preserved across summary versions, and usable for future summary attribution without rewriting originals or old minutes. Verify off/connected/manual/automatic cases.
- [x] Tests: source ownership, ambiguous evidence, malformed speaker IDs, selected-contact proof, stale/ABA scope, unknown/no-speaker recordings, no-Feishu path, future-only opt-in, deduplication and frozen sends. Single-worker tests coordinated across agents; final build and code review.

Voiceprint vendor registration needs an explicit enrollment UI and per-user provider scope; no silent upload or use of an admin-wide voiceprint library. Screen evidence uses displayed names/active-speaker indications and times, not facial identification. Names merely mentioned in speech/documents are not attendance proof. Contact matching does not authorize message sending by itself.

## Implemented evidence boundaries

- Real authenticated local read of the previously generated saved meeting returned HTTP 200, can_confirm=true, 14 speaker rows, zero contact-name candidates, and unconfirmed attendance. No identities were guessed or saved during acceptance.
- Verified video-frame OCR is associated only with actual raw speaker-segment or independent speaking-turn intervals; a broad transcript window is not substituted for a speaking turn. Free visual prose does not fan out to all speakers. Active-speaker UI detection and biometric voice enrollment are not implemented.
- New summary versions freeze current confirmed names in the accepted source-request receipt and recheck meeting/evidence/connection/revision before using them. Revoked or unavailable mapping omits names without blocking generation. Original ASR/previous minutes stay unchanged.
- Import entry bug was repaired separately: a fresh owner-scoped draft prevents old failed global receipts from intercepting new imports; exact historical task/operation URLs still recover the original task.

Final integration: frontend TypeScript + Vite production build passed after all agents froze changes. Existing chunk-size and Browserslist warnings remain non-blocking. No deployment, real model request or actual Feishu publication was used for this acceptance.
