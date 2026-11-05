# Meeting playback and progress repair

Scope: the installed desktop's twelve-minute screen recording, meeting progress,
capture-time titles, failed-history removal and detail action clutter.

## Evidence and implementation

- Original WebM: 720.179 seconds, 18,424 video packets and 12,013 audio packets.
  A stream-copy preview retained every packet. The tail decode check nevertheless
  failed: FFmpeg's null output rounded variable-frame timestamps to nominal FPS
  and reported duplicate DTS. Decode validation now preserves millisecond video
  timestamps; packet equality, duration, tail decoding and immutable originals
  remain checked. A synthetic irregular-frame regression failed before the fix.
- Recording preview uses indexed task media independently of saved-note deletion.
  The task route preserves ownership, canonical source and Range checks. Export
  remains the original bytes; unsubmitted recordings retain their blob preview.
- Meeting rows now retain actual processing stage/measurements and poll original
  tasks. Capture-time labels survive grouping; explicit renames take precedence.
- Pending detail shows task progress instead of presenting placeholder text as
  completed minutes. It does not offer publication of unfinished content.
- Failed-history deletion is owner-scoped display removal, not deletion of
  recordings, notes or replay-protection receipts. Unknown/running results cannot
  be removed as confirmed failures.

## Design reference lock

Keep VINote's existing neutral typography, spacing and components. The user's
screenshots identify the redundant copy/version headings and explanatory blocks.
Refero live research returned NO_SUBSCRIPTION; fallback references are the skill's
`craft-details.md` (inline async feedback, semantic controls, confirmation) and
`copywriting.md` (orientation, status, action; concise product labels). Use a
compact wrapping secondary-action disclosure, retain at most two primary content
actions, and preserve original-file access and meaningful return navigation.

## Validation

Media service and video-evidence tests: 56 passed, 3 skipped (platform symlink and
opt-in private fixtures). The actual twelve-minute source also passed full packet
and seek checks in an isolated preview folder; original hash was unchanged.
Full frontend/backend validation and installed-package acceptance are tracked in
the release handoff; source tests alone do not establish desktop acceptance.

Final frontend suite: 1,901 tests passed. Backend full suite: 5,056 passed,
16 skipped; four existing real-symlink tests could not create fixtures on this
Windows account (WinError 1314). Linux CI must execute those security regressions.
Independent source review findings (note-dependent media, terminal status labels,
cached pending results and stale-draft overwrite) were corrected and re-reviewed.
