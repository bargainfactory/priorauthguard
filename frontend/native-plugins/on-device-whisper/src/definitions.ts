/**
 * `OnDeviceWhisper` — Capacitor plugin definitions.
 *
 * Pattern:
 *   1. UI requests microphone permission via `requestMicrophonePermission()`.
 *   2. UI starts a recording with `startRecording()`. The plugin samples to a
 *      WAV file in the app sandbox (raw audio NEVER leaves the device).
 *   3. UI calls `stopRecording()` and immediately invokes `transcribe()`
 *      against the path returned by stop, OR streams chunks via
 *      `transcribeChunk()` for low-latency dictation.
 *   4. The bridge in `frontend/src/lib/whisper.ts` returns the de-identified
 *      text directly to the React tree — the PHI raw audio file is deleted
 *      by the plugin once the call returns.
 */

export interface MicPermissionResult {
  granted: boolean;
}

export interface StartRecordingOptions {
  /** Suggested sample rate (the plugin will resample to 16k internally). */
  sampleRate?: number;
  /** Optional max duration (ms) for safety on inbound dictation. */
  maxDurationMs?: number;
}

export interface StartRecordingResult {
  recordingId: string;
}

export interface StopRecordingResult {
  /** Sandbox-local path to the captured 16k mono 16-bit WAV. */
  wavPath: string;
  /** Duration in seconds, for OutcomeLogger. */
  durationSeconds: number;
}

export interface TranscribeOptions {
  /** Path returned by `stopRecording`. */
  wavPath: string;
  /** Language code; defaults to "en". */
  language?: string;
  /**
   * If true, the plugin deletes the WAV after transcription completes.
   * Default: true — never leave raw audio on disk.
   */
  deleteAudioAfter?: boolean;
}

export interface TranscribeResult {
  text: string;
  durationMs: number;
  modelName: string;
  /** Always true — this plugin runs strictly on-device. */
  onDevice: true;
}

export interface ModelStatusResult {
  modelInstalled: boolean;
  modelName: string;
  /**
   * Approximate path the model is loaded from (read-only string, useful
   * for diagnostics and for the PrivacyFHEPanel to display).
   */
  modelPath: string;
}

export interface OnDeviceWhisperPlugin {
  requestMicrophonePermission(): Promise<MicPermissionResult>;
  modelStatus(): Promise<ModelStatusResult>;
  startRecording(options?: StartRecordingOptions): Promise<StartRecordingResult>;
  stopRecording(): Promise<StopRecordingResult>;
  transcribe(options: TranscribeOptions): Promise<TranscribeResult>;
}
