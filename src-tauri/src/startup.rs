//! One opt-in Windows startup entry per installation. No startup setting is
//! changed when the app merely starts or reads its preferences.
use std::path::Path;

pub fn installation_id(path: &Path) -> String {
    // NSIS owns this installation GUID and uses the same Run value on removal.
    // Handle both Windows INI encodings; only accept a GUID, never arbitrary
    // names read from a user-editable file. Portable copies use a path identity.
    if let Ok(bytes) = std::fs::read(path.join("installation.ini")) {
        let ini = if bytes.starts_with(&[0xff, 0xfe]) {
            String::from_utf16_lossy(&bytes[2..].chunks_exact(2).map(|part| u16::from_le_bytes([part[0], part[1]])).collect::<Vec<_>>())
        } else { String::from_utf8_lossy(&bytes).into_owned() };
        if let Some(id) = registered_id(&ini) { return format!("AfterglowDesktop-{id}"); }
    }
    let path = path.to_string_lossy().replace('\\', "/").to_lowercase();
    let hash = path.trim_end_matches('/').as_bytes().iter()
        .fold(0xcbf29ce484222325u64, |value, byte| (value ^ u64::from(*byte)).wrapping_mul(0x100000001b3));
    format!("AfterglowDesktop-{hash:016x}")
}

fn registered_id(ini: &str) -> Option<&str> {
    let mut installation = false;
    for line in ini.lines().map(str::trim) {
        if line.starts_with('[') { installation = line.eq_ignore_ascii_case("[installation]"); continue; }
        if !installation { continue; }
        if let Some((key, value)) = line.split_once('=') {
            let value = value.trim();
            if key.trim().eq_ignore_ascii_case("id") && value.len() == 38 && value.starts_with('{') && value.ends_with('}') {
                let guid = &value[1..37];
                if guid.bytes().enumerate().all(|(index, byte)| {
                    if [8, 13, 18, 23].contains(&index) { byte == b'-' } else { byte.is_ascii_hexdigit() }
                }) { return Some(value); }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn windows_path_identity_is_stable() {
        assert_eq!(installation_id(Path::new("C:\\Afterglow\\")), installation_id(Path::new("c:/afterglow")));
        assert_ne!(installation_id(Path::new("C:/Afterglow")), installation_id(Path::new("D:/Afterglow")));
    }
    #[test] fn guid_is_scoped_to_installation_section() {
        let id = "{12ABCDEF-1234-5678-9ABC-1234567890AB}";
        assert_eq!(registered_id(&format!("[installation]\r\nid={id}\r\n")), Some(id));
        assert_eq!(registered_id(&format!("[other]\r\nid={id}\r\n")), None);
        assert_eq!(registered_id("[installation]\nid={not-a-guid}"), None);
    }
}

#[cfg(windows)]
mod registry {
    use std::{os::windows::ffi::OsStrExt, path::Path};
    use windows_sys::Win32::System::Registry::*;
    fn wide(value: &str) -> Vec<u16> { std::ffi::OsStr::new(value).encode_wide().chain(Some(0)).collect() }
    fn command(executable: &Path) -> String { format!("\"{}\" --autostart", executable.display()) }
    struct Key(HKEY);
    impl Drop for Key { fn drop(&mut self) { unsafe { RegCloseKey(self.0); } } }
    const RUN: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";

    pub fn enabled(executable: &Path, name: &str) -> bool {
        unsafe {
            let mut raw = std::ptr::null_mut();
            if RegOpenKeyExW(HKEY_CURRENT_USER, wide(RUN).as_ptr(), 0, KEY_QUERY_VALUE, &mut raw) != 0 { return false; }
            let key = Key(raw);
            let mut kind = 0;
            let mut size = 0;
            if RegQueryValueExW(key.0, wide(name).as_ptr(), std::ptr::null(), &mut kind, std::ptr::null_mut(), &mut size) != 0
                || kind != REG_SZ || size > 65536 { return false; }
            let mut data = vec![0u16; (size as usize + 1) / 2];
            if RegQueryValueExW(key.0, wide(name).as_ptr(), std::ptr::null(), &mut kind, data.as_mut_ptr().cast(), &mut size) != 0 { return false; }
            let end = data.iter().position(|item| *item == 0).unwrap_or(data.len());
            String::from_utf16_lossy(&data[..end]).eq_ignore_ascii_case(&command(executable))
        }
    }

    pub fn set_enabled(executable: &Path, name: &str, enabled: bool) -> Result<(), String> {
        unsafe {
            let mut raw = std::ptr::null_mut();
            let result = RegCreateKeyExW(HKEY_CURRENT_USER, wide(RUN).as_ptr(), 0, std::ptr::null(),
                REG_OPTION_NON_VOLATILE, KEY_SET_VALUE, std::ptr::null(), &mut raw, std::ptr::null_mut());
            if result != 0 { return Err(format!("Windows startup setting: {result}")); }
            let key = Key(raw);
            let result = if enabled {
                let value = wide(&command(executable));
                RegSetValueExW(key.0, wide(name).as_ptr(), 0, REG_SZ, value.as_ptr().cast(), (value.len() * 2) as u32)
            } else { RegDeleteValueW(key.0, wide(name).as_ptr()) };
            if result == 0 || (!enabled && result == 2) { Ok(()) }
            else { Err(format!("Windows startup setting: {result}")) }
        }
    }
}
#[cfg(windows)] pub use registry::{enabled, set_enabled};
#[cfg(not(windows))] pub fn enabled(_: &Path, _: &str) -> bool { false }
#[cfg(not(windows))] pub fn set_enabled(_: &Path, _: &str, _: bool) -> Result<(), String> { Err("Windows only".into()) }
