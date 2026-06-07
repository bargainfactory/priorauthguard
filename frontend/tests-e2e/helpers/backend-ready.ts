/**
 * Global setup — polls the backend's /readyz until it responds.
 *
 * Skips with a thrown error if the backend isn't reachable after the
 * timeout; the runner converts that into a clear failure rather than a
 * timeout per test.
 */
import type { FullConfig } from "@playwright/test";

const BACKEND_URL = process.env.PAG_BACKEND_URL ?? "http://127.0.0.1:8080";
const TIMEOUT_MS = 60_000;
const POLL_MS = 1_000;

export default async function globalSetup(_config: FullConfig) {
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BACKEND_URL}/readyz`, { method: "GET" });
      if (res.ok) {
        const body = await res.json().catch(() => ({}));
        console.log(
          `Backend ready: env=${body.environment ?? "?"} fhe=${body.fhe_enabled ?? "?"}`,
        );
        return;
      }
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  throw new Error(
    `Backend at ${BACKEND_URL}/readyz did not respond within ${TIMEOUT_MS}ms — start uvicorn first.`,
  );
}
