//! Only OS-selected destinations can be written. IPC never accepts a filesystem path.
use std::{
    collections::HashMap,
    io::Write,
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
};
use tauri::{State, WebviewWindow};

struct Download {
    window: String,
    target: PathBuf,
    temporary: tempfile::NamedTempFile,
}
#[derive(Default)]
pub struct Downloads(Mutex<HashMap<String, Download>>);
impl Downloads {
    pub fn discard_window(&self, label: &str) {
        if let Ok(mut sessions) = self.0.lock() {
            sessions.retain(|_, download| download.window != label);
        }
    }
}
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[tauri::command]
pub async fn choose_original_destination(
    window: WebviewWindow,
    downloads: State<'_, Downloads>,
    filename: String,
) -> Result<Option<String>, String> {
    if filename.is_empty() || filename.contains(['/', '\\']) || filename == "." || filename == ".."
    {
        return Err("Invalid filename".into());
    }
    eprintln!("[original-export] stage=picker_started");
    let selected = rfd::AsyncFileDialog::new()
        .set_parent(&window)
        .set_title("导出原文件")
        .set_file_name(&filename)
        .save_file()
        .await;
    eprintln!(
        "[original-export] stage=picker_returned outcome={}",
        if selected.is_some() {
            "selected"
        } else {
            "no_selection"
        }
    );
    let Some(selected) = selected else {
        return Ok(None);
    };
    let target = selected.path().to_path_buf();
    let temporary = tempfile::NamedTempFile::new_in(target.parent().ok_or("Invalid destination")?)
        .map_err(|_| "Cannot prepare destination")?;
    let mut sessions = downloads.0.lock().map_err(|_| "Download unavailable")?;
    if sessions.len() >= 4 {
        return Err("Too many pending downloads".into());
    }
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed).to_string();
    sessions.insert(
        id.clone(),
        Download {
            window: window.label().into(),
            target,
            temporary,
        },
    );
    Ok(Some(id))
}

#[tauri::command]
pub fn append_original_bytes(
    window: WebviewWindow,
    downloads: State<'_, Downloads>,
    id: String,
    bytes: Vec<u8>,
) -> Result<(), String> {
    if bytes.len() > 1024 * 1024 {
        return Err("Download chunk too large".into());
    }
    let mut sessions = downloads.0.lock().map_err(|_| "Download unavailable")?;
    let download = sessions
        .get_mut(&id)
        .filter(|d| d.window == window.label())
        .ok_or("Download expired")?;
    download
        .temporary
        .write_all(&bytes)
        .map_err(|_| "Cannot write original file".into())
}

#[tauri::command]
pub fn finish_original_download(
    window: WebviewWindow,
    downloads: State<'_, Downloads>,
    id: String,
) -> Result<(), String> {
    let mut sessions = downloads.0.lock().map_err(|_| "Download unavailable")?;
    if !sessions
        .get(&id)
        .is_some_and(|d| d.window == window.label())
    {
        return Err("Download expired".into());
    }
    let download = sessions.remove(&id).ok_or("Download expired")?;
    download
        .temporary
        .as_file()
        .sync_all()
        .map_err(|_| "Cannot save original file")?;
    // Same-directory atomic replacement: failed/cancelled exports never truncate an existing file.
    download
        .temporary
        .persist(download.target)
        .map_err(|_| "Cannot save original file")?;
    Ok(())
}

#[tauri::command]
pub fn cancel_original_download(
    window: WebviewWindow,
    downloads: State<'_, Downloads>,
    id: String,
) -> Result<(), String> {
    let mut sessions = downloads.0.lock().map_err(|_| "Download unavailable")?;
    if sessions
        .get(&id)
        .is_some_and(|d| d.window == window.label())
    {
        sessions.remove(&id);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Download, Downloads};
    use std::io::Write;

    #[test]
    fn closing_a_window_discards_only_its_partial_files() {
        let dir = tempfile::tempdir().unwrap();
        let downloads = Downloads::default();
        for window in ["main", "recorder-window"] {
            downloads.0.lock().unwrap().insert(
                window.into(),
                Download {
                    window: window.into(),
                    target: dir.path().join(format!("{window}.webm")),
                    temporary: tempfile::NamedTempFile::new_in(dir.path()).unwrap(),
                },
            );
        }
        downloads.discard_window("main");
        assert_eq!(downloads.0.lock().unwrap().len(), 1);
        assert!(downloads.0.lock().unwrap().contains_key("recorder-window"));
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 1);
        downloads.discard_window("recorder-window");
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 0);
    }
    #[test]
    fn cancellation_and_replacement_preserve_original_bytes() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("video.webm");
        std::fs::write(&target, b"existing").unwrap();
        {
            let mut pending = tempfile::NamedTempFile::new_in(dir.path()).unwrap();
            pending.write_all(b"partial").unwrap();
        }
        assert_eq!(std::fs::read(&target).unwrap(), b"existing");
        let mut pending = tempfile::NamedTempFile::new_in(dir.path()).unwrap();
        pending.write_all(b"exact original").unwrap();
        pending.persist(&target).unwrap();
        assert_eq!(std::fs::read(&target).unwrap(), b"exact original");
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 1);
    }
}
