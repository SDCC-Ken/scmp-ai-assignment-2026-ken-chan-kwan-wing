# Prompt Instruction Log

This file records the real, step-by-step use of AI coding agents during this assignment. It is not a transcript of every conversation. Do not invent prompts, agent outputs, test results, or commits after the fact.

## Recording rules

For every material agent task, append an entry containing:

1. Date and phase.
2. The actual prompt given to the agent.
3. Scope boundaries and files the agent was allowed to change.
4. The agent result and the human review decision.
5. Commands run and their result.
6. The resulting Git commit hash.

Never record API keys, access tokens, private data, or full prompts containing sensitive material.

## Product brief

Create an Internal Operations AI Assistant with a mock Google SSO login and unified chat interface. It must use Python and a multi-agent orchestration framework to identify Leave Application or Staff Claim intent, collect the required fields through follow-up questions, show API loading, require confirmation, and send the request to the ReqRes mock endpoint. The submission must include a public Git repository, clear agent context documentation, meaningful commit history, unit tests, modular code, a README, and this prompt log.

The PoC uses Nuxt 3, FastAPI, LangGraph, Pydantic, SQLite/SQLAlchemy, Google Gemini API (`gemini-3.8-flash` with low thinking), pytest, Playwright, and Docker Compose.

## Entry 00 - Phase 0 planning (KEN)

- **Date:** 2026-09-25
- **Actual task:** Create project-level agent instructions, a prompt-log template, and a phase checklist before application code is created.
- **Result:** `AGENTS.md`, `PROMPT-INSTRUCTION.md`, and `PHASE-CHECKLIST.md` were created. No application code, credentials, or real data were created or added.
- **Human review:** Accepted as the baseline for subsequent agent tasks.
- **Commit:** `39c4f92` (first commit, made after repository initialisation in Phase 0). Note: `PHASE-CHECKLIST.md` is named above but was not present in the workspace when Phase 0 started, so it is not in the repository.

## Entry 01 - Phase 0 kickoff and foundation (Ken → integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), Claude Code, acting as main agent and Phase 0 integrator.
- **Actual prompt (Ken, condensed to the task list; the theme block is exact):**
  ```text
  Phase 0. You are the main agent and may create sub agents. Log what was done in PROMPT-INSTRUCTION.md with your model name.
  1 Init the repo with remote https://github.com/SDCC-Ken/scmp-ai-assignment-2026-ken-chan-kwan-wing.git
  2 Create .gitignore, .env and .env.example; do not commit or read .env (it will hold the real API token)
  3 Python backend: create, install dependencies, pytest to confirm they work [backend agent]
  4 Frontend with Nuxt 4 + TypeScript + Tailwind, with lint and typecheck passing [frontend agent]
  5 Theme env: Light primary #32a9e1, secondary #1e40af, background #ffffff;
    Dark primary #7dd3fc, secondary #94a3b8, background #020617
  6 Docker Compose so users can deploy backend and frontend
  7 Update README.md with the deployment steps
  Ken will test each phase before the next one starts.
  ```
- **Allowed scope:** integrator owned repo root, `.gitignore`, `.env`, `.env.example`, `docker-compose.yml`, `README.md`, `AGENTS.md`, `PROMPT-INSTRUCTION.md`; sub-agents were limited to `backend/` and `frontend/` (Entries 02 and 03).
- **Agent result:** `git init -b main` plus `origin` remote (nothing pushed); `.gitignore`; `.env.example` with ports, Gemini, ReqRes and `NUXT_PUBLIC_THEME_*` variables; `.env` copied from the template with empty secrets and never opened or printed. `AGENTS.md` and README said "Nuxt 3"; changed to Nuxt 4 / Tailwind CSS 4 per Ken's latest instruction.
- **Human review / changes requested:** Pending. Ken will test Phase 0 himself.
- **Verification commands and results:** `git check-ignore -v .env` matches the `.env` rule; `.env.example` matches the `!.env.example` negation, so it is tracked; `git ls-files` shows no `.env`, `node_modules`, `.venv`, `.nuxt` or `.db` files.
- **Commit:** `39c4f92` chore: add project foundation, env template and agent docs.

## Entry 02 - Phase 0 backend skeleton (backend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported by the sub-agent.
- **Actual prompt (condensed from the task brief):**
  ```text
  Phase: 0 - Foundation. Role: backend. File ownership: only backend/.
  Do not edit shared files or read/print .env; no git commit/push; no external API calls.
  Goal: runnable Python backend skeleton and proof that every dependency installs and imports.
  Use uv with CPython 3.12 (requires-python ">=3.12,<3.13"). Deps: fastapi, uvicorn, pydantic,
  pydantic-settings, sqlalchemy, httpx, langgraph, google-genai; dev: pytest, ruff.
  app/main.py with GET /health; app/config.py (pydantic-settings, SecretStr for keys, reads ../.env
  if present). Offline pytest tests: /health, dependency smoke (SQLite SELECT 1, httpx MockTransport,
  1-node LangGraph, google.genai import), settings. Non-root Dockerfile on port 9181.
  Verify: uv sync && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
  ```
- **Allowed scope:** `backend/` only.
- **Agent result:** Created `pyproject.toml`, `uv.lock`, `app/` (`main.py`, `config.py`), 3 test files, `Dockerfile`, `.dockerignore`, `README.md`. Key locked versions: fastapi 0.141.1, pydantic 2.13.5, sqlalchemy 2.1.0, httpx 0.28.1, langgraph 1.2.12, google-genai 2.25.0, pytest 9.1.1, ruff 0.16.9. The agent could not build the Dockerfile because Docker was not running at the time.
- **Human review / changes requested:** Integrator re-ran all checks independently and built the image. One defect was found in the combined setup (see Entry 04). Ken's own review is pending.
- **Verification commands and results (re-run by the integrator):** `uv run python --version` → 3.12.14; `uv run pytest -q` → 9 passed; `uv run ruff check .` clean; `uv run ruff format --check .` clean; `docker compose build api` succeeded.
- **Commit:** `1e317e8` feat(backend): add FastAPI skeleton with uv, settings and dependency tests.

## Entry 03 - Phase 0 frontend skeleton (frontend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported by the sub-agent.
- **Actual prompt (condensed from the task brief):**
  ```text
  Phase: 0 - Foundation. Role: frontend. File ownership: only frontend/.
  Use Nuxt 4 (not Nuxt 3), TypeScript, Tailwind CSS 4 via @tailwindcss/vite, Bun.
  Theme from env: NUXT_PUBLIC_THEME_{LIGHT,DARK}_{PRIMARY,SECONDARY,BACKGROUND} mapped to
  runtimeConfig.public.theme, injected SSR as CSS variables, Tailwind tokens (bg-primary etc.),
  light/dark/system toggle, hex validation with fallback (unit tested).
  ESLint (@nuxt/eslint) and nuxt typecheck; Vitest; dev port 9180. Non-root Dockerfile.
  Verify: bun install && bun run lint && bun run typecheck && bun run test && bun run build,
  then curl the SSR HTML for the six hex values and check an env override.
  ```
- **Allowed scope:** `frontend/` only.
- **Agent result:** Nuxt 4.5.2, Tailwind 4.3.3, Vue 3.5.43, ESLint 10.11.0, Vitest 5.0.1. TypeScript pinned to `~6.0` because 7.x is rejected by typescript-eslint. Nuxt 4 has no `dotenv` config key, so scripts pass `--dotenv ../.env` instead. `--theme-*` variables feed `@theme inline` to avoid a circular `--color-*` definition. Docker build not run by the agent (Docker was down).
- **Human review / changes requested:** Integrator re-ran lint, typecheck and tests, then ran the container (Entry 04). Ken's own review is pending.
- **Verification commands and results (re-run by the integrator):** `bun install --frozen-lockfile` no changes; `bun run lint` clean; `bun run typecheck` clean; `bun run test` → 4 passed. Agent-reported: `bun run build` succeeded, and an env override to `#ff0000` and an invalid value falling back to the default were both observed in SSR output.
- **Commit:** `74aeff1` feat(frontend): add Nuxt 4 skeleton with Tailwind 4 and env-driven theme.

## Entry 04 - Phase 0 integration: Docker Compose and README (integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`).
- **Actual prompt:** Steps 6 and 7 of Entry 01 (Docker Compose for backend and frontend; README deployment update). No separate sub-agent; these files are integrator-owned under `AGENTS.md`.
- **Allowed scope:** `docker-compose.yml`, `README.md`.
- **Agent result:** `docker-compose.yml` with `api` (9181, healthcheck) and `web` (9180, waits for `api` healthy), optional `.env` via `env_file`, SQLite in the `api-data` volume. README gained deployment, `.env` reference, theme table and local-development sections.
- **Human review / changes requested:** Defect found and fixed by the integrator: the first compose file mounted the volume at `/data`, which is root-owned, so the non-root API user could not write there (`touch /data/x` → Permission denied). Changed the mount and `DATABASE_URL` to `/app/data`, which the Dockerfile already chowns; a fresh volume then tested writable. Ken's own review is pending.
- **Verification commands and results:** `docker compose config --quiet` valid; `docker compose up --build -d` → `api` healthy, `web` up; `curl localhost:9181/health` → `{"status":"ok"}`; `curl localhost:9180` → HTTP 200 with all six theme hex values present in the HTML; `docker compose down` afterwards.
- **Commit:** `d9bb5d3` build: add Docker Compose deployment and document it in README.

## Entry 05 - Phase 1 kickoff, design decisions and shared inputs (Ken → integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), Claude Code, integrator.
- **Actual prompt (Ken, condensed to the task list; the table names are exact):**
  ```text
  Phase 1 on DB, using SQLite. 1 install the model to Python. 2 add safe SQLite and create dummy records.
  3 create tables: users, conversations, conversation_messages, leave_requests, claim_requests,
    external_submissions, notifications, audit_events, public_holidays (seed_2026 / 1823_ics), feedback
    (column lists supplied). Check how a user can apply for half-day leave.
  4 seed: 5 users (3 employees, 1 HR, 1 Finance), 10 leave (2 pending, 1 approved, 1 rejected, rest past history),
    10 claim (same), 12-16 audit events (creation, confirmation, API submission, approval, rejection, failures),
    2-3 conversations.
  5 seed safe 2026/2027 Hong Kong public holidays found on the internet; add a command and README steps for later years.
  6 unit tests for seed data, role resolution, validation and state transitions.
  7 Google sign-in mock in the frontend that shows the different roles and the 5 seed users (research the sign-in UI).
  8 show a "mock sign-in" warning; after clicking, log in as that user.
  9 create real auth and JWT with sign-in APIs.
  Also: commit locally; Nuxt 4 and TypeScript 6 accepted; check whether tests run in Docker or locally.
  ```
- **Allowed scope:** integrator only: research, `.env.example`, `docker-compose.yml`, `README.md`, `PROMPT-INSTRUCTION.md`, and placing `backend/app/data/hk_public_holidays_1823.ics`.
- **Agent result:**
  - Holidays: fetched the official 1823 iCal (2025-2027, 17 dates per year) and cross-checked 2026 and 2027 line by line against the gov.hk holiday pages; they matched.
  - Half-day design: added `start_day_part` / `end_day_part` (`full|am|pm`) to `leave_requests`, so `working_days` moves in 0.5 steps. This is an addition to the column list Ken supplied.
  - Added `DB_AUTO_SEED`, `JWT_*` and `MOCK_SSO_ENABLED` to `.env.example`, and `NUXT_API_BASE_SERVER` to compose so Nuxt SSR reaches the API over the compose network.
  - Answered the test question: tests run locally (`uv run pytest`, `bun run test`); Docker is only for running the stack.
  - Wrote the API contract used by both sub-agents (Entries 06 and 07).
- **Human review / changes requested:** Pending. Ken will test Phase 1.
- **Verification commands and results:** see Entry 08.
- **Commit:** `661e077` build: add auth/seed settings, server API URL and Phase 1 docs.

## Entry 06 - Phase 1 database, seed data and JWT auth (backend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported by the sub-agent.
- **Actual prompt (condensed from the task brief):**
  ```text
  Phase: 1 - Database, seed data, real JWT auth. Role: backend. File ownership: only backend/.
  A. SQLAlchemy 2 + SQLite with safe pragmas (foreign_keys, WAL, busy_timeout), tz-aware UTC timestamps,
     exact money, CHECK-constrained enums, the 10 tables and column lists from Ken (+ start/end_day_part).
  B. Pure domain rules: status state machine, role resolution, half-day leave calculation
     (Mon-Fri, excluding public holidays), Pydantic draft models.
  C. Holiday ICS parser/upsert and a CLI: init-db, seed [--reset --yes], import-holidays.
  D. Deterministic fictional seed with the counts Ken specified (5 users, 10 leave, 10 claim, 12-16 audit, 2-3 conversations).
  E. Real auth with PyJWT: GET /api/auth/mock-users, POST /api/auth/mock-google/login, GET /api/auth/me,
     POST /api/auth/logout; user and role re-read from the DB on every request; require_roles dependency.
  F. Offline tests for constraints, seed, roles, transitions, leave days, holidays, CLI and the auth API.
  Do not edit shared files or read .env; no commits; no ReqRes or Gemini calls.
  ```
- **Allowed scope:** `backend/` only.
- **Agent result:** Added `app/db`, `app/domain`, `app/schemas`, `app/services`, `app/auth`, `app/api`, `app/seed.py`, `app/cli.py` and 11 test files; new dependencies `pyjwt` and `email-validator`. After seeding: users 5, leave 10, claims 10, external submissions 21, audit events 15, conversations 3, messages 9, notifications 6, holidays 34, feedback 2. Deviations the agent reported: `audit_events.entity_id` is nullable (failed logins for unknown emails); login accepts a plain string and returns the same 401 for malformed and unknown emails; extra CHECK constraints (approver role per request type, reject needs a note, reviewed rows need a reviewer, amount and working_days positive); money stored as integer cents and day counts as integer tenths (not floats); only four showcase requests have audit rows.
- **Human review / changes requested:** Integrator read the JWT and login code: HS256 only, all claims required, expiry and issuer checked, no token or secret in logs or audit rows, identical error for unknown users. **Open point for Ken:** raw `working_days` shows `5` for a half day and `25` for 2.5 days (integer tenths), which is unfriendly when browsing the SQLite file; money is similarly stored as cents. Storing readable values is a small follow-up if Ken wants it.
- **Verification commands and results (re-run by the integrator):** `uv run pytest -q` 205 passed; `uv run ruff check .` and `ruff format --check .` clean. Agent-reported: local smoke test (login, `/me`, logout, bad email), CLI on a temp DB, and a live `import-holidays --year 2027` fetch from 1823 (17 updated; `--year 2031` exits non-zero with a clear message).
- **Commit:** `c81170c` feat(backend): add SQLite schema, domain rules, seed data, holidays CLI and JWT auth.

## Entry 07 - Phase 1 mock Google sign-in UI (frontend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported by the sub-agent.
- **Actual prompt (condensed from the task brief):**
  ```text
  Phase: 1 - Mock Google sign-in UI wired to real JWT auth. Role: frontend. File ownership: only frontend/.
  Research Google's official sign-in branding and the account-chooser layout first and follow them.
  /login with a mock warning visible before any click; a "Sign in with Google" button opens an accessible modal
  chooser listing the 5 seeded users by role; choosing one calls POST /api/auth/mock-google/login.
  useAuth/useApi with the JWT in a cookie, a global route guard, SSR validation through a private server-side API
  base URL (NUXT_API_BASE_SERVER), role-aware home page and sign out. Pure logic in utils with Vitest.
  Verify against a stub of the contract; lint, typecheck, test and build must pass. No edits outside frontend/.
  ```
- **Allowed scope:** `frontend/` only.
- **Agent result:** Added the login page, auth layout, six components (Google G mark, sign-in button, mock warning, role badge, account chooser modal, header), `useAuth`, `useApi`, a global auth middleware, `app/utils/auth.ts`, 14 new Vitest tests and a dev-only `scripts/mock-api-stub.ts`. Sources followed: the Google Identity branding guidelines and Sign in with Google HTML reference. Reported deviations: the button uses a `"Google Sans", Roboto, system-ui` stack without fetching fonts from Google; 40px height and 200px minimum width; no "Continue as" wording. The account chooser layout was modelled on a generic description rather than an official specification.
- **Human review / changes requested:** Integrator re-ran lint, typecheck and tests, then tested the real backend in the Docker stack (Entry 08). Known limitation reported by the agent: the JWT cookie is set from JavaScript, so it is not `httpOnly`; another open tab keeps its old user until it revalidates.
- **Verification commands and results (re-run by the integrator):** `bun run lint` clean; `bun run typecheck` clean; `bun run test` 18 passed (4 theme + 14 auth). Agent-reported: `bun run build` passes; SSR redirect and session behaviour checked with curl against a stub; chooser, focus trap, error states, 360px layout and computed text contrast (at least 4.5:1) checked in the browser pane.
- **Commit:** `2fd061c` feat(frontend): add mock Google sign-in wired to real JWT auth.

## Entry 08 - Phase 1 integration and end-to-end verification (integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`).
- **Actual prompt:** Integrate Entries 06 and 07, rebuild the Docker stack, test the real flow in the browser, and update the README.
- **Allowed scope:** integrator files (`README.md`, `.env.example`, `docker-compose.yml`, `PROMPT-INSTRUCTION.md`).
- **Agent result:** Stopped the stale Phase 0 containers left running from Ken's own `docker compose up` (they held ports 9180 and 9181), rebuilt and started the Phase 1 stack, and drove the sign-in flow in the Claude browser pane. README gained sections for demo sign-in, database and seed data, half-day rules, the yearly holiday update, and testing.
- **Human review / changes requested:** Pending. Ken will test Phase 1.
- **Verification commands and results:**
  - `docker compose up --build -d`: `api` healthy, `web` up.
  - API from the host: `mock-users` returned the 5 seed users; HR login returned a JWT; `/me` with it returned the user; no token, a bad token and an unknown email each returned 401; a CORS preflight from `http://localhost:9180` allowed the `Authorization` header.
  - Browser: `/` redirected to `/login`; the mock warning was visible before clicking; the chooser listed the seed users; signing in as Daniel Wong (HR Approver) landed on the role-aware home page; a hard reload kept the session and the server-rendered HTML contained the user name but no JWT; localStorage and sessionStorage were empty; the console had no messages; dark theme rendered; sign-out cleared the cookie and returned to `/login`.
  - Database in the volume: WAL mode; audit rows for the login, failed login, browser login and logout were present.
  - README commands checked inside the container against a throwaway database: `seed --reset --yes`, `import-holidays --file ... --year 2027` (17 updated) and `--year 2031` (clear error, non-zero).
- **Commit:** this log is committed in the commit that follows `661e077`.

## Entry 09 - Phase 1b research and decisions (Ken → integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), integrator.
- **Actual prompt (Ken, condensed):**
  ```text
  Test all users log in: good. Search the web: Google has a newer UI with the sign-in at the top-right corner; can we use it?
  Make the session save to a cookie. I want to know how a real Google sign-in avoids surprise sign-outs and signs a
  disabled user out, and what we could prepare for later. Check it out first.
  Follow-up decision: change our mock UI so it is always on the login page, similar to that top-right UI.
  Disabling users is on our side, so do the cookie only.
  ```
- **Allowed scope:** research only; no code changed in this step.
- **Agent result:** Read Google's One Tap, FedCM migration, ID-token verification and Cross-Account Protection (RISC) documentation. Findings reported to Ken: the top-right prompt is Google One Tap (browser-native under FedCM, so it cannot be reproduced authentically with fictional users); a real ID token is a one-time proof of identity, the app must issue its own session and key users by `sub`; Google does not notify an app when an employer disables a user, and RISC events cover Google-detected security problems. The offboarding and suspension claims came from vendor blog posts, not Google documentation, and were reported as secondary sources. Ken chose: mock top-right One Tap-style card always shown, and the httpOnly cookie only (no refresh tokens, sessions table or Google verifier interface).
- **Human review / changes requested:** Ken's scope decision above.
- **Verification commands and results:** none (research step).
- **Commit:** none.

## Entry 10 - Phase 1b httpOnly cookie and CSRF protection (backend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported by the sub-agent.
- **Actual prompt (condensed from the task brief):**
  ```text
  Phase: 1b. Role: backend. File ownership: only backend/.
  Deliver the JWT in an httpOnly cookie: login sets HttpOnly, SameSite=Lax, Path=/, Max-Age cookie and returns no token in the body;
  authenticated routes read the cookie (Bearer still accepted, Authorization wins); logout clears the cookie.
  CSRF: unsafe methods under /api require X-Requested-With: XMLHttpRequest and an allowed Origin if present, else 403.
  Add AUTH_COOKIE_NAME and AUTH_COOKIE_SECURE settings. Update tests and backend/README.md.
  No refresh tokens, sessions table or Google verifier abstraction.
  ```
- **Allowed scope:** `backend/` only.
- **Agent result:** New `app/auth/csrf.py` middleware; cookie handling in `app/api/routes/auth.py` and `app/auth/dependencies.py`; settings `auth_cookie_name` and `auth_cookie_secure` (Secure forced in production); `LoginResponse` without a token. Deviations reported: logout uses an explicit 1970 `Expires` because Starlette's `delete_cookie` expires at now; logout for an inactive user returns 204 and writes no audit row; a garbage Bearer header alongside a valid cookie returns 401.
- **Human review / changes requested:** Integrator reviewed the CSRF middleware and re-ran all checks; no changes requested.
- **Verification commands and results (re-run by the integrator):** `uv run pytest -q` 237 passed; `uv run ruff check .` and `ruff format --check .` clean.
- **Commit:** `830f926` feat(backend): deliver the JWT in an httpOnly cookie with CSRF protection.

## Entry 11 - Phase 1b top-right One Tap style prompt and cookie session (frontend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported by the sub-agent.
- **Actual prompt (condensed from the task brief):**
  ```text
  Phase: 1b. Role: frontend. File ownership: only frontend/.
  Part 1: replace the modal chooser with a Google One Tap-style card fixed top-right of /login, shown on load without a click, listing the
  5 seeded users, with MOCK labelling, an X/Escape to collapse and a button to reopen; keyboard operable; full-width on small screens.
  Part 2: the session is an httpOnly cookie set by the API; remove all token handling; send credentials: 'include' and the CSRF header;
  forward the cookie during SSR; update the stub, tests and README.
  ```
- **Allowed scope:** `frontend/` only.
- **Agent result:** New `GoogleOneTapCard.vue` (modal removed), cookie-based `useAuth`/`useApi`/middleware, updated stub and tests (22 passing). Deviations reported: on mobile the card sits in normal flow rather than pinned; the frontend hard-codes the cookie name `scmp_session` for the "session expired" notice; `logout()` now waits up to 3 seconds for the POST. The agent tested only against its stub.
- **Human review / changes requested:** Integrator tested against the real backend (Entry 12). Follow-up noted: the hard-coded cookie name would not follow a changed `AUTH_COOKIE_NAME`; this only affects the expired-session notice and is documented in the README.
- **Verification commands and results (re-run by the integrator):** `bun run lint` clean; `bun run typecheck` clean; `bun run test` 22 passed.
- **Commit:** `755f333` feat(frontend): always-visible top-right One Tap style prompt and cookie session.

## Entry 12 - Phase 1b integration and end-to-end verification (integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`).
- **Actual prompt:** Integrate Entries 10 and 11, rebuild the Docker stack, test against the real API in the browser, update the README.
- **Allowed scope:** `.env.example` (added `AUTH_COOKIE_SECURE`, `AUTH_COOKIE_NAME`), `README.md`, `PROMPT-INSTRUCTION.md`.
- **Agent result:** Rebuilt and restarted the stack; README now describes the top-right prompt, the httpOnly cookie, the CSRF header rule, the cookie settings and the different-hosts caveat.
- **Human review / changes requested:** Pending. Ken will test.
- **Verification commands and results:**
  - API from the host: login returned 200 with `HttpOnly; SameSite=Lax; Path=/; Max-Age=3600` and no token in the body; `/me` worked with the cookie only; a POST without the header and a POST from `http://evil.example` both returned 403; a CORS preflight allowed `X-Requested-With` with credentials for `http://localhost:9180`; logout returned 204 and expired the cookie.
  - Browser (Claude browser pane): the card appeared on load with all 5 users and no click; signing in as Eva Cheung (Finance Approver) landed on the home page; `document.cookie` contained only the theme cookie and storage was empty; `/me` returned 200 with credentials and 401 without; server-rendered HTML contained the name and no JWT; sign-out returned to `/login`; the 375px layout showed no overflow.
  - Not repeated in the browser this round: logins for the other four users (covered by backend tests and the earlier Phase 1 browser check as Daniel Wong).
- **Commit:** `0ab3401` docs: document cookie session, top-right sign-in prompt and cookie settings.

## Entry 13 - Phase 2 kickoff and decisions (Ken → integrator agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), integrator.
- **Actual prompt (Ken, condensed):**
  ```text
  Phase 2. 1 one simple chat UI. 2 use gemini-3.8-flash with Pydantic structured output to control and validate the final leave/claim form.
  3 ask again when something is wrong or misunderstood. 4 when all is OK show a confirmation card, save to SQLite and send to reqres.in with only
  the defined API fields, keep the rest in SQLite. 5 leave working days skip public holidays and Saturday/Sunday. 6 save every conversation so the
  user can call it back, continue editing, or cancel. 7 users can ask the LLM for the status of their leave and claims. 8 create success and failure
  test cases (e.g. wrong dates) for create, update and delete. 9 the Gemini key is in .env.
  Follow-ups: the assignment's API spec (screenshot: JSON keys `email`, `leave_type` "Annual", `start_date`, `end_date`; no token needed; claims use
  the same endpoint) - "you can try"; "rules will be set into phase 3, keep and can CRUD leaves and claims first"; single date must ask whether it is one day
  (single day is allowed); past leave is allowed only for sick leave; other rules are fine; write all rules to an md file; attachments 5 MB per file;
  the machine has Ollama, use it as a fallback if the key has a problem; do not use Gemini first (free quota); wait for the quota reset for phase 4 testing.
  ```
- **Allowed scope:** integrator: shared contracts (`backend/app/llm/{schemas,base}.py`, `backend/app/integrations/base.py`), settings, `docs/chat-api-contract.md`, `.env.example`, compose.
- **Agent result:**
  - Wrote the interface contracts and the chat API contract so three agents could work in parallel (LLM/ReqRes adapters, chat engine, UI).
  - The screenshot showed my earlier assumption was wrong (`employee_email` and a required key). Added `to_wire()` to the payload models, corrected AGENTS.md, and made the `x-api-key` header optional.
  - Made two live ReqRes calls (one leave, one claim, fictional sample data) to confirm: HTTP 201, string `id` and `createdAt`, plus extra `_meta` ignored.
  - Deferred the invented business rules to Phase 3 as Ken asked; the code has an empty rules registry. After Ken's answers the registry holds exactly one rule (past leave only for sick leave) and the single-date question was added.
  - Read Google's Gemini docs on rate limits (per project, daily reset at midnight Pacific, exact numbers only in AI Studio) and on image/PDF input.
  - Added Ollama settings and a container-to-host route (`host.docker.internal`); verified a Docker container can reach the host Ollama.
- **Human review / changes requested:** Ken made the rule decisions listed above.
- **Verification commands and results:** see Entries 14 to 17.
- **Commit:** `7ba037f` (documents); contract and settings files are in the backend commit (pending, see Entry 15).

## Entry 14 - Phase 2 Gemini/Ollama and ReqRes adapters (backend sub-agent B1)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported.
- **Actual prompt (condensed):**
  ```text
  Phase 2, role backend-B1. Own backend/app/llm/*, backend/app/integrations/*, their tests and scripts. Build: Gemini provider (gemini-3.8-flash, thinking level low,
  structured output validated by AgentTurn), a deterministic fake LLM, the ReqRes adapter sending payload.to_wire() only (x-api-key only when configured, no retries),
  a fake submission adapter, factories, offline tests, and a bounded live Gemini smoke script. Later tasks: attachments (multimodal parts, document extraction,
  sample fictional documents) and a local Ollama provider with an automatic fallback wrapper and PDF-to-image conversion.
  ```
- **Allowed scope:** `backend/app/llm/`, `backend/app/integrations/`, `backend/tests/llm|integrations/`, `backend/scripts/`, `backend/samples/`.
- **Agent result:** Gemini and Fake providers, ReqRes and fake adapters, factories, document-aware prompts and fake fixtures, four fictional sample documents, and (later, partly finished) Ollama provider, fallback wrapper and PDF renderer. Live checks: 1 of 12 Gemini cases completed before the free quota ran out (429) after 503 "high demand" errors, although the agent ran the smoke script four times against an instruction to run it once; two live ReqRes POSTs returned 201.
- **Human review / changes requested:** The agent was cut off by the account session limit while running the live Ollama comparison. The Ollama provider, fallback, PDF renderer and factory existed without tests. The integrator's live check of `qwen2.5:7b` then found it dropped explicit fields, so a follow-up agent was launched (Entry 18).
- **Verification commands and results:** the agent reported 181 tests passing in `tests/llm` and `tests/integrations` before the Ollama work; the whole suite was 599 passing and ruff clean when the integrator re-ran it after the interruption.
- **Commit:** pending (backend commit).

## Entry 15 - Phase 2 chat engine and business rules (backend sub-agent B2)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported.
- **Actual prompt (condensed):**
  ```text
  Phase 2, role backend-B2. Build the chat engine: LangGraph turn pipeline (understand, route, merge, validate, decide, respond) with a per-node AI trace, conversation state and
  additive schema changes, policy and validation with deterministic follow-ups, confirmation cards (confirm only via the newest card), create/update/cancel/retry/status flows,
  graceful LLM/ReqRes failures, the /api/chat endpoints, and offline tests. Later corrections: business rules deferred (empty registry), wire format via to_wire(); then Ken's rule
  decisions (single-date question, past leave only for sick leave) and a request to write docs/business-rules.md.
  ```
- **Allowed scope:** `backend/` except the LLM/integration files owned by B1; `docs/test-cases.md`.
- **Agent result:** LangGraph pipeline in `app/agent/graph.py`, `app/chat/*` (policy, validation, state, cards, actions), additive migrator, chat routes, new state transition `pending_approval` -> `cancelled` for the owner, and 3,395 lines of chat tests. The agent was cut off by the account session limit while updating tests for Ken's rule decisions and before writing the two documents.
- **Human review / changes requested:** The integrator confirmed the single-date question and the past-leave rule were already implemented and tested, then wrote `docs/business-rules.md` and `docs/test-cases.md` from the code and verified by script that every cited test exists.
- **Verification commands and results (integrator):** `uv run pytest -q` 599 passed; `ruff check` and `ruff format --check` clean (before the later agents began editing).
- **Commit:** pending (backend commit).

## Entry 16 - Phase 2 chat UI and attachment upload UI (frontend sub-agent)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`), self-reported.
- **Actual prompt (condensed):**
  ```text
  Phase 2, role frontend. One simple chat for employees at `/`: conversation list with New chat, thread, composer, confirmation/status/result cards, loading state, collapsible AI trace,
  resume old conversations, warning banners, stale-card handling; approvers keep the "coming next phase" panel. Then Phase 2b: attach (button, drag-drop, paste), 5 MB and 3-file limits,
  staged chips, thumbnails via credentialed fetch, preview dialog, "from document" tags. Develop against the API contract and a dev stub.
  ```
- **Allowed scope:** `frontend/` only.
- **Agent result:** New composables, types, utilities, 15 components, an extended stub. Deviations reported: indeterminate spinner instead of a progress bar; Send blocked while an upload fails; an empty new chat is reused instead of creating another.
- **Human review / changes requested:** Integrator re-ran the checks. Not yet tested against the real backend (the attachment endpoints do not exist yet).
- **Verification commands and results (integrator):** `bun run lint` clean; `bun run typecheck` clean; `bun run test` 70 passed; `bun run build` complete.
- **Commit:** `a90b427` feat(frontend): add employee chat UI with cards, AI trace and attachment upload.

## Entry 17 - Rules, test-case and Phase 3 documents (integrator)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`).
- **Actual prompt:** Ken: write all the validation rules to an md file (Entry 13); later Phase 3 brief (13 points on departments, approval routing, limits, reviewer note, bell notifications and audit).
- **Allowed scope:** `docs/`, `AGENTS.md`.
- **Agent result:** `docs/business-rules.md` (Leave, Claim, update/cancel, chat rules with IDs, status, enforcement location, follow-up text and proving tests), `docs/test-cases.md` (create/update/cancel success and failure matrix), and `docs/phase3-approval-design.md` (people and routing, limits, approver API, notifications, seed and schema changes). Ken's Phase 3 brief required two design changes: approvers can also file requests (Cathy), and the reviewer note becomes optional, which removes a database check and therefore needs a database reset.
- **Human review / changes requested:** Pending. Assumptions that Ken can change are marked **(assumption)** in the Phase 3 design (leave entitlements 15/10 days, department claim limits, counting rules).
- **Verification commands and results:** a script confirmed every test name cited in both documents exists in `backend/tests`.
- **Commit:** `7ba037f` docs: add chat API contract, business rules, test cases and Phase 3 design.

## Entry 18 - Local model tuning and delegated follow-ups (integrator, then sub-agents)

- **Date:** 2026-09-25
- **Model:** Sonnet 5 (`claude-sonnet-5`).
- **Actual prompt:** Ken: the machine has Ollama, use it as a fallback and do not use Gemini for now; then, after the agents were cut off: "do not continue your jobs, create some small sub agents to do the work that is not finished".
- **Allowed scope:** live experiments only (no code committed from them); two new sub-agents with separate file ownership.
- **Agent result:** The integrator ran live tests of the local models on five text cases. `qwen2.5:7b` always returned valid JSON but skipped fields such as leave type; `llama3.1:8b` was more accurate on the leave type but returned invalid JSON on 2 of 5 cases (about 60 s each); `gemma3:12b` failed most cases and took over 100 s. A flat schema with a compact prompt scored 9 of 12 on `qwen2.5:7b`; the remaining failures were a cold-model timeout, the one-day reply and "next Monday" date arithmetic. Two sub-agents were then launched: one to finish the Ollama provider (flat schema, calendar table, tests, live comparison, smoke script) and one to build attachment storage and the upload/download API.
- **Human review / changes requested:** Ken asked for delegation to small agents rather than the integrator continuing the work.
- **Verification commands and results:** pending the two agents' reports.
- **Commit:** pending.

## Entry template

### Entry NN - [phase and short task name]

- **Date:** YYYY-MM-DD
- **Actual prompt:**
  ```text
  Paste the exact safe prompt here.
  ```
- **Allowed scope:**
- **Agent result:**
- **Human review / changes requested:**
- **Verification commands and results:**
- **Commit:**
