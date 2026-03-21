#[tauri::command]
fn set_ignore_cursor(window: tauri::Window, ignore: bool) {
    let _ = window.set_ignore_cursor_events(ignore);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![set_ignore_cursor])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
