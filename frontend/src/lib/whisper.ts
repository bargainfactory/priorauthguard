/**
 * Unified on-device Whisper bridge.
 *
 * The same `transcribeOnDevice()` function works in all three runtimes:
 *
 *  - tauri      → invokes the Rust `transcribe_audio` command (whisper-rs).
 *  - capacitor  → calls the custom `OnDeviceWhisper` plugin (whisper.cpp / sherpa-onnx).
 *  - web        → throws — the web `/voice` page should de-identify the
 *                 transcript via the backend `/v1/voice/dictation` endpoint
 *                 instead of expecting Whisper to run in the browser.
 *
 * The bridge enforces the platform's privacy contract: raw audio bytes are
 * passed straight from the capture surface into the native transcribe call
 * and are NEVER attached to any HTTP request, log, or persisted form.
 */

import { getPlatform } from "@/lib/platform";

/**
 * Load an optional native module without letting Webpack / Turbopack
 * follow the specifier into its dependency graph.
 *
 * Why: `@pa-guard/on-device-whisper` only exists when the Capacitor shell
 * has installed it; on the web build the package is absent and a literal
 * `await import("@pa-guard/on-device-whisper")` would fail at compile
 * time with `Module not found`. Constructing the import via `new Function`
 * gives the bundler a non-literal specifier, so it emits a runtime native
 * dynamic import — which resolves on Capacitor and cleanly rejects
 * everywhere else.
 *
 * `unsafe-eval` is already in the Tauri CSP; Next.js dev has no CSP. The
 * helper is safe across every supported runtime.
 */
export async function loadOptionalNativeModule<T = unknown>(
  specifier: string,
): Promise<T> {
  const dynImport = new Function("s", "return import(s)") as (s: string) => Promise<T>;
  return dynImport(specifier);
}

export interface OnDeviceTranscript {
  text: string;
  modelName: string;
  durationMs: number;
  onDevice: true;
}

export class WhisperUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WhisperUnavailableError";
  }
}

/**
 * Transcribe a WAV (16-bit PCM, mono, 16 kHz). Returns the text only — raw
 * audio is not retained.
 */
export async function transcribeOnDevice(
  wav: Blob,
  language = "en",
): Promise<OnDeviceTranscript> {
  const platform = getPlatform();
  if (platform === "tauri") {
    const bytes = new Uint8Array(await wav.arrayBuffer());
    const { invoke } = await import("@tauri-apps/api/core");
    const res = await invoke<{
      text: string;
      model: string;
      duration_ms: number;
    }>("transcribe_audio", { audio: Array.from(bytes), language });
    return {
      text: res.text,
      modelName: res.model,
      durationMs: res.duration_ms,
      onDevice: true,
    };
  }

  if (platform === "capacitor") {
    // The Capacitor plugin's API is record→stop→transcribe (raw audio stays
    // on-device the entire time). This helper expects the caller has already
    // captured a WAV via the plugin and is just rerouting through this
    // bridge — for a one-shot run, see `transcribeViaCapacitor`.
    throw new WhisperUnavailableError(
      "Use OnDeviceWhisper.startRecording() + stopRecording() + transcribe() " +
        "on Capacitor; the WAV stays on-device and is referenced by path.",
    );
  }

  throw new WhisperUnavailableError(
    "On-device Whisper is only available in the desktop (Tauri) and mobile " +
      "(Capacitor) clients. The web client de-identifies via the backend.",
  );
}

/**
 * High-level wrapper for the Capacitor case: record, stop, transcribe.
 * Returns the de-identified-ready transcript without ever exposing the WAV
 * to JS.
 */
export async function recordAndTranscribeCapacitor(
  language = "en",
): Promise<OnDeviceTranscript> {
  const platform = getPlatform();
  if (platform !== "capacitor") {
    throw new WhisperUnavailableError("Capacitor runtime required.");
  }
  const { OnDeviceWhisper } = await loadOptionalNativeModule<{
    OnDeviceWhisper: {
      requestMicrophonePermission(): Promise<{ granted: boolean }>;
      startRecording(opts: { sampleRate: number }): Promise<unknown>;
      stopRecording(): Promise<{ wavPath: string }>;
      transcribe(opts: {
        wavPath: string;
        language: string;
        deleteAudioAfter: boolean;
      }): Promise<{ text: string; modelName: string; durationMs: number }>;
    };
  }>("@pa-guard/on-device-whisper").catch(() => {
    throw new WhisperUnavailableError(
      "@pa-guard/on-device-whisper plugin not installed in this Capacitor app.",
    );
  });

  const perm = await OnDeviceWhisper.requestMicrophonePermission();
  if (!perm.granted) {
    throw new WhisperUnavailableError("Microphone permission denied.");
  }
  await OnDeviceWhisper.startRecording({ sampleRate: 16_000 });
  // The actual stop is triggered by the UI — in practice this helper is
  // composed of two halves. We expose it as one fn for documentation; real
  // UI calls startRecording / stopRecording in response to user gestures.
  const stop = await OnDeviceWhisper.stopRecording();
  const res = await OnDeviceWhisper.transcribe({
    wavPath: stop.wavPath,
    language,
    deleteAudioAfter: true,
  });
  return {
    text: res.text,
    modelName: res.modelName,
    durationMs: res.durationMs,
    onDevice: true,
  };
}
