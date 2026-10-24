#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod rpc;
mod lifecycle;
mod startup;
use std::{path::PathBuf, process::{Command, Stdio}, sync::{Arc, Mutex}};
use tauri::Manager;

struct HostState(Mutex<Option<Arc<rpc::Client>>>);

fn host_client(app: &tauri::AppHandle) -> Result<Arc<rpc::Client>, String> {
    let state = app.state::<HostState>();
    let mut guard = state.0.lock().map_err(|_| "Manager lock failed")?;
    if guard.as_ref().is_some_and(|host| !host.is_alive()) { guard.take(); }
    if guard.is_none() { *guard = Some(spawn_host(app)?); }
    Ok(guard.as_ref().unwrap().clone())
}

fn spawn_host(app: &tauri::AppHandle) -> Result<Arc<rpc::Client>, String> {
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let dev_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let host_path = if cfg!(debug_assertions) { dev_root.join("desktop_host/host.py") } else { resources.join("desktop_host/host.py") };
    let catalog = if cfg!(debug_assertions) { dev_root.join("src-tauri/resources/catalog.json") } else { resources.join("catalog.json") };
    let bundled_python = if cfg!(debug_assertions) { dev_root.join("src-tauri/resources/python/python.exe") } else { resources.join("python/python.exe") };
    let python = if bundled_python.is_file() { bundled_python } else if cfg!(debug_assertions) {
        std::env::var_os("AFTERGLOW_DEV_PYTHON").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }))
    } else { return Err("Bundled Python 3.12 is missing. Rebuild with the prepared Windows runtime.".into()) };
    let app_data = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let install_dir = executable.parent().ok_or("Cannot resolve installation directory")?;
    let mut command = Command::new(python);
    command.arg("-u").arg(host_path).arg("--install-dir").arg(install_dir).arg("--app-data-dir").arg(app_data).arg("--catalog").arg(catalog)
        .env("PYTHONIOENCODING", "utf-8").env("PYTHONUTF8", "1")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    // Keep development data stable across different Rust target folders.
    if cfg!(debug_assertions) && std::env::var_os("AFTERGLOW_DATA_DIR").is_none() {
        command.arg("--data-dir").arg(dev_root.join(".desktop-data"));
    }
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let child = command.spawn().map_err(|e| format!("Cannot start desktop manager: {e}"))?;
    rpc::Client::connect(child)
}

#[tauri::command]
async fn host_request(app: tauri::AppHandle, method: String, args: serde_json::Value) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        host_client(&app)?.request(method, args)
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn apply_desktop_update(app: tauri::AppHandle, args: serde_json::Value) -> Result<(), String> {
    #[cfg(not(windows))] { let _ = (app, args); return Err("Desktop updates currently require Windows.".into()); }
    #[cfg(windows)] {
        let handle = app.clone();
        tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
            use std::os::windows::process::CommandExt;
            let host = host_client(&handle)?;
            let staged = host.request("download_desktop_update".into(), args.clone())?;
            host.request("prepare_desktop_update".into(), args.clone())?;
            let path = staged["path"].as_str().ok_or("Update path missing")?;
            let sha256 = staged["sha256"].as_str().ok_or("Update checksum missing")?;
            let executable = std::env::current_exe().map_err(|e| e.to_string())?;
            let directory = executable.parent().ok_or("Installation directory missing")?;
            let powershell = PathBuf::from(std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into()))
                .join("System32/WindowsPowerShell/v1.0/powershell.exe");
            Command::new(powershell)
                .args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", include_str!("../../desktop_host/apply_update.ps1")])
                .env("AFTERGLOW_UPDATE_INSTALLER", path).env("AFTERGLOW_UPDATE_SHA256", sha256)
                .env("AFTERGLOW_UPDATE_DIRECTORY", directory).env("AFTERGLOW_UPDATE_PARENT", std::process::id().to_string())
                .env("AFTERGLOW_UPDATE_LOCALE", args["locale"].as_str().unwrap_or("zh-CN"))
                .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
                .creation_flags(0x08000000).spawn().map_err(|e| e.to_string())?;
            Ok(())
        }).await.map_err(|e| e.to_string())??;
        app.exit(0);
        Ok(())
    }
}

fn main() {
    let app = tauri::Builder::default().plugin(tauri_plugin_dialog::init()).plugin(tauri_plugin_opener::init())
        .manage(HostState(Mutex::new(None)))
        .setup(|app| lifecycle::init(app))
        .on_window_event(|window, event| if let tauri::WindowEvent::CloseRequested { api, .. } = event { lifecycle::close_requested(window, api); })
        .invoke_handler(tauri::generate_handler![host_request, apply_desktop_update, lifecycle::desktop_preferences,
            lifecycle::set_desktop_preferences, lifecycle::hide_to_tray, lifecycle::exit_application])
        .build(tauri::generate_context!()).expect("Unable to build Afterglow desktop");
    app.run(|app, event| if let tauri::RunEvent::Exit = event {
        let host = app.state::<HostState>().0.lock().ok().and_then(|mut guard| guard.take());
        if let Some(host) = host { host.shutdown(); }
    });
}
