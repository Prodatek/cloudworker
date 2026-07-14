# E2E tests (Playwright)

Scaffolded in Phase 8, deferred from Phase 7. Drives a real browser against the real running
dashboard, which talks to a real running API backed by a real Postgres database — unlike every
other test in this repo, there's no fake/mock layer here.

**Not run by CI or this project's automated verification.** Same standing limitation as every
Postgres-backed backend integration test since Phase 2: this development environment has no
Docker and no reachable Postgres, so there's never been a running backend for these to talk to.
Written and ready to run once that's available.

## Running these for real

1. Start Postgres and run migrations (see the root `README.md`'s Quickstart).
2. Start the backend: `docker compose up api` (or `uvicorn app.main:app` directly).
3. From `frontend/`:
   ```bash
   npx playwright install --with-deps chromium   # once, downloads a browser
   npm run test:e2e
   ```
   This starts the Vite dev server automatically (see `playwright.config.ts`'s `webServer`) and
   runs `e2e/smoke.spec.ts` against it. Set `E2E_BASE_URL` if you'd rather point it at an
   already-running dev server or a deployed environment instead.

## What's covered

`smoke.spec.ts`: register → (auto-login) → create a shell job → see it in the job list; and a
second spec confirming log out/log in preserves the account's job history. Intentionally minimal
— a smoke test proving the critical path wires together, not a full regression suite. Worth
expanding (browser job submission, API key management, cancel) once this is actually running in
CI against a provisioned environment.
