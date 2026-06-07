// JNI bridge between WhisperBridge.kt and whisper.cpp.
//
// Minimal, blocking, single-call implementation. Audio is read from disk
// (the Kotlin side captures a WAV) so we avoid pinning large byte arrays
// across the JNI boundary.

#include <jni.h>
#include <string>
#include <vector>
#include <cstdio>
#include <cstdint>
#include <stdexcept>

#include "whisper.h"

namespace {

std::vector<float> load_wav_16k_mono(const std::string& path) {
    FILE* fp = std::fopen(path.c_str(), "rb");
    if (!fp) throw std::runtime_error("could not open " + path);

    char header[44];
    if (std::fread(header, 1, 44, fp) != 44) {
        std::fclose(fp);
        throw std::runtime_error("short WAV header");
    }
    // Trust the Kotlin writer's contract: PCM mono 16-bit 16kHz.
    std::vector<int16_t> raw;
    raw.reserve(16000 * 30);
    int16_t buf[1024];
    while (true) {
        size_t n = std::fread(buf, sizeof(int16_t), 1024, fp);
        if (n == 0) break;
        raw.insert(raw.end(), buf, buf + n);
    }
    std::fclose(fp);

    std::vector<float> out(raw.size());
    for (size_t i = 0; i < raw.size(); ++i) {
        out[i] = static_cast<float>(raw[i]) / 32768.0f;
    }
    return out;
}

std::string j2c(JNIEnv* env, jstring s) {
    const char* raw = env->GetStringUTFChars(s, nullptr);
    std::string out(raw);
    env->ReleaseStringUTFChars(s, raw);
    return out;
}

void throw_runtime(JNIEnv* env, const std::string& msg) {
    jclass ex = env->FindClass("java/lang/RuntimeException");
    env->ThrowNew(ex, msg.c_str());
}

} // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_com_paguard_whisper_WhisperBridge_transcribe(
    JNIEnv* env,
    jclass /* clazz */,
    jstring jWavPath,
    jstring jModelPath,
    jstring jLanguage) {

    try {
        const std::string wav_path = j2c(env, jWavPath);
        const std::string model_path = j2c(env, jModelPath);
        const std::string language = j2c(env, jLanguage);

        struct whisper_context_params cparams = whisper_context_default_params();
        struct whisper_context* ctx = whisper_init_from_file_with_params(
            model_path.c_str(), cparams);
        if (!ctx) throw std::runtime_error("whisper_init_from_file failed");

        const std::vector<float> pcm = load_wav_16k_mono(wav_path);

        whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
        params.language = language.c_str();
        params.print_realtime = false;
        params.print_progress = false;
        params.print_special = false;
        params.print_timestamps = false;
        params.no_context = true;
        params.single_segment = false;

        if (whisper_full(ctx, params, pcm.data(), pcm.size()) != 0) {
            whisper_free(ctx);
            throw std::runtime_error("whisper_full failed");
        }

        std::string out;
        const int n_segments = whisper_full_n_segments(ctx);
        for (int i = 0; i < n_segments; ++i) {
            const char* text = whisper_full_get_segment_text(ctx, i);
            if (text) {
                out += text;
                out += ' ';
            }
        }
        whisper_free(ctx);
        // Trim trailing space.
        if (!out.empty() && out.back() == ' ') out.pop_back();
        return env->NewStringUTF(out.c_str());
    } catch (const std::exception& e) {
        throw_runtime(env, e.what());
        return nullptr;
    }
}
