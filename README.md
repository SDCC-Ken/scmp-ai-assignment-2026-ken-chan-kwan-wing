# SCMP Internal Operations AI Assistant

This repository contains a coding-assignment proof of concept for the AI Engineer (Internal Automation) role at South China Morning Post.

Repository URL: <https://github.com/SDCC-Ken/scmp-ai-assignment-2026-ken-chan-kwan-wing.git>

## Assignment objective

The PoC provides a unified employee self-service chat experience for two internal operations workflows:

- Leave Application
- Staff Claim

It demonstrates mock Google SSO, role-aware access, AI-assisted intent detection and structured field extraction, explicit confirmation before submission, mock enterprise API integration, approval workflows, and auditability.

All accounts, requests, dates, policies, and records are fictional demonstration data. No real SCMP, employee, HR, or financial data is used.

## Technology

- Nuxt 4, TypeScript, and Tailwind CSS 4
- Python FastAPI, Pydantic, and LangGraph
- Google Gemini API with `gemini-3.8-flash` and low thinking
- SQLite and SQLAlchemy
- pytest, Playwright, and Docker Compose

## Engineering documentation

- [Agent engineering guide](AGENTS.md)
- [Agentic coding prompt log](PROMPT-INSTRUCTION.md)

## Development status

**Phase 0 (foundation) and Phase 1 (database, seed data, mock Google sign-in with real JWT auth in an httpOnly cookie) are complete.** The chat workflow, LangGraph agent, ReqRes submission and approval screens are added in later phases; this README is updated with each one.

## Deployment (Docker Compose)

Prerequisite: Docker Desktop (or Docker Engine) with the Compose plugin. Use `docker compose`, not `docker-compose`.

```bash
cp .env.example .env      # then edit .env and fill in the secrets (see below)
docker compose up --build
```

| Service | URL | Notes |
| --- | --- | --- |
| Frontend (Nuxt 4) | <http://localhost:9180> | Redirects to the mock Google sign-in (top-right prompt), then a role-aware home page |
| Backend (FastAPI) | <http://localhost:9181/health> | Returns `{"status":"ok"}`; interactive docs at `/docs` |

Useful commands:

```bash
docker compose up --build -d   # run in the background
docker compose ps              # both services should be Up; api should be (healthy)
docker compose logs -f         # follow logs
docker compose down            # stop; add -v to also delete the SQLite volume
```

The `web` service waits for the `api` healthcheck. SQLite is stored in the named volume `api-data` (mounted at `/app/data`), so data survives restarts.

### Configuration (`.env`)

`.env` is git-ignored and must never be committed. `.env.example` documents every variable.

| Variable | Purpose |
| --- | --- |
| `WEB_PORT` / `API_PORT` | Host ports for the frontend / backend (default `9180` / `9181`) |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_THINKING_LEVEL` | Gemini provider (used from Phase 1; `LLM_PROVIDER=fake` for offline runs) |
| `REQRES_API_KEY`, `REQRES_BASE_URL` | Hosted ReqRes mock API; requires an `x-api-key` header |
| `DB_AUTO_SEED` | Create tables and load the fictional demo data on startup when the database is empty (default `true`) |
| `AUTH_COOKIE_SECURE`, `AUTH_COOKIE_NAME` | Session cookie flags. Set `AUTH_COOKIE_SECURE=true` when served over https (production mode forces it). If you change the name, the frontend's "session expired" notice still expects `scmp_session` |
| `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`, `JWT_ISSUER` | JWT signing. Empty secret = random per-process secret in development (logins reset when the API restarts); production requires 32+ characters (`openssl rand -hex 32`) |
| `MOCK_SSO_ENABLED` | Enables the mock Google sign-in endpoints (default `true`) |
| `NUXT_PUBLIC_API_BASE` | Backend URL as seen by the browser |
| `NUXT_PUBLIC_THEME_*` | Light and dark theme colours (see below) |

Changing `.env` needs `docker compose up -d` again (recreate) to take effect. The theme and API base are read by Nuxt at runtime, so no image rebuild is needed for them.

### Theme

| Token | Light | Dark |
| --- | --- | --- |
| Primary | `#32a9e1` | `#7dd3fc` |
| Secondary | `#1e40af` | `#94a3b8` |
| Background | `#ffffff` | `#020617` |

Values are set through `NUXT_PUBLIC_THEME_{LIGHT,DARK}_{PRIMARY,SECONDARY,BACKGROUND}` and exposed as CSS variables and Tailwind tokens (`bg-primary`, `text-secondary`, `bg-background`). Invalid hex values fall back to the defaults. The theme toggle on the page switches light, dark, or system.

## Demo sign-in and seeded users

Open <http://localhost:9180>. A Google One Tap-style prompt is always shown in the top-right corner of the login page (close it with the X or Escape, and reopen it with the **Sign in with Google** button). Pick an account to continue. This is a **mock** sign-in: the page says so, nothing is sent to Google, and choosing an account signs you in immediately as that fictional user (no password). Behind it the backend issues a real signed JWT.

**Session cookie.** The JWT is delivered only in an `httpOnly`, `SameSite=Lax` cookie set by the API, so page scripts and browser storage never see it. The login response body contains no token. Writes (POST, PUT, PATCH, DELETE) must send `X-Requested-With: XMLHttpRequest` and, if an `Origin` header is present, it must be an allowed origin (a second defence against cross-site requests); the frontend does this automatically. The cookie is host-scoped, so it is shared by `localhost:9180` and `localhost:9181`. Deploying the web app and API on different hosts would need a same-origin reverse proxy, which is not part of this PoC. Disabling a user takes effect on the next request, because the API re-reads the user and role from the database every time.

| User | Email | Role | Can do (from the next phase) |
| --- | --- | --- | --- |
| Amy Lau, Ben Chow, Cathy Ng | `amy.lau@`, `ben.chow@`, `cathy.ng@example.com` | `employee` | Create Leave and Claim requests; view only their own |
| Daniel Wong | `daniel.wong@example.com` | `hr_approver` | List, view, approve, reject Leave requests only |
| Eva Cheung | `eva.cheung@example.com` | `finance_approver` | List, view, approve, reject Claim requests only |

Auth API (mounted under `/api/auth`): `GET /mock-users`, `POST /mock-google/login`, `GET /me`, `POST /logout`. The backend re-reads the user and role from the database on every request, so the role inside the token is never trusted on its own. Details and error codes are in [backend/README.md](backend/README.md).

## Database and seed data

SQLite (WAL mode, foreign keys enforced) through SQLAlchemy, stored in the `api-data` volume. Ten tables: `users`, `conversations`, `conversation_messages`, `leave_requests`, `claim_requests`, `external_submissions`, `notifications`, `audit_events`, `public_holidays`, `feedback`.

| Seed data | Rows | Notes |
| --- | ---: | --- |
| Users | 5 | 3 employees, 1 HR approver, 1 Finance approver (`@example.com`) |
| Leave requests | 10 | 2 pending, recent approved and rejected, the rest past history; includes half-day examples |
| Claim requests | 10 | Same mix, HKD amounts |
| Audit events | 15 | Creation, confirmation, API submission, a 429 failure then retry, approval, rejection |
| Conversations | 3 | With 9 short messages |
| Public holidays | 34 | Hong Kong 2026 and 2027 (17 each) |

Also seeded: 21 external-submission records, 6 notifications and 2 feedback rows. Every seeded record is fictional. Rebuild the demo data at any time:

```bash
docker compose exec api python -m app.cli seed --reset --yes   # drops and reseeds the database
```

**Request status flow** (enforced in the backend): `draft` → `pending_approval` (after confirmation and API submission) or `submission_failed` (retry allowed) → `approved` or `rejected`; `draft` and `submission_failed` can also be `cancelled`. Rejecting needs a reviewer note, and a reviewer cannot act on their own request. HR reviews Leave only; Finance reviews Claims only.

**Half-day leave.** `leave_requests` has `start_day_part` and `end_day_part` (`full`, `am`, `pm`), and `working_days` is a decimal in 0.5 steps.

| Request | start / end date | start_day_part / end_day_part | working_days |
| --- | --- | --- | ---: |
| Whole day | same date | `full` / `full` | 1 |
| Half day, morning or afternoon | same date | `am` / `am` or `pm` / `pm` | 0.5 |
| Several days, starting at noon | different dates | `pm` / `full` | first day counts 0.5 |
| Several days, ending at noon | different dates | `full` / `am` | last day counts 0.5 |

The working week is Monday to Friday, excluding Hong Kong public holidays. Those two optional fields are all the chat step needs to fill for "half day tomorrow afternoon".

### Hong Kong public holidays: yearly update

The 2026 and 2027 holidays are bundled from the official 1823 calendar (checked against the gov.hk holiday pages on 2026-09-25). 1823 publishes roughly three years ahead, so each year, once the new year appears, import it:

```bash
docker compose exec api python -m app.cli import-holidays --year 2028
# local (no Docker), from backend/
uv run python -m app.cli import-holidays --year 2028
# offline, from a downloaded calendar file
uv run python -m app.cli import-holidays --file path/to/en.ics --year 2028
```

The import is safe to re-run (it updates by date), and it stops with a clear message if the year is not yet published.

## Testing

Tests run locally, not inside Docker. Docker Compose is only used to run and demonstrate the stack.

| What | Command | Where |
| --- | --- | --- |
| Backend unit tests (237, offline) | `cd backend && uv run pytest -q` | local |
| Backend lint | `cd backend && uv run ruff check . && uv run ruff format --check .` | local |
| Frontend lint, types, unit tests (22) | `cd frontend && bun run lint && bun run typecheck && bun run test` | local |
| Full-stack smoke check | `docker compose up --build`, then open both URLs above | Docker |

Backend tests use in-memory or temporary SQLite databases, never read `.env`, and never call ReqRes or Gemini.

## Local development (without Docker)

Backend (Python 3.12 via `uv`):

```bash
cd backend
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run uvicorn app.main:app --port 9181 --reload
```

Frontend (Bun):

```bash
cd frontend
bun install
bun run lint && bun run typecheck && bun run test
bun run dev                    # http://localhost:9180
```

Both dev servers read the shared repo-root `.env`, which is optional for Phase 0.
