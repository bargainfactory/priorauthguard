/**
 * Runtime platform detection.
 *
 * Returns one of:
 *  - "tauri"     — running inside the Tauri 2 shell (desktop)
 *  - "capacitor" — running inside the Capacitor 6 shell (iOS / Android)
 *  - "web"       — running in a regular browser
 *
 * Detection runs lazily and only once per page (cached).
 */

export type Platform = "web" | "tauri" | "capacitor";

let cached: Platform | null = null;

export function getPlatform(): Platform {
  if (cached) return cached;
  if (typeof window === "undefined") {
    cached = "web"; // SSR
    return cached;
  }
  const w = window as unknown as Record<string, unknown>;
  if (typeof w["__TAURI_INTERNALS__"] !== "undefined" || typeof w["__TAURI__"] !== "undefined") {
    cached = "tauri";
    return cached;
  }
  if (typeof w["Capacitor"] !== "undefined") {
    cached = "capacitor";
    return cached;
  }
  cached = "web";
  return cached;
}

export function isNative(): boolean {
  const p = getPlatform();
  return p === "tauri" || p === "capacitor";
}
