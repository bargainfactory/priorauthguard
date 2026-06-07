package com.paguard.whisper

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Capacitor plugin: on-device Whisper for clinical dictation on Android.
 *
 * Audio is captured via `AudioRecord` at 16 kHz mono int16 — the exact shape
 * whisper.cpp expects. The plugin writes a WAV to the app's private storage
 * and never exposes the raw audio bytes to the JS layer.
 *
 * The native whisper.cpp library is built by the CMake target under
 * `src/main/cpp/`. JNI bindings live in `WhisperBridge` (Kotlin) ↔
 * `whisper-jni.cpp` (C++).
 */
@CapacitorPlugin(
    name = "OnDeviceWhisper",
    permissions = [
        Permission(
            alias = "microphone",
            strings = [Manifest.permission.RECORD_AUDIO],
        )
    ],
)
class OnDeviceWhisperPlugin : Plugin() {

    private val executor = Executors.newSingleThreadExecutor()
    private val isRecording = AtomicBoolean(false)
    private var currentWav: File? = null
    private var recordingStartedAt: Long = 0
    private var audioRecord: AudioRecord? = null

    private val sampleRate = 16_000
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    private val bufferSize by lazy {
        AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat) * 4
    }

    // -----------------------------------------------------------------------
    // Permissions
    // -----------------------------------------------------------------------

    @PluginMethod
    fun requestMicrophonePermission(call: PluginCall) {
        if (
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED
        ) {
            val result = JSObject().apply { put("granted", true) }
            call.resolve(result)
            return
        }
        requestPermissionForAlias("microphone", call, "permissionCallback")
    }

    @PermissionCallback
    private fun permissionCallback(call: PluginCall) {
        val granted = getPermissionState("microphone").name == "GRANTED"
        val result = JSObject().apply { put("granted", granted) }
        call.resolve(result)
    }

    // -----------------------------------------------------------------------
    // Model status
    // -----------------------------------------------------------------------

    @PluginMethod
    fun modelStatus(call: PluginCall) {
        val modelFile = modelFile()
        val result = JSObject().apply {
            put("modelInstalled", modelFile.exists())
            put("modelName", "ggml-small.en-q8_0.bin")
            put("modelPath", modelFile.absolutePath)
        }
        call.resolve(result)
    }

    // -----------------------------------------------------------------------
    // Recording — 16-bit PCM mono 16 kHz into a sandbox WAV.
    // -----------------------------------------------------------------------

    @PluginMethod
    fun startRecording(call: PluginCall) {
        if (isRecording.get()) {
            call.reject("Already recording")
            return
        }
        if (
            ActivityCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED
        ) {
            call.reject("RECORD_AUDIO permission not granted")
            return
        }

        val id = UUID.randomUUID().toString()
        val outFile = File(dictationDir(), "dictation-$id.wav")
        currentWav = outFile

        val record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            sampleRate,
            channelConfig,
            audioFormat,
            bufferSize,
        )
        audioRecord = record
        record.startRecording()
        isRecording.set(true)
        recordingStartedAt = System.currentTimeMillis()

        executor.submit {
            val out = FileOutputStream(outFile)
            // Reserve 44 bytes for the WAV header — written on stop().
            out.write(ByteArray(44))
            val buf = ByteArray(bufferSize)
            while (isRecording.get()) {
                val n = record.read(buf, 0, buf.size)
                if (n > 0) out.write(buf, 0, n)
            }
            val dataLength = (outFile.length() - 44).toInt()
            out.close()
            writeWavHeader(outFile, dataLength)
        }

        val result = JSObject().apply { put("recordingId", id) }
        call.resolve(result)
    }

    @PluginMethod
    fun stopRecording(call: PluginCall) {
        if (!isRecording.get()) {
            call.reject("Not recording")
            return
        }
        isRecording.set(false)
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null

        val durationSeconds =
            (System.currentTimeMillis() - recordingStartedAt) / 1000.0
        val path = currentWav?.absolutePath ?: ""
        val result = JSObject().apply {
            put("wavPath", path)
            put("durationSeconds", durationSeconds)
        }
        call.resolve(result)
    }

    // -----------------------------------------------------------------------
    // Transcription via JNI bridge.
    // -----------------------------------------------------------------------

    @PluginMethod
    fun transcribe(call: PluginCall) {
        val wavPath = call.getString("wavPath") ?: run {
            call.reject("wavPath is required"); return
        }
        val language = call.getString("language", "en") ?: "en"
        val deleteAfter = call.getBoolean("deleteAudioAfter", true) ?: true
        executor.submit {
            try {
                val started = System.currentTimeMillis()
                val text = WhisperBridge.transcribe(
                    wavPath = wavPath,
                    modelPath = modelFile().absolutePath,
                    language = language,
                )
                if (deleteAfter) File(wavPath).delete()
                val elapsed = System.currentTimeMillis() - started
                val result = JSObject().apply {
                    put("text", text)
                    put("durationMs", elapsed)
                    put("modelName", "ggml-small.en-q8_0.bin")
                    put("onDevice", true)
                }
                call.resolve(result)
            } catch (e: Throwable) {
                call.reject("transcribe failed: ${e.message}", e)
            }
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private fun dictationDir(): File =
        File(context.filesDir, "dictation").apply { mkdirs() }

    private fun modelFile(): File =
        File(context.filesDir, "whisper/ggml-small.en-q8_0.bin")

    private fun writeWavHeader(file: File, dataLength: Int) {
        // Minimal canonical PCM WAV header for 16k mono 16-bit.
        val byteRate = sampleRate * 1 * 16 / 8
        val totalLength = dataLength + 36
        val raf = java.io.RandomAccessFile(file, "rw")
        raf.seek(0)
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray())
        header.putInt(totalLength)
        header.put("WAVE".toByteArray())
        header.put("fmt ".toByteArray())
        header.putInt(16)                       // Subchunk1Size
        header.putShort(1)                      // PCM
        header.putShort(1)                      // mono
        header.putInt(sampleRate)
        header.putInt(byteRate)
        header.putShort(2)                      // block align
        header.putShort(16)                     // bits per sample
        header.put("data".toByteArray())
        header.putInt(dataLength)
        raf.write(header.array())
        raf.close()
    }
}
