use serde::Serialize;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{Manager, State, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const LAUNCHER_NAMES: [(&str, &str); 6] = [
    ("llm", "gguf_llm.cmd"),
    ("tts", "tts_backend.cmd"),
    ("stt", "realtimestt.cmd"),
    ("stt_bridge", "stt_bridge.cmd"),
    ("wechat", "wechat_bridge.cmd"),
    ("core", "core_backend.cmd"),
];

#[derive(Clone, Serialize)]
struct ServiceProcessStatus {
    name: String,
    pid: u32,
    state: String,
}

#[derive(Clone, Serialize)]
struct BackendStatus {
    phase: String,
    message: String,
    log_dir: String,
    services: Vec<ServiceProcessStatus>,
}

struct ManagedProcess {
    name: String,
    child: Child,
    state: String,
}

struct SupervisorState {
    phase: String,
    message: String,
    log_dir: PathBuf,
    processes: Vec<ManagedProcess>,
}

struct ServiceSupervisor {
    inner: Mutex<SupervisorState>,
}

impl ServiceSupervisor {
    fn new(log_dir: PathBuf) -> Self {
        Self {
            inner: Mutex::new(SupervisorState {
                phase: "idle".to_string(),
                message: "等待启动后台服务".to_string(),
                log_dir,
                processes: Vec::new(),
            }),
        }
    }

    fn set_status(&self, phase: &str, message: impl Into<String>) {
        let mut state = self.inner.lock().unwrap_or_else(|err| err.into_inner());
        state.phase = phase.to_string();
        state.message = message.into();
    }

    fn start(&self) -> Result<(), String> {
        {
            let state = self.inner.lock().unwrap_or_else(|err| err.into_inner());
            if matches!(state.phase.as_str(), "preparing" | "starting" | "ready") {
                return Ok(());
            }
        }

        self.set_status("preparing", "正在准备后台服务");
        let project_root = locate_project_root()?;
        let start_script = project_root.join("start_everything.bat");
        let launcher_dir = env::temp_dir().join("neuro_core_launchers");
        fs::create_dir_all(&launcher_dir).map_err(|err| format!("无法创建启动器目录: {err}"))?;

        let log_dir = {
            let state = self.inner.lock().unwrap_or_else(|err| err.into_inner());
            state.log_dir.clone()
        };
        fs::create_dir_all(&log_dir).map_err(|err| format!("无法创建日志目录: {err}"))?;

        for (_, launcher_name) in LAUNCHER_NAMES {
            let launcher_path = launcher_dir.join(launcher_name);
            if launcher_path.exists() {
                let _ = fs::remove_file(launcher_path);
            }
        }

        let mut generator = Command::new("cmd.exe");
        generator
            .arg("/D")
            .arg("/C")
            .arg(&start_script)
            .arg("--dry-run")
            .arg("--no-ui")
            .current_dir(&project_root);
        hide_console(&mut generator);
        let output = generator
            .output()
            .map_err(|err| format!("无法运行服务启动器生成脚本: {err}"))?;
        write_launcher_output(
            &log_dir.join("launcher.log"),
            &output.stdout,
            &output.stderr,
        )?;
        if !output.status.success() {
            let message = format!(
                "服务准备失败，详情见 {}",
                log_dir.join("launcher.log").display()
            );
            self.set_status("error", &message);
            return Err(message);
        }

        self.set_status("starting", "正在启动本地 AI 服务");
        let reuse_stt = port_is_open(8011) && port_is_open(8012);
        let mut launched = Vec::new();
        for (service_name, launcher_name) in LAUNCHER_NAMES {
            if service_name == "stt" && reuse_stt {
                continue;
            }
            let launcher_path = launcher_dir.join(launcher_name);
            if !launcher_path.exists() {
                continue;
            }
            let child = match spawn_launcher(service_name, &launcher_path, &project_root, &log_dir)
            {
                Ok(child) => child,
                Err(err) => {
                    stop_processes(&mut launched);
                    return Err(err);
                }
            };
            launched.push(ManagedProcess {
                name: service_name.to_string(),
                child,
                state: "starting".to_string(),
            });
        }

        if launched.is_empty() {
            let message = "没有生成可用的后台服务启动器".to_string();
            self.set_status("error", &message);
            return Err(message);
        }

        let mut state = self.inner.lock().unwrap_or_else(|err| err.into_inner());
        state.processes = launched;
        state.message = if reuse_stt {
            "后台服务启动中，复用现有 STT 服务".to_string()
        } else {
            "后台服务启动中".to_string()
        };
        Ok(())
    }

    fn snapshot(&self) -> BackendStatus {
        let mut state = self.inner.lock().unwrap_or_else(|err| err.into_inner());
        let mut core_failed = false;
        let mut tts_failed = false;
        for process in &mut state.processes {
            match process.child.try_wait() {
                Ok(Some(status)) => {
                    process.state = format!("exited({})", status.code().unwrap_or(-1));
                    if process.name == "core" {
                        core_failed = true;
                    } else if process.name == "tts" {
                        tts_failed = true;
                    }
                }
                Ok(None) => process.state = "running".to_string(),
                Err(_) => process.state = "unknown".to_string(),
            }
        }

        let core_ready = port_is_open(8080);
        let tts_ready = port_is_open(9880);
        if core_ready && tts_ready {
            state.phase = "ready".to_string();
            state.message = "Core 和 TTS 服务已连接".to_string();
        } else if tts_failed && !tts_ready {
            state.phase = "error".to_string();
            state.message = format!(
                "TTS 启动失败，请查看 {}",
                state.log_dir.join("tts.log").display()
            );
        } else if core_failed && !core_ready {
            state.phase = "error".to_string();
            state.message = format!(
                "Core 启动失败，请查看 {}",
                state.log_dir.join("core.log").display()
            );
        } else if core_ready && !tts_ready {
            state.phase = "starting".to_string();
            state.message = "Core 已连接，TTS 服务尚未就绪".to_string();
        }

        BackendStatus {
            phase: state.phase.clone(),
            message: state.message.clone(),
            log_dir: state.log_dir.display().to_string(),
            services: state
                .processes
                .iter()
                .map(|process| ServiceProcessStatus {
                    name: process.name.clone(),
                    pid: process.child.id(),
                    state: process.state.clone(),
                })
                .collect(),
        }
    }

    fn stop(&self) {
        let mut state = self.inner.lock().unwrap_or_else(|err| err.into_inner());
        state.phase = "stopping".to_string();
        state.message = "正在关闭后台服务".to_string();
        stop_processes(&mut state.processes);
        state.processes.clear();
        state.phase = "stopped".to_string();
        state.message = "后台服务已停止".to_string();
    }
}

impl Drop for ServiceSupervisor {
    fn drop(&mut self) {
        self.stop();
    }
}

fn locate_project_root() -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    if let Ok(value) = env::var("PROJECT_AVIS_ROOT") {
        if !value.trim().is_empty() {
            candidates.push(PathBuf::from(value));
        }
    }
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));
    if let Ok(current_dir) = env::current_dir() {
        candidates.extend(current_dir.ancestors().map(Path::to_path_buf));
    }
    if let Ok(executable) = env::current_exe() {
        if let Some(parent) = executable.parent() {
            candidates.extend(parent.ancestors().map(Path::to_path_buf));
        }
    }

    for candidate in candidates {
        if candidate.join("start_everything.bat").is_file()
            && candidate.join("Core").is_dir()
            && candidate.join("live2d-desktop").is_dir()
        {
            let root = candidate
                .canonicalize()
                .map_err(|err| format!("无法解析项目目录: {err}"));
            return root.map(path_for_cmd);
        }
    }
    Err("找不到 Project Avis 项目目录；请设置 PROJECT_AVIS_ROOT".to_string())
}

fn path_for_cmd(path: PathBuf) -> PathBuf {
    #[cfg(windows)]
    {
        let display = path.to_string_lossy();
        if let Some(unc_path) = display.strip_prefix(r"\\?\UNC\") {
            return PathBuf::from(format!(r"\\{unc_path}"));
        }
        if let Some(drive_path) = display.strip_prefix(r"\\?\") {
            return PathBuf::from(drive_path);
        }
    }
    path
}

fn spawn_launcher(
    service_name: &str,
    launcher_path: &Path,
    project_root: &Path,
    log_dir: &Path,
) -> Result<Child, String> {
    let log_path = log_dir.join(format!("{service_name}.log"));
    let stdout = create_log_file(&log_path)?;
    let stderr = stdout
        .try_clone()
        .map_err(|err| format!("无法打开服务日志 {}: {err}", log_path.display()))?;

    let mut command = Command::new("cmd.exe");
    command
        .arg("/D")
        .arg("/C")
        .arg(launcher_path)
        .current_dir(project_root)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    hide_console(&mut command);
    command
        .spawn()
        .map_err(|err| format!("无法启动 {service_name}: {err}"))
}

fn create_log_file(path: &Path) -> Result<File, String> {
    OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)
        .map_err(|err| format!("无法创建日志 {}: {err}", path.display()))
}

fn write_launcher_output(path: &Path, stdout: &[u8], stderr: &[u8]) -> Result<(), String> {
    let mut file = create_log_file(path)?;
    file.write_all(stdout)
        .and_then(|_| file.write_all(stderr))
        .map_err(|err| format!("无法写入启动日志 {}: {err}", path.display()))
}

fn port_is_open(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, Duration::from_millis(120)).is_ok()
}

fn terminate_process_tree(pid: u32) -> bool {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill.exe");
        command
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_console(&mut command);
        command
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    }

    #[cfg(not(windows))]
    {
        let _ = pid;
        false
    }
}

fn stop_processes(processes: &mut [ManagedProcess]) {
    for process in processes {
        if !terminate_process_tree(process.child.id()) {
            let _ = process.child.kill();
        }
        let _ = process.child.wait();
    }
}

fn hide_console(command: &mut Command) {
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
}

#[tauri::command]
fn set_ignore_cursor(window: tauri::Window, ignore: bool) {
    let _ = window.set_ignore_cursor_events(ignore);
}

#[tauri::command]
fn backend_status(supervisor: State<'_, Arc<ServiceSupervisor>>) -> BackendStatus {
    supervisor.snapshot()
}

#[tauri::command]
fn default_live2d_model_path() -> Result<String, String> {
    let path = locate_project_root()?.join(
        "Data/Live2D Cubism/hiyori_free_zh/hiyori_free_zh/runtime/hiyori_free_t08.model3.json",
    );
    if !path.is_file() {
        return Err(format!("默认 Live2D 模型不存在: {}", path.display()));
    }
    Ok(path.to_string_lossy().into_owned())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let supervisor_slot: Arc<Mutex<Option<Arc<ServiceSupervisor>>>> = Arc::new(Mutex::new(None));
    let shutdown_slot = Arc::clone(&supervisor_slot);

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            let log_dir = app.path().app_log_dir()?;
            let supervisor = Arc::new(ServiceSupervisor::new(log_dir));
            app.manage(Arc::clone(&supervisor));
            *supervisor_slot
                .lock()
                .unwrap_or_else(|err| err.into_inner()) = Some(Arc::clone(&supervisor));
            std::thread::spawn(move || {
                if let Err(err) = supervisor.start() {
                    supervisor.set_status("error", err);
                }
            });
            Ok(())
        })
        .on_window_event(move |window, event| {
            if window.label() == "main" && matches!(event, WindowEvent::Destroyed) {
                if let Some(supervisor) = shutdown_slot
                    .lock()
                    .unwrap_or_else(|err| err.into_inner())
                    .as_ref()
                {
                    supervisor.stop();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            set_ignore_cursor,
            backend_status,
            default_live2d_model_path
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn finds_project_root_from_manifest_location() {
        let root = locate_project_root().expect("project root should be discoverable");
        assert!(root.join("start_everything.bat").is_file());
        assert!(root.join("Core").is_dir());
        assert!(!root.to_string_lossy().starts_with(r"\\?\"));
    }

    #[test]
    fn canonicalized_script_runs_through_cmd() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock should be valid")
            .as_nanos();
        let test_dir = env::temp_dir().join(format!("project-avis-cmd-{unique}"));
        fs::create_dir_all(&test_dir).expect("test directory should be created");
        let script = test_dir.join("test.cmd");
        fs::write(&script, "@echo off\r\nexit /b 0\r\n").expect("test script should be written");
        let canonical_script = script.canonicalize().expect("test script should resolve");
        let output = Command::new("cmd.exe")
            .arg("/D")
            .arg("/C")
            .arg(path_for_cmd(canonical_script))
            .current_dir(&test_dir)
            .output()
            .expect("test script should run");
        assert!(
            output.status.success(),
            "test script failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        fs::remove_file(script).expect("test script should be removed");
        fs::remove_dir(test_dir).expect("test directory should be removed");
    }

    #[test]
    fn launcher_process_tree_can_be_stopped() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock should be valid")
            .as_nanos();
        let test_dir = env::temp_dir().join(format!("project-avis-supervisor-{unique}"));
        let log_dir = test_dir.join("logs");
        fs::create_dir_all(&log_dir).expect("test log directory should be created");
        let launcher = test_dir.join("test-service.cmd");
        fs::write(&launcher, "@echo off\r\nping -n 30 127.0.0.1 >nul\r\n")
            .expect("test launcher should be written");

        let mut child = spawn_launcher("test", &launcher, &test_dir, &log_dir)
            .expect("test launcher should start");
        std::thread::sleep(Duration::from_millis(250));
        assert!(child
            .try_wait()
            .expect("process state should be readable")
            .is_none());

        if !terminate_process_tree(child.id()) {
            child.kill().expect("launcher fallback kill should succeed");
        }
        child
            .wait()
            .expect("terminated launcher should be reapable");

        let _ = fs::remove_file(launcher);
        let _ = fs::remove_file(log_dir.join("test.log"));
        let _ = fs::remove_dir(log_dir);
        let _ = fs::remove_dir(test_dir);
    }
}
