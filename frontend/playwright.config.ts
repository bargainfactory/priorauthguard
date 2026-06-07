import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for PriorAuthGuard end-to-end tests.
 *
 * The test runner boots the Next.js dev server itself (so CI doesn't need
 * a separate process). The backend is expected to be reachable at
 * `PAG_BACKEND_URL` (default `http://127.0.0.1:8080`). The
 * `backend-ready` global setup in `tests-e2e/helpers/backend-ready.ts`
 * polls `/readyz` so flaky races during `pytest` warm-up don't fail
 * the suite.
 */
export default defineConfig({
  testDir: "./tests-e2e/specs",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  globalSetup: "./tests-e2e/helpers/backend-ready.ts",
  use: {
    baseURL: process.env.PAG_E2E_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://127.0.0.1:3000",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    env: {
      // Proxy /api/* to the local backend in dev / E2E.
      NEXT_PUBLIC_BACKEND_URL: process.env.PAG_BACKEND_URL ?? "http://127.0.0.1:8080",
    },
  },
});
