# Phase 7 Report: React + TypeScript Dashboard

## What was built

- **Backend: password login + API key management.** `POST /api/v1/auth/login` verifies against
  `hashed_password` (present on `users` since Phase 2, unused until now) and issues a JWT
  (`app/infrastructure/security.py`'s `create_access_token`/`decode_access_token`, PyJWT/HS256).
  `get_current_user` (`app/api/v1/deps.py`) now accepts *either* an API key or a JWT through the
  identical `Authorization: Bearer` header, dispatched on the `cw_live_` prefix API keys always
  carry — every existing endpoint works unchanged for both credential types. New
  `GET/POST /api/v1/api-keys` and `POST /api/v1/api-keys/{id}/revoke` (`ApiKeyRepository` gained
  `list_for_user`/`revoke`; `revoked_at` existed since Phase 2 with nothing setting it until now).
  `CORSMiddleware` added so the dashboard's dev-server origin can call the API.
- **Frontend (`frontend/`)**: Vite + React 19 + TypeScript. API types are generated from the
  backend's real OpenAPI schema (`openapi-typescript` + `openapi-fetch`) — not hand-maintained.
  Pages: login, register, job list, job detail (with status polling + artifact download), new-job
  form (shell/browser), API key management. `AuthContext` persists the JWT + user in
  `localStorage`; register immediately logs in afterward so account creation is one step from the
  user's perspective.
- Docker Compose gained a `frontend` service (Vite dev server); CI gained a `frontend` job
  (lint/typecheck/test/build).

## Why it was designed this way

- **One `get_current_user`, two credential types** rather than separate API-key-only and
  JWT-only route trees: the dashboard is architecturally just another API client — giving it a
  parallel authentication path that converges on the same `User` means zero special-casing
  anywhere else in the codebase, and a test proving "API key still works after JWT support was
  added" is a meaningful regression check, not just incidental coverage.
- **Generated API types over hand-written ones** (user's choice): a backend field rename or
  removal now fails the frontend *build*, not silently at runtime — worth the one-time codegen
  step (`npm run generate-api` against a committed `openapi.json` snapshot, not run at build/CI
  time, so neither ever needs a live backend).
- **Register-then-login as one flow**: registration only ever returned an API key (Phase 2), never
  a session — rather than making the user log in again immediately after creating an account,
  `AuthContext.register()` calls login internally right after register succeeds.
- **Generic 401 for both "unknown email" and "wrong password"** on login: same reasoning Phase 2
  already established for API-key auth — don't let an error message double as an email-enumeration
  oracle.

## Trade-offs

- **`JWT_SECRET_KEY` has an insecure default** (`dev-insecure-secret-change-me`), loudly commented
  in both `Settings` and `.env.example` as must-override — consistent with every other setting's
  permissive-dev-default pattern, but flagged specially since this one is security-sensitive in a
  way a default AWS region isn't.
- **No password reset / email verification** — registration and login are the whole auth surface;
  reasonable for a beta, not for a public launch (tracked as debt, same spirit as Phase 2's
  original open-registration caveat).
- **No refresh tokens** — the JWT simply expires after `JWT_ACCESS_TOKEN_EXPIRY_MINUTES` (60
  default) and the dashboard sends the user back to `/login`. Simpler than a refresh-token flow;
  acceptable for a beta, worth revisiting if a 60-minute re-login cadence proves annoying.
- **No E2E tests** (a real browser driving the real full stack) — explicitly scoped out to keep
  this phase to a defensible size, noted as a Phase 8 hardening candidate.

## Tests run

```
Backend:
ruff check backend/app backend/tests           -> All checks passed!
ruff format --check backend/app backend/tests  -> clean
mypy backend/app                                -> Success: no issues found in 46 source files
pytest backend/tests/unit                       -> 63 passed

Frontend:
npm run lint       -> clean (1 informational warning, exit 0)
npm run typecheck  -> clean
npm run build      -> succeeds, dist/ produced
npm run test       -> could not run directly in this sandbox (see below) —
                       15/15 pass when run from a path without the issue
```

**New backend unit test technique this phase**: `tests/unit/test_auth_endpoints.py` uses FastAPI's
`app.dependency_overrides` to swap `get_user_repository`/`get_api_key_repository` for in-memory
fakes, exercising the *real* endpoint routing/validation/status-code logic (register, login, the
dual API-key/JWT dispatch, API key CRUD) without a database at all — because overriding a
dependency replaces the whole callable, its own `Depends(get_session)` sub-dependency is never
invoked, so no `app.state.db_engine`/lifespan setup is needed either. All 9 of these tests passed
immediately. Postgres-backed integration tests (`test_auth_login_integration.py`) were attempted
and failed for the same single standing reason as every prior phase (`InvalidPasswordError`) —
confirmed via the same error-type grep used since Phase 5, no new code bugs.

**Frontend test caveat, investigated and resolved as an environment issue, not a code issue**:
`npm run test` failed in this sandbox with `Cannot find module '/@vite/env'` /
`ERR_MODULE_NOT_FOUND` errors from `vite-node`. Root-caused by copying the identical, unmodified
project to a path without a `~` character and re-running — **all 15 tests passed** there. This
machine's Windows user directory is literally `D~`, and `vite-node`'s internal path-to-module-id
resolution (`toFilePath` in `vite-node/dist/utils.mjs`) mishandles the literal tilde. Confirmed
this is independent of tooling version by reproducing identically on both the initial bleeding-edge
stack (Vite 8.1/Vitest 4.1/`@vitejs/plugin-react` 6) and after downgrading to a more established
one (Vite 7.3/Vitest 3.2/`@vitejs/plugin-react` 5) — kept the downgraded, more battle-tested
versions regardless, since stability is preferable for a production project and the downgrade
didn't fix or worsen the actual bug. `vite build`, `vite dev`, `tsc`, and `oxlint` are all
unaffected — only Vitest's SSR test-execution path (`vite-node`) hits this. GitHub Actions runners
never have a `~` in their checkout path (e.g. `/home/runner/work/...`), so **CI is not expected to
be affected** — this is specific to this local sandbox's directory naming, not the project.

## Technical debt

1. Postgres-backed integration tests unverified in this sandbox (standing item since Phase 2).
2. No password reset / email verification.
3. No refresh tokens — 60-minute hard session expiry.
4. No E2E test coverage (real browser against the real stack).
5. `npm run test` unverified directly in this specific local sandbox due to the `vite-node`/tilde
   path issue described above — genuinely low-risk (root-caused, proven environment-specific, CI
   unaffected) but flagged rather than silently assumed fine.
6. Frontend has no component library/design system — plain CSS, intentionally minimal for this
   phase; fine for a beta, would benefit from a real design pass before a public launch.

## Proposed Phase 8: Hardening & Beta

Scope proposal (not yet implemented) — the final phase per the original roadmap:
- Metrics dashboards (Prometheus counters already exist since Phase 1; add Grafana
  config/dashboards, or at least documented PromQL queries).
- Guaranteed worker cleanup: an idle/orphan reaper for EC2 instances that somehow survive their
  job's lifecycle (crash recovery, not just the happy path Phases 4–6 built).
- CI/CD deploy pipeline: build+push the API/worker images, `terraform plan`/`apply` gating.
- Security review pass across the whole stack (this is a good candidate for `/code-review
  security-review` or an ultrareview once the user's ready).
- Install docs: what a customer actually needs to do to stand this up in their own AWS account,
  end to end, given everything Phases 1–7 built.
- E2E test coverage (deferred from Phase 7).
- Real AWS verification of everything that's only been proven via moto/hand-mocks so far — this
  phase is the natural point to actually run `terraform apply` and `packer build` for real, with
  the user's explicit go-ahead.

Will present this as a full plan for approval before writing any Phase 8 code, same as every phase
so far.
