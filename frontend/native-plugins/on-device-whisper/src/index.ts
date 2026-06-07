import { registerPlugin } from "@capacitor/core";
import type { OnDeviceWhisperPlugin } from "./definitions";

/**
 * Registered Capacitor plugin handle.
 *
 * Native implementations:
 *   - iOS:     `OnDeviceWhisperPlugin.swift` (sherpa-onnx-runtime + Whisper INT8)
 *   - Android: `OnDeviceWhisperPlugin.kt`    (whisper.cpp JNI + Android NDK)
 *
 * The plugin name "OnDeviceWhisper" must match the `@CapacitorPlugin` /
 * `@objc` registration on the native side. Audio capture happens entirely
 * in Swift / Kotlin so a memory-resident `Blob` of raw audio never reaches
 * the JS layer.
 */
const OnDeviceWhisper = registerPlugin<OnDeviceWhisperPlugin>("OnDeviceWhisper", {
  // No web fallback — the bridge in `src/lib/whisper.ts` routes to the
  // browser MediaRecorder + backend `/v1/voice/dictation` path instead.
});

export * from "./definitions";
export { OnDeviceWhisper };
