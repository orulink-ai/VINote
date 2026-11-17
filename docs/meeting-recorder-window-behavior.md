# Meeting recorder floating window behavior

## Web behavior

The web app keeps the meeting recorder as a small draggable overlay inside the VINote browser window. It is mounted at the app shell level, so it remains available while navigating within VINote.

The web UI must not show a pop-out/export window control or an inside/outside mode. Browser tabs cannot guarantee true OS-level always-on-top behavior.

## Desktop behavior

Starting a meeting from the Meetings page starts capture in the main WebView. Once capture begins, VINote opens a native `recorder-window` at `/?recorderWindow=1&controller=1`. The controller displays elapsed time and sends pause, resume, and stop commands to the main window. Stop is available while recording or paused and opens the save confirmation.

The controller's Hide controls button calls the native window's `hide()`. The recording stays in the main WebView and continues to receive media while the process and capture session remain active. Reopening the active controls shows the existing window and preserves its session. During active capture, Tauri intercepts a close request for either window and a normal application exit request. Closing the main window hides it and brings the controls forward when they exist. Force quit, system sleep or a development rebuild can interrupt capture.

The compatibility recorder window at `/?recorderWindow=1&autostart=1` can own capture itself. It uses the native expanded window and compact pill, with fixed baseline sizes of `360x132` and `320x48`. Both native windows can be dragged and request always-on-top and all-workspaces visibility.

## Permission behavior

On macOS, the app declares `NSMicrophoneUsageDescription` and requests native microphone access before the capture WebView calls `getUserMedia`. Permission or device failures surface in the recorder. The separate microphone test releases its stream when hidden; it is independent of an active meeting recording.

## Platform notes

Always-on-top and all-workspaces visibility are requested through native Tauri APIs. Some operating systems or window managers may still prevent overlays above exclusive fullscreen applications, so visibility above every fullscreen app is best-effort rather than guaranteed.

The recorder window requests transparency so the native window hugs the panel visually without extra square corners. On macOS this uses Tauri's `macos-private-api` support, which is appropriate for local desktop distribution but not accepted by the Mac App Store.

To verify background capture on a device, start a short meeting, hide the controls or switch to another app while speaking, then reopen the controls, end and save. Check that the saved audio contains the speech from both intervals. Window lifecycle tests cover hide, minimize and close behavior; they cannot verify recorded audio while the operating system manages a background WebView.
