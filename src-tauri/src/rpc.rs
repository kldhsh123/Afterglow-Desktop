use serde_json::{json, Value};
#[path = "process_tree.rs"]
mod process_tree;
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin},
    sync::{atomic::{AtomicBool, AtomicU64, Ordering}, mpsc, Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

type Reply = Result<Value, String>;
type Pending = Arc<Mutex<HashMap<u64, mpsc::Sender<Reply>>>>;

pub struct Client {
    child: Mutex<Child>,
    tree: process_tree::ProcessTree,
    input: Mutex<Option<ChildStdin>>,
    pending: Pending,
    next_id: AtomicU64,
    alive: Arc<AtomicBool>,
}

fn fail_pending(pending: &Pending, message: &str) {
    if let Ok(mut requests) = pending.lock() {
        for (_, sender) in requests.drain() {
            let _ = sender.send(Err(message.to_owned()));
        }
    }
}

impl Client {
    pub fn connect(mut child: Child) -> Result<Arc<Self>, String> {
        let tree = match process_tree::ProcessTree::attach(&child) {
            Ok(tree) => tree,
            Err(error) => { let _ = child.kill(); let _ = child.wait(); return Err(error); }
        };
        let input = child.stdin.take().ok_or("Missing manager input")?;
        let output = child.stdout.take().ok_or("Missing manager output")?;
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let alive = Arc::new(AtomicBool::new(true));
        let client = Arc::new(Self {
            child: Mutex::new(child), tree, input: Mutex::new(Some(input)),
            pending: pending.clone(), next_id: AtomicU64::new(1), alive: alive.clone(),
        });
        // Only this thread reads stdout. Responses may arrive in any order.
        thread::spawn(move || {
            let mut output = BufReader::new(output);
            let mut line = String::new();
            loop {
                line.clear();
                match output.read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {}
                }
                let response: Value = match serde_json::from_str(&line) {
                    Ok(response) => response,
                    Err(_) => break,
                };
                let Some(id) = response.get("id").and_then(Value::as_u64) else { break };
                let sender = pending.lock().ok().and_then(|mut requests| requests.remove(&id));
                if let Some(sender) = sender {
                    let result = if response["ok"] == true {
                        Ok(response["result"].clone())
                    } else {
                        Err(response["error"].as_str().unwrap_or("Manager request failed").to_owned())
                    };
                    let _ = sender.send(result);
                }
            }
            alive.store(false, Ordering::Release);
            fail_pending(&pending, "Desktop manager closed its connection; retry to reconnect.");
        });
        Ok(client)
    }

    pub fn is_alive(&self) -> bool {
        self.alive.load(Ordering::Acquire)
            && self.child.lock().map(|mut child| matches!(child.try_wait(), Ok(None))).unwrap_or(false)
    }

    pub fn request(&self, method: String, args: Value) -> Reply {
        if !self.is_alive() { return Err("Desktop manager stopped; retry to reconnect.".into()); }
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver) = mpsc::channel();
        {
            let mut requests = self.pending.lock().map_err(|_| "Manager request lock failed")?;
            if requests.len() >= 64 { return Err("Desktop manager has too many pending requests".into()); }
            requests.insert(id, sender);
        }
        let written = (|| -> Result<(), String> {
            let mut guard = self.input.lock().map_err(|_| "Manager input lock failed")?;
            let input = guard.as_mut().ok_or("Desktop manager is closing")?;
            writeln!(input, "{}", json!({ "id": id, "method": method, "args": args })).map_err(|e| e.to_string())?;
            input.flush().map_err(|e| e.to_string())
        })();
        if let Err(error) = written {
            if let Ok(mut requests) = self.pending.lock() { requests.remove(&id); }
            return Err(error);
        }
        match receiver.recv_timeout(Duration::from_secs(600)) {
            Ok(result) => result,
            Err(_) => {
                if let Ok(mut requests) = self.pending.lock() { requests.remove(&id); }
                Err("Desktop request timed out. Check its status before trying again.".into())
            }
        }
    }

    pub fn shutdown(&self) {
        self.alive.store(false, Ordering::Release);
        fail_pending(&self.pending, "Desktop manager is closing");
        // EOF asks Python to close the core and its bundled channel workers.
        if let Ok(mut input) = self.input.lock() { input.take(); }
        if let Ok(mut child) = self.child.lock() {
            let deadline = Instant::now() + Duration::from_secs(15);
            loop {
                if !matches!(child.try_wait(), Ok(None)) { break; }
                if Instant::now() >= deadline { break; }
                thread::sleep(Duration::from_millis(25));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
        self.tree.terminate();
    }
}

impl Drop for Client {
    fn drop(&mut self) { self.shutdown(); }
}
