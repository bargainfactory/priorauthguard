//! Native Whisper integration via `whisper-rs` (whisper.cpp under the hood).
//!
//! ## Model resolution
//! The model file lives under the Tauri app data dir at:
//!
//!     <app-data-dir>/models/<model-name>
//!
//! Default model name: `ggml-small.en-q8_0.bin` (≈170 MB after q8
//! quantization). The user (or installer) drops the GGUF/GGML file there
//! once; subsequent runs auto-load it.
//!
//! Download with:
//!
//!     bash scripts/download-whisper-model.sh small.en-q8_0
//!
//! ## Audio shape contract
//! The frontend hands us a WAV blob containing **16-bit PCM, mono, 16 kHz**.
//! `hound` is used to decode it into the `f32` slice that whisper expects.

use std::path::PathBuf;
use std::sync::Mutex;

use thiserror::Error;
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

/// Default model — quantized small.en is a good clinician-dictation default:
/// runs on CPU at ~1.5x real-time on Apple Silicon and modern x86.
pub const DEFAULT_MODEL: &str = "ggml-small.en-q8_0.bin";

#[derive(Error, Debug)]
pub enum WhisperError {
    #[error("model file not found at {0:?}; place a GGML/GGUF whisper.cpp model there")]
    ModelMissing(PathBuf),
    #[error("whisper-rs error: {0}")]
    Whisper(String),
    #[error("audio decode failed: {0}")]
    AudioDecode(#[from] hound::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("unexpected audio shape: expected 16-bit PCM mono 16 kHz, got {0}")]
    AudioShape(String),
}

impl From<whisper_rs::WhisperError> for WhisperError {
    fn from(value: whisper_rs::WhisperError) -> Self {
        WhisperError::Whisper(value.to_string())
    }
}

pub fn resolve_model_path(app: &tauri::AppHandle) -> Result<PathBuf, WhisperError> {
    use tauri::Manager;
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| WhisperError::Whisper(e.to_string()))?;
    Ok(dir.join("models").join(DEFAULT_MODEL))
}

/// Long-lived Whisper engine. `Mutex<WhisperContext>` is sufficient because
/// inference is GIL-free under whisper.cpp and we serialize at the tokio
/// runtime level above.
pub struct WhisperEngine {
    ctx: Mutex<WhisperContext>,
    model_name: String,
}

impl WhisperEngine {
    pub fn new(model_path: PathBuf) -> Result<Self, WhisperError> {
        if !model_path.exists() {
            return Err(WhisperError::ModelMissing(model_path));
        }
        let model_name = model_path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or(DEFAULT_MODEL)
            .to_string();
        let params = WhisperContextParameters::default();
        let ctx = WhisperContext::new_with_params(
            model_path.to_string_lossy().as_ref(),
            params,
        )?;
        Ok(Self {
            ctx: Mutex::new(ctx),
            model_name,
        })
    }

    pub fn model_name(&self) -> &str {
        &self.model_name
    }

    /// Decode a WAV blob and run Whisper. Returns the concatenated transcript.
    pub fn transcribe_wav(&self, wav_bytes: &[u8], language: &str) -> Result<String, WhisperError> {
        let samples = decode_wav_to_pcm_f32(wav_bytes)?;

        let mut ctx = self.ctx.lock().expect("whisper context mutex poisoned");
        let mut state = ctx.create_state()?;

        let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
        params.set_language(Some(language));
        params.set_print_special(false);
        params.set_print_progress(false);
        params.set_print_realtime(false);
        params.set_print_timestamps(false);
        // Disable VAD-style features that hurt short clinical phrases.
        params.set_no_context(true);
        params.set_single_segment(false);
        // Use as many cores as the host offers — clinician dictation is bursty,
        // we want each call to finish fast.
        params.set_n_threads(num_cpus().min(8) as i32);

        state.full(params, &samples)?;

        let mut out = String::new();
        let n_segments = state.full_n_segments()?;
        for i in 0..n_segments {
            let segment = state.full_get_segment_text(i)?;
            out.push_str(&segment);
            out.push(' ');
        }
        Ok(out.trim().to_string())
    }
}

/// Decode a 16-bit PCM mono 16 kHz WAV blob into the f32 samples Whisper expects.
fn decode_wav_to_pcm_f32(wav_bytes: &[u8]) -> Result<Vec<f32>, WhisperError> {
    let cursor = std::io::Cursor::new(wav_bytes);
    let mut reader = hound::WavReader::new(cursor)?;
    let spec = reader.spec();
    if spec.sample_rate != 16_000 || spec.channels != 1 {
        return Err(WhisperError::AudioShape(format!(
            "rate={}, channels={}, bits={}",
            spec.sample_rate, spec.channels, spec.bits_per_sample
        )));
    }
    let samples: Vec<f32> = match (spec.sample_format, spec.bits_per_sample) {
        (hound::SampleFormat::Int, 16) => reader
            .samples::<i16>()
            .map(|s| s.map(|v| v as f32 / i16::MAX as f32))
            .collect::<Result<_, _>>()?,
        (hound::SampleFormat::Float, 32) => {
            reader.samples::<f32>().collect::<Result<_, _>>()?
        }
        (fmt, bits) => {
            return Err(WhisperError::AudioShape(format!(
                "unsupported sample format {:?} @ {} bits",
                fmt, bits
            )));
        }
    };
    Ok(samples)
}

fn num_cpus() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
}
