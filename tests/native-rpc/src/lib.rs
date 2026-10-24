#[path = "../../../src-tauri/src/rpc.rs"]
pub mod rpc;

#[cfg(test)]
mod tests {
    use super::rpc::Client;
    use serde_json::json;
    use std::{process::{Command, Stdio}, sync::{Arc, atomic::{AtomicBool, Ordering}}, thread};

    fn host(script: &str) -> Arc<Client> {
        let python = std::env::var("AFTERGLOW_TEST_PYTHON").unwrap_or_else(|_| {
            if cfg!(windows) { "python".into() } else { "python3".into() }
        });
        let child = Command::new(python).args(["-u", "-c", script])
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
            .spawn().expect("Python is required for transport integration checks");
        Client::connect(child).unwrap()
    }

    #[test]
    fn responses_are_matched_by_id_and_health_does_not_wait_for_generation() {
        let client = host(r#"
import json, sys, threading, time
started = threading.Event()
lock = threading.Lock()
def respond(request):
    if request['method'] == 'slow':
        started.set()
        time.sleep(1.5)
    else:
        started.wait(2)
    with lock:
        print(json.dumps({'id': request['id'], 'ok': True, 'result': request['method']}), flush=True)
for line in sys.stdin:
    threading.Thread(target=respond, args=(json.loads(line),)).start()
"#);
        let finished = Arc::new(AtomicBool::new(false));
        let slow = {
            let client = client.clone();
            let finished = finished.clone();
            thread::spawn(move || {
                let result = client.request("slow".into(), json!({}));
                finished.store(true, Ordering::Release);
                result
            })
        };
        assert_eq!(client.request("health".into(), json!({})).unwrap(), json!("health"));
        assert!(!finished.load(Ordering::Acquire), "Health waited for the long request");
        assert_eq!(slow.join().unwrap().unwrap(), json!("slow"));
        client.shutdown();
        assert!(!client.is_alive());
    }

    #[test]
    fn manager_errors_are_returned_to_the_matching_request() {
        let client = host(r#"
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({'id': request['id'], 'ok': False, 'error': 'test failure'}), flush=True)
"#);
        assert_eq!(client.request("fail".into(), json!({})).unwrap_err(), "test failure");
        client.shutdown();
    }

    #[test]
    fn closed_or_invalid_stdout_fails_pending_requests_without_hanging() {
        for script in ["import sys; sys.stdin.readline()", "import sys; sys.stdin.readline(); print('invalid response', flush=True)"] {
            let client = host(script);
            assert!(client.request("health".into(), json!({})).is_err());
            client.shutdown();
        }
    }

    #[cfg(windows)]
    #[test]
    fn shutdown_reaps_descendants_after_the_manager_exits() {
        use windows_sys::Win32::{Foundation::CloseHandle, System::Threading::{OpenProcess, WaitForSingleObject}};
        let client = host(r#"
import json, subprocess, sys
grandchild = None
for line in sys.stdin:
    request = json.loads(line)
    grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(json.dumps({'id': request['id'], 'ok': True, 'result': grandchild.pid}), flush=True)
"#);
        let pid = client.request("spawn".into(), json!({})).unwrap().as_u64().unwrap() as u32;
        unsafe {
            // Retain a handle so the exit check does not depend on PID reuse.
            let process = OpenProcess(0x00100000, 0, pid);
            assert!(!process.is_null(), "Cannot observe fixture descendant");
            assert_eq!(WaitForSingleObject(process, 0), 0x102);
            client.shutdown();
            let wait = WaitForSingleObject(process, 5000);
            CloseHandle(process);
            assert_eq!(wait, 0, "Desktop shutdown left a descendant running");
        }
    }
}
