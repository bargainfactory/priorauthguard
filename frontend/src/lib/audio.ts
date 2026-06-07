/**
 * Browser audio capture utilities.
 *
 * Records via the Web Audio API + MediaRecorder, then converts the captured
 * buffer to 16-bit PCM mono 16 kHz wrapped in a WAV — the exact shape the
 * Tauri Whisper command expects. (Capacitor records natively, so this only
 * runs in the browser / Tauri path.)
 */

export interface RecordingHandle {
  stop: () => Promise<Blob>;
}

/**
 * Begin recording from the system microphone. Returns a handle; call
 * `stop()` to finalize and receive a WAV `Blob` (mono 16 kHz 16-bit PCM).
 */
export async function startBrowserRecording(): Promise<RecordingHandle> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices) {
    throw new Error("Microphone capture is not available in this environment.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

  // Use an AudioContext so we can resample to 16k mono. MediaRecorder by itself
  // emits opus/webm — fine to ship to a cloud STT but not what whisper.cpp eats.
  const audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
  const source = audioContext.createMediaStreamSource(stream);
  const processor = audioContext.createScriptProcessor(4096, 1, 1);

  const chunks: Float32Array[] = [];
  processor.onaudioprocess = (event) => {
    // Float32 mono samples in the AudioContext's native sample rate.
    const input = event.inputBuffer.getChannelData(0);
    // Copy — the underlying buffer is recycled by the AudioContext.
    chunks.push(new Float32Array(input));
  };
  source.connect(processor);
  processor.connect(audioContext.destination);

  const stop = async (): Promise<Blob> => {
    processor.disconnect();
    source.disconnect();
    stream.getTracks().forEach((t) => t.stop());

    const inputRate = audioContext.sampleRate;
    const inputSamples = concatFloat32(chunks);
    const resampled = resampleLinear(inputSamples, inputRate, 16_000);
    const wav = encodeWav16kMono(resampled);
    await audioContext.close();
    return new Blob([wav], { type: "audio/wav" });
  };
  return { stop };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function concatFloat32(parts: Float32Array[]): Float32Array {
  const len = parts.reduce((a, b) => a + b.length, 0);
  const out = new Float32Array(len);
  let i = 0;
  for (const p of parts) {
    out.set(p, i);
    i += p.length;
  }
  return out;
}

function resampleLinear(
  input: Float32Array,
  inputRate: number,
  outputRate: number,
): Float32Array {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const src = i * ratio;
    const idx = Math.floor(src);
    const frac = src - idx;
    const a = input[idx] ?? 0;
    const b = input[idx + 1] ?? a;
    out[i] = a + (b - a) * frac;
  }
  return out;
}

function encodeWav16kMono(samples: Float32Array): ArrayBuffer {
  const sampleRate = 16_000;
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const dataLength = samples.length * 2;

  const buffer = new ArrayBuffer(44 + dataLength);
  const view = new DataView(buffer);
  let p = 0;
  const writeStr = (s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(p++, s.charCodeAt(i));
  };

  writeStr("RIFF");
  view.setUint32(p, 36 + dataLength, true); p += 4;
  writeStr("WAVE");
  writeStr("fmt ");
  view.setUint32(p, 16, true); p += 4;
  view.setUint16(p, 1, true); p += 2;
  view.setUint16(p, numChannels, true); p += 2;
  view.setUint32(p, sampleRate, true); p += 4;
  view.setUint32(p, byteRate, true); p += 4;
  view.setUint16(p, blockAlign, true); p += 2;
  view.setUint16(p, bitsPerSample, true); p += 2;
  writeStr("data");
  view.setUint32(p, dataLength, true); p += 4;

  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(p, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    p += 2;
  }
  return buffer;
}
