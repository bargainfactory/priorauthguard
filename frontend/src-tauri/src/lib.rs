//! PriorAuthGuard desktop — Tauri entry point.
//!
//! Exposes the [`transcribe_audio`] command so the web UI's voice console
//! can hand a Blob of 16-bit PCM mono 16 kHz audio to the native Whisper
//! engine without the audio ever leaving the user's machine.
//!
//! ## Why this matters
//! Clinician dictation must stay on-device under both HIPAA Safe Harbor and
//! the platform's privacy contract. This module hosts the Rust + whisper.cpp
//! path that fulfills that promise.

mod whisper;

use std::sync::Arc;
use tauri::{Manager, State};
use tokio::sync::Mutex;

use crate::whisper::{WhisperEngine, WhisperError};

/// Shared, lazily-initialized Whisper engine. Loading the model is expensive
/// (hundreds of MB → seconds of GGML setup) so we want one engine per process.
pub struct AppState {
    engine: Mutex<Option<Arc<WhisperEngine>>>,
}

#[derive(serde::Serialize)]
pub struct TranscribeResponse {
    pub text: String,
    pub on_device: bool,
    pub model: String,
    pub language: String,
    pub duration_ms: u128,
}

#[tauri::command]
async fn whisper_status(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let model_path = whisper::resolve_model_path(&app).map_err(|e| e.to_string())?;
    Ok(serde_json::json!({
        "available": model_path.exists(),
        "model_path": model_path.to_string_lossy(),
    }))
}

/// Transcribe a chunk of audio.
///
/// `audio` is expected to be **16-bit PCM, mono, 16 kHz** wrapped in a WAV
/// container. The frontend Web Audio capture path resamples to that shape
/// before invoking this command — see `frontend/src/lib/audio.ts`.
#[tauri::command]
async fn transcribe_audio(
    audio: Vec<u8>,
    language: Option<String>,
    state: State<'_, AppState>,
    app: tauri::AppHandle,
) -> Result<TranscribeResponse, String> {
    let started = std::time::Instant::now();
    let lang = language.unwrap_or_else(|| "en".to_string());

    // Lazily build the engine on first call.
    let engine = {
        let mut guard = state.engine.lock().await;
        if guard.is_none() {
            let model_path = whisper::resolve_model_path(&app).map_err(|e| e.to_string())?;
            let built = WhisperEngine::new(model_path).map_err(|e| e.to_string())?;
            *guard = Some(Arc::new(built));
        }
        guard.as_ref().unwrap().clone()
    };

    let text = engine
        .transcribe_wav(&audio, &lang)
        .map_err(|e: WhisperError| e.to_string())?;

    Ok(TranscribeResponse {
        text,
        on_device: true,
        model: engine.model_name().to_string(),
        language: lang,
        duration_ms: started.elapsed().as_millis(),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            engine: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![whisper_status, transcribe_audio])
        .setup(|app| {
            tracing::info!("PriorAuthGuard desktop starting");
            // Ensure the app data dir exists so the user can drop a model in.
            if let Ok(dir) = app.path().app_data_dir() {
                let _ = std::fs::create_dir_all(dir.join("models"));
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PriorAuthGuard desktop");
}
