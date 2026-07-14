import { defineConfig, devices } from "@playwright/test";

// E2E scaffold (Phase 8) — see frontend/e2e/README.md for why these aren't run in CI/this
// sandbox yet: they need a real backend + Postgres, which this project's automated
// verification hasn't had access to since Phase 2.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "html",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Starts the Vite dev server for the test run. Does NOT start the backend — that needs
  // Postgres, which is out of scope for this config; point E2E_BASE_URL at an already-running
  // dev server (`npm run dev`) with the backend already up if you'd rather manage it yourself.
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
