use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

#[cfg(not(debug_assertions))]
mod desktop_backend;

use tauri::{
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, RunEvent, Size, State, Url,
    WebviewUrl, WebviewWindowBuilder, WindowEvent,
};

const RECORDER_WINDOW_LABEL: &str = "recorder-window";
const RECORDER_WINDOW_TITLE: &str = "VINote Meeting Recorder";
const RECORDER_WINDOW_EXPANDED_WIDTH: f64 = 360.0;
const RECORDER_WINDOW_EXPANDED_HEIGHT: f64 = 132.0;
const RECORDER_WINDOW_MINIMIZED_WIDTH: f64 = 320.0;
const RECORDER_WINDOW_MINIMIZED_HEIGHT: f64 = 48.0;
const RECORDER_WINDOW_EDGE_PADDING: f64 = 24.0;
const MAIN_WINDOW_LABEL: &str = "main";
const NAVIGATE_EVENT: &str = "vinote-navigate";

#[derive(Default)]
struct RecorderRuntimeState {
    active: AtomicBool,
}

impl RecorderRuntimeState {
    fn is_active(&self) -> bool {
        self.active.load(Ordering::SeqCst)
    }

    fn set_active(&self, active: bool) {
        self.active.store(active, Ordering::SeqCst);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(RecorderRuntimeState::default())
        .plugin(tauri_plugin_opener::init())
        .setup(|_app| {
            #[cfg(not(debug_assertions))]
            desktop_backend::start(_app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            request_microphone_access,
            open_recorder_window,
            close_recorder_window,
            set_recorder_active,
            show_main_window,
            set_recorder_window_layout,
            set_recorder_window_size,
        ])
        .build(tauri::generate_context!())
        .expect("error while building VINote");

    app.run(handle_run_event);
}

fn recorder_window_url() -> &'static str {
    "index.html?recorderWindow=1&autostart=1"
}

fn recorder_window_reopen_url(mut current_url: Url) -> Url {
    let reopen_nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    current_url.set_path("/");
    current_url.set_query(Some(&format!(
        "recorderWindow=1&autostart=1&reopen={reopen_nonce}"
    )));
    current_url.set_fragment(None);
    current_url
}

fn recorder_window_layout_size(layout: &str) -> Result<(f64, f64), String> {
    match layout {
        "expanded" => Ok((
            RECORDER_WINDOW_EXPANDED_WIDTH,
            RECORDER_WINDOW_EXPANDED_HEIGHT,
        )),
        "minimized" => Ok((
            RECORDER_WINDOW_MINIMIZED_WIDTH,
            RECORDER_WINDOW_MINIMIZED_HEIGHT,
        )),
        _ => Err("invalid_recorder_window_layout".into()),
    }
}

fn recorder_window_position(app: &AppHandle) -> Option<LogicalPosition<f64>> {
    let monitor = app.primary_monitor().ok().flatten()?;
    let position = monitor.position();
    let size = monitor.size();
    let scale_factor = monitor.scale_factor();
    let logical_x = position.x as f64 / scale_factor;
    let logical_y = position.y as f64 / scale_factor;
    let logical_width = size.width as f64 / scale_factor;
    let x =
        logical_x + logical_width - RECORDER_WINDOW_EXPANDED_WIDTH - RECORDER_WINDOW_EDGE_PADDING;
    let y = logical_y + RECORDER_WINDOW_EDGE_PADDING;
    Some(LogicalPosition::new(x.max(logical_x), y.max(logical_y)))
}

#[tauri::command]
async fn open_recorder_window(app: AppHandle) -> Result<String, String> {
    // WebView2 window creation must not run in a synchronous IPC command:
    // it can deadlock the Windows UI thread before microphone access begins.
    if let Some(window) = app.get_webview_window(RECORDER_WINDOW_LABEL) {
        // Recover the window from whatever state it was left in by a prior
        // close / hide cycle. Re-navigate first so a stale or unloaded webview
        // recreates the recorder React tree instead of relying on an event
        // listener that may no longer exist.
        if !app.state::<RecorderRuntimeState>().is_active() {
            if let Ok(url) = window.url() {
                let _ = window.navigate(recorder_window_reopen_url(url));
            }
        }
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        let _ = window.set_always_on_top(true);
        return Ok("existing".into());
    }

    #[cfg(debug_assertions)]
    let recorder_url = WebviewUrl::App(recorder_window_url().into());
    #[cfg(not(debug_assertions))]
    let recorder_url = WebviewUrl::External(app.get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or("Main window not found")?.url().map_err(|e| e.to_string())?
        .join("/?recorderWindow=1&autostart=1").map_err(|e| e.to_string())?);
    let mut builder = WebviewWindowBuilder::new(
        &app,
        RECORDER_WINDOW_LABEL,
        recorder_url,
    )
    .title(RECORDER_WINDOW_TITLE)
    .inner_size(
        RECORDER_WINDOW_EXPANDED_WIDTH,
        RECORDER_WINDOW_EXPANDED_HEIGHT,
    )
    .min_inner_size(RECORDER_WINDOW_EXPANDED_WIDTH, 48.0)
    .max_inner_size(RECORDER_WINDOW_EXPANDED_WIDTH, 400.0)
    .resizable(false)
    .decorations(false)
    .transparent(true)
    .shadow(false)
    .always_on_top(true)
    .visible_on_all_workspaces(true)
    .skip_taskbar(true)
    .visible(true);

    if let Some(position) = recorder_window_position(&app) {
        builder = builder.position(position.x as f64, position.y as f64);
    }

    let window = builder.build().map_err(|error| error.to_string())?;
    let _ = window.set_focus();
    Ok("created".into())
}

#[tauri::command]
fn close_recorder_window(
    app: AppHandle,
    state: State<'_, RecorderRuntimeState>,
) -> Result<(), String> {
    state.set_active(false);
    if let Some(window) = app.get_webview_window(RECORDER_WINDOW_LABEL) {
        window.close().map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn apply_recorder_window_layout(window: &tauri::WebviewWindow, layout: &str) -> Result<(), String> {
    let (width, height) = recorder_window_layout_size(layout)?;
    let size = Size::Logical(LogicalSize::new(width, height));
    window.set_size(size).map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn set_recorder_window_layout(app: AppHandle, layout: String) -> Result<(), String> {
    let window = app
        .get_webview_window(RECORDER_WINDOW_LABEL)
        .ok_or_else(|| "recorder_window_not_found".to_string())?;
    apply_recorder_window_layout(&window, &layout)
}

#[tauri::command]
fn set_recorder_window_size(app: AppHandle, width: f64, height: f64) -> Result<(), String> {
    let window = app
        .get_webview_window(RECORDER_WINDOW_LABEL)
        .ok_or_else(|| "recorder_window_not_found".to_string())?;
    let size = Size::Logical(LogicalSize::new(width, height));
    window.set_size(size).map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn set_recorder_active(active: bool, state: State<'_, RecorderRuntimeState>) {
    state.set_active(active);
}

#[tauri::command]
fn show_main_window(app: AppHandle, route: Option<String>) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or_else(|| "main_window_not_found".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;

    if let Some(route) = route {
        app.emit_to(MAIN_WINDOW_LABEL, NAVIGATE_EVENT, route)
            .map_err(|error| error.to_string())?;
    }

    Ok(())
}

fn focus_recorder_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(RECORDER_WINDOW_LABEL) {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn should_protect_window_close(label: &str, recorder_active: bool) -> bool {
    recorder_active && (label == MAIN_WINDOW_LABEL || label == RECORDER_WINDOW_LABEL)
}

fn should_prevent_app_exit(recorder_active: bool) -> bool {
    recorder_active
}

fn handle_run_event(app: &AppHandle, event: RunEvent) {
    match event {
        #[cfg(not(debug_assertions))]
        RunEvent::Exit => {
            if let Some(backend) = app.try_state::<desktop_backend::Backend>() {
                if let Ok(mut child) = backend.0.lock() {
                    if let Some(mut child) = child.take() { let _ = child.kill(); let _ = child.wait(); }
                }
            }
        }
        RunEvent::WindowEvent { label, event, .. } => {
            let recorder_active = app.state::<RecorderRuntimeState>().is_active();
            if !should_protect_window_close(&label, recorder_active) {
                return;
            }

            if let WindowEvent::CloseRequested { api, .. } = event {
                if label == MAIN_WINDOW_LABEL {
                    api.prevent_close();
                    if let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) {
                        let _ = window.hide();
                    }
                    focus_recorder_window(app);
                } else if label == RECORDER_WINDOW_LABEL {
                    api.prevent_close();
                    focus_recorder_window(app);
                }
            }
        }
        RunEvent::ExitRequested { api, .. } => {
            if should_prevent_app_exit(app.state::<RecorderRuntimeState>().is_active()) {
                api.prevent_exit();
                focus_recorder_window(app);
            }
        }
        _ => {}
    }
}

#[tauri::command]
fn request_microphone_access() -> Result<String, String> {
    request_microphone_access_impl()
}

#[cfg(target_os = "macos")]
fn request_microphone_access_impl() -> Result<String, String> {
    use std::sync::mpsc;
    use std::time::Duration;

    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2_av_foundation::{AVAuthorizationStatus, AVCaptureDevice, AVMediaTypeAudio};

    let media_type =
        unsafe { AVMediaTypeAudio.ok_or_else(|| "microphone_media_type_unavailable".to_string())? };
    let status = unsafe { AVCaptureDevice::authorizationStatusForMediaType(media_type) };

    if status.0 == AVAuthorizationStatus::Authorized.0 {
        return Ok("authorized".into());
    }
    if status.0 == AVAuthorizationStatus::Denied.0 {
        return Err("microphone_denied".into());
    }
    if status.0 == AVAuthorizationStatus::Restricted.0 {
        return Err("microphone_restricted".into());
    }

    let (sender, receiver) = mpsc::channel();
    let completion = RcBlock::new(move |granted: Bool| {
        let _ = sender.send(granted.as_bool());
    });

    unsafe {
        AVCaptureDevice::requestAccessForMediaType_completionHandler(media_type, &completion);
    }

    match receiver.recv_timeout(Duration::from_secs(120)) {
        Ok(true) => Ok("authorized".into()),
        Ok(false) => Err("microphone_denied".into()),
        Err(_) => Err("microphone_request_timeout".into()),
    }
}

#[cfg(not(target_os = "macos"))]
fn request_microphone_access_impl() -> Result<String, String> {
    Ok("unsupported_platform".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recorder_window_uses_stable_label_and_bootstrap_url() {
        assert_eq!(RECORDER_WINDOW_LABEL, "recorder-window");
        assert_eq!(
            recorder_window_url(),
            "index.html?recorderWindow=1&autostart=1"
        );
    }

    #[test]
    fn recorder_window_reopen_url_returns_to_bootstrap_route() {
        let url = recorder_window_reopen_url(
            Url::parse("http://127.0.0.1:3100/note/abc?recorderWindow=1").unwrap(),
        );
        assert_eq!(url.scheme(), "http");
        assert_eq!(url.host_str(), Some("127.0.0.1"));
        assert_eq!(url.path(), "/");
        assert_eq!(
            url.query_pairs()
                .find(|(key, _)| key == "recorderWindow")
                .unwrap()
                .1,
            "1"
        );
        assert_eq!(
            url.query_pairs()
                .find(|(key, _)| key == "autostart")
                .unwrap()
                .1,
            "1"
        );
        assert!(url
            .query_pairs()
            .any(|(key, value)| key == "reopen" && !value.is_empty()));
    }

    #[test]
    fn recorder_window_layouts_have_fixed_dimensions() {
        assert_eq!(
            recorder_window_layout_size("expanded").unwrap(),
            (360.0, 132.0)
        );
        assert_eq!(
            recorder_window_layout_size("minimized").unwrap(),
            (320.0, 48.0)
        );
        assert!(recorder_window_layout_size("invalid").is_err());
    }

    #[test]
    fn recorder_runtime_state_tracks_active_recording() {
        let state = RecorderRuntimeState::default();
        assert!(!state.is_active());

        state.set_active(true);
        assert!(state.is_active());

        state.set_active(false);
        assert!(!state.is_active());
    }

    #[test]
    fn active_recorder_protects_main_and_recorder_window_close() {
        assert!(should_protect_window_close(MAIN_WINDOW_LABEL, true));
        assert!(should_protect_window_close(RECORDER_WINDOW_LABEL, true));
        assert!(!should_protect_window_close("settings", true));
        assert!(!should_protect_window_close(MAIN_WINDOW_LABEL, false));
    }

    #[test]
    fn active_recorder_prevents_app_exit() {
        assert!(should_prevent_app_exit(true));
        assert!(!should_prevent_app_exit(false));
    }

    #[test]
    fn recorder_window_is_in_default_capability() {
        let capabilities = include_str!("../capabilities/default.json");
        assert!(capabilities.contains("\"main\""));
        assert!(capabilities.contains("\"recorder-window\""));
        assert!(capabilities.contains("\"core:window:allow-start-dragging\""));
    }
}
