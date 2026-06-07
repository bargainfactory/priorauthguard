# Phase 4 — Deliverables, Verification, Privacy Impact

## What ships

| Area | Path |
|---|---|
| **Tauri 2.x desktop shell** wrapping the Next.js frontend | [`frontend/src-tauri/`](../frontend/src-tauri/) |
| Tauri Rust + whisper-rs integration (`transcribe_audio` command) | [`frontend/src-tauri/src/whisper.rs`](../frontend/src-tauri/src/whisper.rs) |
| Tauri app entry, AppState, lifecycle | [`frontend/src-tauri/src/lib.rs`](../frontend/src-tauri/src/lib.rs) |
| Whisper.cpp model fetch helper | [`frontend/scripts/download-whisper-model.sh`](../frontend/scripts/download-whisper-model.sh) |
| **Capacitor 6.x mobile config** | [`frontend/capacitor.config.ts`](../frontend/capacitor.config.ts) |
| **Custom Capacitor plugin** `OnDeviceWhisper` (TS interface) | [`frontend/native-plugins/on-device-whisper/src/`](../frontend/native-plugins/on-device-whisper/src/) |
| iOS native (Swift + sherpa-onnx hook + AVAudioEngine capture) | [`frontend/native-plugins/on-device-whisper/ios/`](../frontend/native-plugins/on-device-whisper/ios/) |
| Android native (Kotlin + JNI + whisper.cpp CMake) | [`frontend/native-plugins/on-device-whisper/android/`](../frontend/native-plugins/on-device-whisper/android/) |
| Runtime platform detection | [`frontend/src/lib/platform.ts`](../frontend/src/lib/platform.ts) |
| Unified Whisper bridge | [`frontend/src/lib/whisper.ts`](../frontend/src/lib/whisper.ts) |
| Browser audio capture (WAV 16k mono 16-bit encoder) | [`frontend/src/lib/audio.ts`](../frontend/src/lib/audio.ts) |
| Native-aware Voice page | [`frontend/src/app/voice/page.tsx`](../frontend/src/app/voice/page.tsx) |
| Next.js config for static export under native builds | [`frontend/next.config.mjs`](../frontend/next.config.mjs) |
| Updated `package.json` with `tauri:*`, `cap:*`, `whisper:download` scripts | [`frontend/package.json`](../frontend/package.json) |

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Next.js 15 frontend (one codebase, three targets)                       │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  /voice page                                                     │    │
│  │  ─────────                                                       │    │
│  │  • getPlatform() → "tauri" | "capacitor" | "web"                 │    │
│  │  • Native paths: capture entirely on-device,                     │    │
│  │     never produce a Blob the JS layer can leak.                  │    │
│  │  • Web path: shows a banner, asks the user to paste transcript.  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                          │                       │                       │
│                          │                       │                       │
│       ┌──────────────────┘                       └──────────────────┐    │
│       ▼                                                             ▼    │
│  ┌─────────────────────────────┐         ┌─────────────────────────────┐ │
│  │  Tauri 2.x (Rust)           │         │  Capacitor 6.x (Swift/Kotlin)│ │
│  │  invoke("transcribe_audio") │         │  OnDeviceWhisper.transcribe()│ │
│  │     │                       │         │     │                       │ │
│  │     ▼                       │         │     ▼                       │ │
│  │  whisper-rs (whisper.cpp)   │         │  iOS:   sherpa-onnx INT8    │ │
│  │  CPU/CUDA/Metal feature flag│         │  Andr:  whisper.cpp JNI     │ │
│  │  model under app data dir   │         │  model bundled in app       │ │
│  └─────────────────────────────┘         └─────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                   │                              │
                   ▼                              ▼
       Backend API (FastAPI):  POST /v1/voice/dictation
       (Safe Harbor de-identification of the de-identified-ready transcript text)
```

The native runtimes return **text**, not audio — raw PCM never crosses the
JS / native boundary in either direction.

## Verification checklist

### Desktop (Tauri)

```bash
# Prereqs: Rust toolchain, C++ build tools, Tauri CLI prerequisites
# https://v2.tauri.app/start/prerequisites/

cd frontend
pnpm install
pnpm tauri:icon ./brand-icon.png      # generate icons in src-tauri/icons/
pnpm whisper:download                 # fetch small.en-q8_0 model
pnpm tauri:dev                        # launches desktop shell + Next dev
```

Manual checks:
1. App window opens with the Next.js UI rendered.
2. Open the `/voice` page; platform badge reads `tauri`.
3. Click Record → speak briefly → Stop. Confirm:
   - The "Native transcript" pane fills with the Whisper text.
   - A `whisper Xs` badge appears (transcribe latency).
   - The "De-identified transcript" pane shows the Safe-Harbor-clean version.
   - Network panel shows **no** request carrying audio bytes — only the
     `POST /v1/voice/dictation` request carrying the *text* transcript.
4. Open `/zk`. Verify the proof verifier UI works inside the desktop shell.

### Mobile (Capacitor)

```bash
cd frontend
pnpm install
pnpm cap:sync                         # builds static export + syncs platforms
# First-time only:
npx cap add ios
npx cap add android
pnpm cap:open:ios                     # opens Xcode
pnpm cap:open:android                 # opens Android Studio
```

Inside each native project:

1. Add the local plugin: `npm install ../native-plugins/on-device-whisper`
2. iOS: drop the Whisper ONNX bundle into `App/App/Resources/whisper-small-en-int8.onnx`.
3. Android: drop the GGML model into `app/src/main/assets/whisper/ggml-small.en-q8_0.bin` and copy at install.
4. Build & run on a device. The `/voice` page's platform badge reads `capacitor`.
5. Record → Stop → confirm the WAV is written under the app sandbox and
   deleted after transcription (set `deleteAudioAfter: false` to inspect once).
6. Inspect HTTP traffic — confirm no audio leaves the device.

### Web (regression check)

Unchanged from Phase 3 — the `/voice` page now shows a `web` badge and
displays the banner instructing the user to paste the transcript.

## Privacy / compliance impact

- ✅ **Tauri**: audio captured in the browser context becomes a `Blob`, which
  is converted to a `Uint8Array` and handed directly to the Rust IPC call.
  The Rust side never persists the WAV to disk by default; the result text
  is the only thing crossing back. No network egress involves audio.
- ✅ **Capacitor (iOS / Android)**: audio is captured by native code into the
  app's sandboxed file system, transcribed locally, and the WAV is **deleted
  by default** after transcription (`deleteAudioAfter: true`). The plugin
  has zero `INTERNET` / outbound permissions of its own; only the transcript
  text reaches the JS layer.
- ✅ **Web**: no path attempts to upload raw audio. The web page explicitly
  instructs the user to paste the transcript so the contract of
  "raw audio never leaves the device" holds even on the unsupported runtime.
- ✅ The Tauri CSP locks `connect-src` to `self`, `ipc:`, and the loopback
  backend — no third-party host can be contacted by the desktop shell.
- ✅ The Capacitor Android plugin manifest declares only `RECORD_AUDIO`; no
  `INTERNET` permission is requested by the plugin itself.

## Phase 4 → Phase 5 entry plan

1. **Streaming voice** — promote the request/response Whisper call to a true
   `/v1/voice/stream` WebSocket with the same on-device path producing
   incremental partial-results (Whisper VAD chunks at 250–500 ms cadence).
2. **Real payer integrations** behind the existing `SubmissionAdapter`
   Protocol (Availity, CoverMyMeds, Surescripts, OHIP API, NHS Spine).
3. **Learned `MetaImproverAgent`** — replace the Phase 2 heuristic engine with
   a small LLM proposal generator under the same approval-gated interface.
4. **Postgres-backed PA registry** to replace the Phase 1 in-memory store.
5. **Tests + deploy** — Helm charts, container images, CI workflow that
   builds Tauri (Linux + Windows + macOS) and Android (Capacitor) binaries.
