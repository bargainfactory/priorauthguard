import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Capacitor 6.x config for the PriorAuthGuard mobile companion.
 *
 * - Web assets come from Next.js's static export at `out/` (see
 *   `next.config.mjs`'s `output: "export"` flag activated by
 *   `BUILD_TARGET=native`).
 * - Custom plugin `OnDeviceWhisper` (../native-plugins/on-device-whisper)
 *   provides the bridge to native Whisper backends — sherpa-onnx on iOS,
 *   whisper.cpp via JNI on Android. The TS interface lives in
 *   `src/plugins/whisper.ts`.
 * - `appendUserAgent` lets the web layer detect that it's running inside
 *   the Capacitor shell without sniffing for proprietary globals.
 */

const config: CapacitorConfig = {
  appId: "com.priorauthguard.mobile",
  appName: "PriorAuthGuard",
  webDir: "out",
  bundledWebRuntime: false,
  android: {
    allowMixedContent: false,
    captureInput: true,
    webContentsDebuggingEnabled: false,
  },
  ios: {
    contentInset: "automatic",
    backgroundColor: "#0b1118",
    scheme: "PriorAuthGuard",
  },
  server: {
    // In dev, point at the Next.js dev server; in prod we serve the static
    // bundle bundled by Capacitor.
    androidScheme: "https",
    hostname: process.env.PAG_MOBILE_HOST ?? "app",
    iosScheme: "https",
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 800,
      launchAutoHide: true,
      backgroundColor: "#0b1118",
      androidScaleType: "CENTER_CROP",
    },
  },
};

export default config;
