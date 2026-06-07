import AVFoundation
import Capacitor
import Foundation

/// Capacitor plugin: on-device Whisper transcription for clinical dictation.
///
/// Raw audio is recorded to a sandbox-local file via `AVAudioEngine` and is
/// **never** copied into the JS layer. After transcription the WAV is deleted
/// unless the caller explicitly opts out.
///
/// Backend: sherpa-onnx with a Whisper INT8 ONNX bundle shipped in the app.
/// Swap to whisper.cpp via a thin Objective-C++ wrapper if you prefer.
@objc(OnDeviceWhisperPlugin)
public class OnDeviceWhisperPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "OnDeviceWhisperPlugin"
    public let jsName = "OnDeviceWhisper"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "requestMicrophonePermission", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "modelStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startRecording", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopRecording", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "transcribe", returnType: CAPPluginReturnPromise),
    ]

    private let engine = AVAudioEngine()
    private var recordingURL: URL?
    private var recordingFile: AVAudioFile?
    private var recordingStart: Date?

    // -----------------------------------------------------------------------
    // Permissions
    // -----------------------------------------------------------------------

    @objc func requestMicrophonePermission(_ call: CAPPluginCall) {
        AVAudioSession.sharedInstance().requestRecordPermission { granted in
            call.resolve(["granted": granted])
        }
    }

    // -----------------------------------------------------------------------
    // Model status
    // -----------------------------------------------------------------------

    @objc func modelStatus(_ call: CAPPluginCall) {
        let path = bundledModelPath()
        let installed = FileManager.default.fileExists(atPath: path.path)
        call.resolve([
            "modelInstalled": installed,
            "modelName": "whisper-small-en-int8",
            "modelPath": path.path,
        ])
    }

    // -----------------------------------------------------------------------
    // Recording — writes to a sandbox-local 16-bit PCM 16kHz mono WAV.
    // -----------------------------------------------------------------------

    @objc func startRecording(_ call: CAPPluginCall) {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers])
            try session.setActive(true)

            let input = engine.inputNode
            let bus = 0
            let inputFormat = input.outputFormat(forBus: bus)
            guard
                let targetFormat = AVAudioFormat(
                    commonFormat: .pcmFormatInt16,
                    sampleRate: 16_000,
                    channels: 1,
                    interleaved: true)
            else {
                call.reject("Could not create target format")
                return
            }

            let id = UUID().uuidString
            let url = sandboxDir().appendingPathComponent("dictation-\(id).wav")
            recordingURL = url
            recordingFile = try AVAudioFile(forWriting: url, settings: targetFormat.settings)
            recordingStart = Date()

            // Resample from the device's native rate (often 44.1k or 48k) into
            // 16k mono on the way out so whisper.cpp / sherpa-onnx don't have to.
            let converter = AVAudioConverter(from: inputFormat, to: targetFormat)
            input.installTap(onBus: bus, bufferSize: 4096, format: inputFormat) { buffer, _ in
                guard
                    let converter = converter,
                    let outBuffer = AVAudioPCMBuffer(
                        pcmFormat: targetFormat,
                        frameCapacity: AVAudioFrameCount(targetFormat.sampleRate * 0.4))
                else { return }
                var error: NSError?
                converter.convert(to: outBuffer, error: &error) { _, status in
                    status.pointee = .haveData
                    return buffer
                }
                if error == nil { try? self.recordingFile?.write(from: outBuffer) }
            }

            engine.prepare()
            try engine.start()
            call.resolve(["recordingId": id])
        } catch {
            call.reject("startRecording failed: \(error.localizedDescription)")
        }
    }

    @objc func stopRecording(_ call: CAPPluginCall) {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        let duration = recordingStart.map { Date().timeIntervalSince($0) } ?? 0
        guard let url = recordingURL else {
            call.reject("No active recording")
            return
        }
        recordingFile = nil
        recordingStart = nil
        recordingURL = nil
        call.resolve([
            "wavPath": url.path,
            "durationSeconds": duration,
        ])
    }

    // -----------------------------------------------------------------------
    // Transcription
    // -----------------------------------------------------------------------

    @objc func transcribe(_ call: CAPPluginCall) {
        guard let wavPath = call.getString("wavPath") else {
            call.reject("wavPath is required")
            return
        }
        let language = call.getString("language") ?? "en"
        let deleteAfter = call.getBool("deleteAudioAfter") ?? true
        let start = Date()

        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let text = try WhisperRunner.shared.transcribe(
                    wavPath: wavPath,
                    language: language,
                    modelURL: self.bundledModelPath()
                )
                if deleteAfter { try? FileManager.default.removeItem(atPath: wavPath) }
                let elapsed = Int(Date().timeIntervalSince(start) * 1000)
                call.resolve([
                    "text": text,
                    "durationMs": elapsed,
                    "modelName": "whisper-small-en-int8",
                    "onDevice": true,
                ])
            } catch {
                call.reject("transcribe failed: \(error.localizedDescription)")
            }
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private func sandboxDir() -> URL {
        let fm = FileManager.default
        let url = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("dictation", isDirectory: true)
        try? fm.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func bundledModelPath() -> URL {
        // Models ship inside the app bundle under Resources/whisper/. They are
        // updated via a normal app store update; never downloaded at runtime.
        if let url = Bundle.main.url(forResource: "whisper-small-en-int8", withExtension: "onnx") {
            return url
        }
        return Bundle.main.bundleURL.appendingPathComponent("whisper-small-en-int8.onnx")
    }
}

/// Thin Swift facade around sherpa-onnx-runtime. The real implementation
/// holds a single `SherpaOnnxOfflineRecognizer` instance per process; we keep
/// the interface narrow so swapping in whisper.cpp later is a one-file change.
final class WhisperRunner {
    static let shared = WhisperRunner()
    private init() {}

    func transcribe(wavPath: String, language: String, modelURL: URL) throws -> String {
        // ┌─────────────────────────────────────────────────────────────────┐
        // │  Replace this stub with sherpa-onnx-runtime / whisper.cpp call. │
        // │  Keeping it pure-Swift keeps the plugin compileable without the │
        // │  ONNX dependency wired up — the bridge contract stays stable.   │
        // └─────────────────────────────────────────────────────────────────┘
        return "[on-device-whisper iOS stub] " +
            "wav=\(wavPath) language=\(language) model=\(modelURL.lastPathComponent)"
    }
}
