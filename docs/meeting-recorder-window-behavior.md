# Meeting recorder floating window behavior

## Web behavior

The web app keeps the meeting recorder as a small draggable overlay inside the VINote browser window. It is mounted at the app shell level, so it remains available while navigating within VINote.

The web UI must not show a pop-out/export window control or an inside/outside mode. Browser tabs cannot guarantee true OS-level always-on-top behavior.

## Desktop behavior

The Tauri desktop app opens a native recorder window by default:

- the idle main app shows only the lower-right recorder launcher;
- clicking the launcher in the main app opens one native `recorder-window` (or re-focuses an existing one); the main-window launcher remains available until the recorder React page emits its ready event;
- if a packaged WebView does not become ready within the bounded startup timeout, VINote closes that unusable child window and automatically falls back to the in-window recorder so microphone capture remains available;
- duplicate Start clicks focus the existing recorder window rather than creating duplicates;
- the recorder window is small, borderless, skipped from taskbar, positioned near the screen edge/top, draggable by native window movement from the recorder surface, and configured with `always_on_top`;
- the expanded native window starts at `360x132` px and grows vertically (up to `400` px) when the failed/success state adds the re-record or view-note action row, measured by a `ResizeObserver` in the recorder panel; the minimized native window is fixed to `320x48` px and contains only the compact pill;
- clicking the recorder window's close (X) control hides the native window via `getCurrentWindow().hide()` without destroying the webview, so the recording pipeline stays alive and the launcher can re-open it;
- the recorder window also requests all-workspaces visibility as the closest supported behavior for fullscreen/space switching;
- the recorder window loads `index.html?recorderWindow=1&autostart=1`, mounts only the recorder panel as window content, owns the actual `MediaRecorder`, and emits state updates back to the main window;
- while recording or processing is active, closing the main VINote window hides the main window instead of destroying the app process, so the recorder window stays alive;
- quitting or force-killing the VINote process still stops recording because browser `MediaRecorder` lives inside the Tauri process. Surviving a true process kill would require a separate native/background recorder process.

The recorder exposes Stop only after Pause. While actively recording, the Stop control is muted and disabled so the safe path is Pause, then Stop.

The desktop recorder is still rendered by Tauri's webview engine because VINote is a Tauri React app. The important behavior is that the webview fills the native window exactly: desktop drag/minimize/restore are native window actions, while the browser web app keeps DOM-based overlay positioning.

## Permission behavior

Desktop recording performs native microphone preflight first, then browser `getUserMedia` readiness checks in the recorder window. Denied, restricted, timed out, missing-device, busy/unavailable, and unsupported microphone states must surface as recorder failures instead of leaving a half-open recording session.

## Platform notes

Always-on-top and all-workspaces visibility are requested through native Tauri APIs. Some operating systems or window managers may still prevent overlays above exclusive fullscreen applications, so visibility above every fullscreen app is best-effort rather than guaranteed.

The recorder window requests transparency so the native window hugs the panel visually without extra square corners. On macOS this uses Tauri's `macos-private-api` support, which is appropriate for local desktop distribution but not accepted by the Mac App Store.
