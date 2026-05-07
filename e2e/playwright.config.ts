import { defineConfig, devices } from "@playwright/test";

// Phase 7 demo e2e. Targets a running stack (backend on :8000, frontend
// on :3001) — see README's "Локальный dev" section. CI (when wired up)
// can launch them via `webServer:` blocks; for now the dev expects you
// to start backend + frontend yourself before running.

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:3001";
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // shared backend state; run serially
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: FRONTEND_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    extraHTTPHeaders: { "x-graphrag-e2e": "1" },
    locale: "ru-RU",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  metadata: {
    backend: BACKEND_URL,
    frontend: FRONTEND_URL,
  },
});
