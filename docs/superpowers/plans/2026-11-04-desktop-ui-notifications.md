# Desktop UI and Notifications Implementation Plan

> **For agentic workers:** Use the existing delegated implementation tasks; preserve the shared dirty checkout.

**Goal:** Improve desktop reading/list hierarchy and deliver one actionable completion/failure notification, in app while foreground and via the OS while background.

**Architecture:** Shared account-scoped notification state and a layout-level task observer, using existing retained receipts without generating or publishing again. Native notifications use the official Tauri integration; unavailable permission falls back to the in-app inbox. Existing routes and source/version identity stay unchanged.

**Tech Stack:** React, Zustand, Tailwind, Tauri 2.

**Spec:** docs/ui-design.md and user-confirmed foreground/background notification preference in this chat.

## Reference lock and scope

Existing flat workspace, user-provided unslop, Refero bundled typography: neutral type, aligned rows, restrained borders, one clear primary action. Refero live research was unavailable due to subscription; reuse the documented research instead of pretending fresh screen evidence. Reading body stays comfortable width; controls remain keyboard accessible. No screen takeover or actual test notifications to other people.

- [x] Notifications: owner-scoped dedupe; no historical terminal replay; foreground/background routing; click-through; permission fallback; real settings replacing fake toggles. Tests include account ABA and accepted work overtaking a silent historical baseline.
- [x] Meetings and reader: align metadata/version rows, contain toolbar secondary actions, limit body width; existing behavior regressions.
- [x] Generation: remove stale mandatory-review language, compact current phase/elapsed/steps, retain truthful measured-only percentages and error recovery.
- [x] Producer hooks: new upload, new generation, summary version and captured recording acceptance; notification storage failure does not interrupt accepted work. Recording recovery targets the exact meeting when no saved note is found.
- [x] Date organization: date lists with date picker; editable display title/date separate from canonical identity; unknown capture dates stay unknown. Archive becomes a secondary filter. Imported files retain their filenames as provenance, not main titles.
- [x] Feishu contacts: same account returned 21 contacts while old cache had zero. Initial read refreshes discovery; exact-name remote search and visible partial/error states. Normal local refresh verified 21 contacts / 26 groups.
- [x] Feishu setup: single-page connection, destination and sending preferences; advanced configuration collapsed. Remove MCP product entry points, preserve historical data and credentials; old routes redirect to Feishu.
- [x] Browser component visual check with synthetic content; screenshot in `data/ui-meeting-date-preview-20261104.png`. Temporary harness removed. Native window remained untouched; occluded screenshot did not provide valid native visual evidence. No actual OS toast sent.

## Deliberate remaining boundaries

Voiceprint registration and screen-based speaker candidate matching are researched in `2026-11-04-speaker-identity-research.md`, not enabled as a user feature. Portable export/migration bundles are not implemented. Imported ungenerated recordings remain in their own date-grouped section. Windows OS notification behavior still needs installed-app acceptance; component tests and Cargo checks are not that acceptance.

No commit, merge, deploy, model invocation or Feishu publication is part of this work.
