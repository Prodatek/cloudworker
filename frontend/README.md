# CloudWorker Dashboard

React + TypeScript (Vite) dashboard for CloudWorker: log in, submit shell/browser jobs, watch
status, download artifacts. See [`../docs/phase-7.md`](../docs/phase-7.md) for what shipped and
[`../docs/api-examples.md`](../docs/api-examples.md) for the underlying API this talks to.

## Quickstart

```bash
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://localhost:8000
npm install
npm run dev
```

Requires the backend running (`docker compose up api db` from the repo root, or `uvicorn` locally
per `../backend/README`-equivalent instructions in the root `README.md`).

## Scripts

```bash
npm run dev         # Vite dev server with HMR
npm run build        # tsc typecheck + production build
npm run typecheck    # tsc only, no build output
npm run lint          # oxlint
npm run test           # vitest (run once, no watch)
npm run generate-api    # regenerate src/api/generated/schema.d.ts from openapi.json
```

## API types

`src/api/generated/schema.d.ts` is generated from the backend's OpenAPI schema via
[`openapi-typescript`](https://openapi-ts.dev/), paired with
[`openapi-fetch`](https://openapi-ts.dev/openapi-fetch/) for a fully-typed client
(`src/api/client.ts`) — request/response shapes can't silently drift from what the backend
actually returns.

To regenerate after a backend contract change:

```bash
# from backend/, with the venv active:
python -c "import json; from app.main import app; json.dump(app.openapi(), open('../frontend/openapi.json', 'w'), indent=2)"

# from frontend/:
npm run generate-api
```

This isn't run automatically at build/CI time — `openapi.json` is a committed snapshot, so
`npm run build`/CI never need a live backend.

## Auth

Both API keys (`cw_live_...`, from `POST /api/v1/auth/register`) and JWTs (from `POST
/api/v1/auth/login`) work as the same `Authorization: Bearer <token>` header — the backend tells
them apart by the `cw_live_` prefix. This dashboard uses password login (`AuthContext`), storing
the JWT and a small user record in `localStorage`.

## Known local-environment limitation

`npm run test` (Vitest) fails in some local Windows setups where the project path contains a
literal `~` character (e.g. a Windows username shortened to `D~`) — this is a bug in `vite-node`'s
module-path resolution, not in this project's code or tests. Confirmed by running the identical,
unmodified test suite from a tilde-free path, where all tests pass. `npm run build`, `npm run
lint`, and `npm run typecheck` are unaffected. GitHub Actions runners never have a `~` in their
checkout path, so CI is unaffected either way.
