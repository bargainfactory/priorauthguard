package com.paguard.whisper

/**
 * Kotlin ↔ C++ JNI surface.
 *
 * The native side is built from `src/main/cpp/whisper-jni.cpp` (a thin
 * wrapper around whisper.cpp's high-level `whisper_full` API). The library
 * is loaded once per process.
 */
object WhisperBridge {

    init {
        System.loadLibrary("pa_guard_whisper")
    }

    /**
     * Run whisper.cpp synchronously. Returns the concatenated transcript.
     * @throws RuntimeException on model load / decode failure.
     */
    @JvmStatic
    external fun transcribe(
        wavPath: String,
        modelPath: String,
        language: String,
    ): String
}
