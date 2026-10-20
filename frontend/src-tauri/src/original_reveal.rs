//! Reveal a validated existing local file; never open its content or modify it.
use std::path::{Component, Path, PathBuf};
use tauri::AppHandle;
use tauri_plugin_opener::OpenerExt;

fn local_file(path: &str) -> Result<PathBuf, &'static str> {
    let file = Path::new(path);
    if path.is_empty()
        || path.chars().any(char::is_control)
        || path.starts_with("\\\\")
        || path.starts_with("//")
        || path.contains("://")
        || !file.is_absolute()
        || file.components().any(|c| matches!(c, Component::ParentDir))
    {
        return Err("invalid_original_path");
    }
    #[cfg(windows)]
    {
        use std::path::Prefix;
        if !matches!(file.components().next(), Some(Component::Prefix(p)) if matches!(p.kind(), Prefix::Disk(_)))
            || path.chars().skip(2).any(|c| c == ':')
        {
            return Err("invalid_original_path");
        }
    }
    // Do not follow file symlinks or parent junctions into a different device,
    // a share or a directory. Keep the exact original path selected in Explorer.
    for entry in file.ancestors() {
        let metadata = std::fs::symlink_metadata(entry).map_err(|_| "original_file_unavailable")?;
        if metadata.file_type().is_symlink() {
            return Err("invalid_original_path");
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if metadata.file_attributes() & 0x400 != 0 {
                return Err("invalid_original_path");
            }
        }
    }
    if !std::fs::symlink_metadata(file)
        .map_err(|_| "original_file_unavailable")?
        .is_file()
    {
        return Err("original_file_unavailable");
    }
    Ok(file.to_path_buf())
}

#[tauri::command]
pub fn reveal_original_file(app: AppHandle, path: String) -> Result<(), String> {
    let file = local_file(&path).map_err(str::to_owned)?;
    // Verified against the installed tauri-plugin-opener 2.5.4 Rust API.
    // This reveals/selects the item; open_path would launch the media instead.
    app.opener()
        .reveal_item_in_dir(file)
        .map_err(|_| "unable_to_reveal_original".into())
}

#[cfg(test)]
mod tests {
    use super::local_file;

    #[test]
    fn refuses_urls_relative_paths_unc_and_device_namespaces() {
        for path in [
            "", "recording.webm", "../recording.webm", "file:///C:/recording.webm",
            "https://example.invalid/video.webm", "\\\\server\\share\\video.webm",
            "//server/share/video.webm", "\\\\?\\UNC\\server\\share\\video.webm",
            "\\\\.\\PhysicalDrive0", "C:relative.webm", "C:\\video.webm\0",
        ] {
            assert!(local_file(path).is_err(), "unexpectedly accepted {path:?}");
        }
    }

    #[test]
    fn reveals_only_existing_files_without_changing_their_bytes() {
        let root = tempfile::tempdir().unwrap();
        let file = root.path().join("会议录屏 original.webm");
        std::fs::write(&file, b"retained original").unwrap();
        assert_eq!(local_file(file.to_str().unwrap()).unwrap(), file);
        assert!(local_file(root.path().to_str().unwrap()).is_err());
        assert!(local_file(root.path().join("missing.webm").to_str().unwrap()).is_err());
        assert_eq!(std::fs::read(&file).unwrap(), b"retained original");
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 1);
    }

    #[cfg(windows)]
    #[test]
    fn refuses_windows_drive_relative_ads_and_parent_traversal() {
        for path in ["\\video.webm", "C:\\video.webm:stream", "C:\\dir\\..\\video.webm", "\\\\?\\C:\\video.webm"] {
            assert!(local_file(path).is_err());
        }
    }

    #[cfg(unix)]
    #[test]
    fn refuses_symlinks_to_files_or_parent_directories() {
        use std::os::unix::fs::symlink;
        let root = tempfile::tempdir().unwrap();
        let file = root.path().join("original.webm");
        std::fs::write(&file, b"original").unwrap();
        let link = root.path().join("linked.webm");
        symlink(&file, &link).unwrap();
        assert!(local_file(link.to_str().unwrap()).is_err());
        let dir = root.path().join("linked-dir");
        symlink(root.path(), &dir).unwrap();
        assert!(local_file(dir.join("original.webm").to_str().unwrap()).is_err());
    }
}
