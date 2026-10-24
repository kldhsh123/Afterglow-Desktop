//! Desktop-wide preferences and tray lifetime; independent of model settings.
use serde_json::{json, Value};
use std::{path::PathBuf, sync::Mutex};
use tauri::{Emitter, Manager, menu::{Menu, MenuItem}, tray::{TrayIconBuilder, TrayIconEvent, MouseButton, MouseButtonState}};
use crate::startup;

pub struct DesktopLifecycle {
    preferences: Mutex<Value>,
    path: PathBuf,
    executable: PathBuf,
    startup_id: String,
    open: MenuItem<tauri::Wry>,
    exit: MenuItem<tauri::Wry>,
    tray_ready: bool,
}

fn text(locale: &str, key: &str) -> String {
    let dictionary = if locale == "zh-CN" { include_str!("../../locales/zh-CN.json") } else { include_str!("../../locales/en-US.json") };
    serde_json::from_str::<Value>(dictionary).ok().and_then(|value| value[key].as_str().map(str::to_owned)).unwrap_or_else(|| key.into())
}
fn open_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus();
    }
}

pub fn init(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let executable = std::env::current_exe()?;
    let directory = executable.parent().ok_or("Installation directory missing")?;
    let startup_id = startup::installation_id(directory);
    let root = if let Some(override_path) = std::env::var_os("AFTERGLOW_DATA_DIR") { PathBuf::from(override_path) }
        else if cfg!(debug_assertions) { PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join(".desktop-data") }
        else if directory.join(".afterglow-portable").is_file() { directory.join("AfterglowData") }
        else { app.path().app_local_data_dir()?.join("desktop").join(&startup_id) };
    let path = root.join("desktop-preferences.json");
    let mut preferences = std::fs::read(&path).ok().and_then(|value| serde_json::from_slice::<Value>(&value).ok()).filter(Value::is_object)
        .unwrap_or_else(|| json!({"closeAction": "ask", "locale": "en-US"}));
    #[cfg(windows)] if !path.is_file() {
        if unsafe { windows_sys::Win32::Globalization::GetUserDefaultUILanguage() } & 0x3ff == 4 { preferences["locale"] = json!("zh-CN"); }
    }
    let locale = preferences["locale"].as_str().unwrap_or("en-US");
    let open = MenuItem::with_id(app, "tray-open", text(locale, "desktop.tray_open"), true, None::<&str>)?;
    let exit = MenuItem::with_id(app, "tray-exit", text(locale, "desktop.tray_exit"), true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &exit])?;
    let mut builder = TrayIconBuilder::with_id("afterglow-tray").menu(&menu).tooltip("Afterglow").show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() { "tray-open" => open_window(app), "tray-exit" => app.exit(0), _ => {} })
        .on_tray_icon_event(|tray, event| {
            if matches!(event, TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } | TrayIconEvent::DoubleClick { button: MouseButton::Left, .. }) { open_window(tray.app_handle()); }
        });
    if let Some(icon) = app.default_window_icon() { builder = builder.icon(icon.clone()); }
    let tray_ready = builder.build(app).is_ok();
    app.manage(DesktopLifecycle { preferences: Mutex::new(preferences), path, executable, startup_id, open, exit, tray_ready });
    if tray_ready && std::env::args().any(|argument| argument == "--autostart") {
        if let Some(window) = app.get_webview_window("main") { window.hide()?; }
    }
    Ok(())
}

fn snapshot(state: &DesktopLifecycle) -> Result<Value, String> {
    let saved = state.preferences.lock().map_err(|_| "Desktop preferences unavailable")?;
    let action = saved["closeAction"].as_str().filter(|value| ["ask", "tray", "exit"].contains(value)).unwrap_or("ask");
    Ok(json!({"closeAction": if action == "tray" && !state.tray_ready { "ask" } else { action },
        "autostart": startup::enabled(&state.executable, &state.startup_id), "trayAvailable": state.tray_ready}))
}

#[tauri::command]
pub fn desktop_preferences(app: tauri::AppHandle) -> Result<Value, String> { snapshot(&app.state::<DesktopLifecycle>()) }

#[tauri::command]
pub fn set_desktop_preferences(app: tauri::AppHandle, args: Value) -> Result<Value, String> {
    let state = app.state::<DesktopLifecycle>();
    let mut saved = state.preferences.lock().map_err(|_| "Desktop preferences unavailable")?;
    let mut updated = saved.clone();
    if let Some(action) = args.get("closeAction") {
        let action = action.as_str().filter(|value| ["ask", "tray", "exit"].contains(value)).ok_or("Invalid close action")?;
        if action == "tray" && !state.tray_ready { return Err("Tray icon is unavailable".into()); }
        updated["closeAction"] = json!(action);
    }
    if let Some(locale) = args["locale"].as_str().filter(|value| ["zh-CN", "en-US"].contains(value)) { updated["locale"] = json!(locale); }
    let old_autostart = startup::enabled(&state.executable, &state.startup_id);
    if let Some(autostart) = args.get("autostart") {
        startup::set_enabled(&state.executable, &state.startup_id, autostart.as_bool().ok_or("Invalid startup preference")?)?;
    }
    let persisted = (|| -> Result<(), std::io::Error> {
        std::fs::create_dir_all(state.path.parent().unwrap())?;
        let temporary = state.path.with_extension("json.tmp");
        std::fs::write(&temporary, serde_json::to_vec_pretty(&updated)?)?;
        std::fs::rename(temporary, &state.path)
    })();
    if let Err(error) = persisted {
        if args.get("autostart").is_some() { let _ = startup::set_enabled(&state.executable, &state.startup_id, old_autostart); }
        return Err(error.to_string());
    }
    let locale = updated["locale"].as_str().unwrap_or("en-US");
    let _ = state.open.set_text(text(locale, "desktop.tray_open"));
    let _ = state.exit.set_text(text(locale, "desktop.tray_exit"));
    *saved = updated;
    drop(saved);
    snapshot(&state)
}

#[tauri::command]
pub fn hide_to_tray(app: tauri::AppHandle) -> Result<(), String> {
    if !app.state::<DesktopLifecycle>().tray_ready { return Err("Tray icon is unavailable".into()); }
    app.get_webview_window("main").ok_or("Main window unavailable")?.hide().map_err(|error| error.to_string())
}
#[tauri::command]
pub fn exit_application(app: tauri::AppHandle) { app.exit(0); }

pub fn close_requested(window: &tauri::Window, api: &tauri::CloseRequestApi) {
    api.prevent_close();
    let _ = window.emit("desktop-close-requested", ());
}
