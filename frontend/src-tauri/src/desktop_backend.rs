use std::{io::{Read, Write}, net::{TcpListener, TcpStream}, process::{Child, Command}, sync::Mutex, time::Duration};
use tauri::Manager;

pub struct Backend(pub Mutex<Option<Child>>);
impl Drop for Backend {
    fn drop(&mut self) {
        if let Ok(child) = self.0.get_mut() {
            if let Some(child) = child.as_mut() { let _ = child.kill(); let _ = child.wait(); }
        }
    }
}

pub fn start(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let data = app.path().app_data_dir()?.join("backend");
    std::fs::create_dir_all(&data)?;
    // Keep the same origin across launches so IndexedDB recordings and local
    // preferences remain reachable. Never connect to an unrelated listener.
    let port_file = data.join("backend-port");
    let port = if port_file.exists() {
        let port: u16 = std::fs::read_to_string(&port_file)?.trim().parse()?;
        let _reservation = TcpListener::bind(("127.0.0.1", port))?;
        port
    } else {
        let port = TcpListener::bind("127.0.0.1:0")?.local_addr()?.port();
        std::fs::write(&port_file, port.to_string())?;
        port
    };
    let backend_name = if app.config().identifier == "app.vinote.desktop.test" { "vinote-test-backend" } else { "vinote-backend" };
    let filename = if cfg!(windows) { format!("{backend_name}.exe") } else { backend_name.to_string() };
    let binary = app.path().resource_dir()?.join("backend").join(filename);
    let mut command = Command::new(binary);
    command.current_dir(&data).env("VINOTE_DESKTOP_DATA", &data).env("PORT", port.to_string())
        .env("VINOTE_DESKTOP_PARENT_PID", std::process::id().to_string());
    let log = std::fs::OpenOptions::new().create(true).append(true).open(data.join("backend.log"))?;
    command.stdout(log.try_clone()?).stderr(log);
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn()?;
    let address = format!("127.0.0.1:{port}");
    let mut ready = false;
    for _ in 0..120 {
        if child.try_wait()?.is_some() { break; }
        if let Ok(mut connection) = TcpStream::connect_timeout(&address.parse()?, Duration::from_millis(200)) {
            connection.set_read_timeout(Some(Duration::from_millis(500)))?;
            let _ = connection.write_all(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n");
            let mut response = [0; 128];
            if let Ok(length) = connection.read(&mut response) {
                if String::from_utf8_lossy(&response[..length]).contains("200 OK") { ready = true; break; }
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    if !ready { let _ = child.kill(); let _ = child.wait(); return Err(format!("VINote backend failed. See {}", data.join("backend.log").display()).into()); }
    app.manage(Backend(Mutex::new(Some(child))));
    if let Some(window) = app.get_webview_window("main") {
        window.navigate(format!("http://{address}/").parse()?)?;
    }
    Ok(())
}
