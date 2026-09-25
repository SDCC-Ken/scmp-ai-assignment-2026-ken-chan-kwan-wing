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
- [Validation and business rules](docs/business-rules.md), [test cases](docs/test-cases.md)
- [Chat API contract](docs/chat-api-contract.md), [Phase 3 approval design](docs/phase3-approval-design.md)
- [Changing limits and approvers](docs/limits-and-routing.md)

## Development status

**Phases 0 to 3 are implemented:** foundation and Docker; database, seed data and mock Google sign-in with real JWT auth; the AI chat (leave and claims, confirmation cards, ReqRes submission, attachments and documents, status, change and cancel); and the approval workflow (departments, per-user approvers, leave balances, department claim limits, approver screens, reviewer note, audit events and the notification bell). Phase 4 is end-to-end testing and the live Gemini check.

## What the assistant does

- **Employees** (Amy, Ben, Daniel, and Cathy for her own requests) chat in plain English: leave and staff claims, half days, single days, status, balance ("how many annual leave days do I have left?"), change and cancel. Anything the AI reads is validated by the backend, and **nothing is saved or sent until the user presses Submit on a card**. The submission goes to `POST https://reqres.in/api/users` with only the specified fields (`email`, `leave_type` / `claim_type`, dates, `amount`); everything else stays in SQLite.
- **Documents:** attach an image or PDF (5 MB, 3 files) such as a sick note or receipt; the AI fills the draft, tags values "from document", and asks for anything missing. Sample fictional files are in `backend/samples/`.
- **Approvers** (Cathy and Helen for leave, Eva for claims) see only the pending requests assigned to them, with the requester's balance or the department budget, an over-limit warning, teammates on leave at the same time, attachments, and an optional note; approving or rejecting is confirmed and audited. Limits are shown but never block: the approver decides.
- **Everyone** has a bell with unread notifications (new request, change or cancel for approvers; decision for requesters).
- Rules and limits are listed in [docs/business-rules.md](docs/business-rules.md). Only the four employees can file requests; Helen and Eva have no approver configured, by design.

## AI providers

| Setting | Meaning |
| --- | --- |
| `LLM_PROVIDER=ollama` | Local models through Ollama (default model `gemma4:latest` for text and documents). No key, no quota. |
| `LLM_PROVIDER=gemini` | Google Gemini `gemini-3.8-flash` (free tier has daily limits; see below). |
| `LLM_FALLBACK_PROVIDER=ollama` | If the primary fails (bad key, quota, outage) the chat switches to the fallback automatically, with a short cooldown. |
| `LLM_PROVIDER=fake` | Deterministic rules for offline development and tests only. |

Run with local AI only, without editing `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up --build
```

The containers reach Ollama on your machine through `host.docker.internal`; keep `ollama serve` running and `ollama pull gemma4:latest` done. The first request after a pause loads the model and can take about 30 seconds. Gemini limits apply per Google project (not per key) and the daily quota resets at midnight Pacific time; exact numbers are in Google AI Studio.

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

| User | Department | Role | Leave approver | Claim approver | Can do |
| --- | --- | --- | --- | --- | --- |
| Amy Lau, Ben Chow | IT | `employee` | Cathy Ng | Eva Cheung | Chat: leave and claims, status, balance, change, cancel |
| Daniel Wong | HR | `employee` | Helen Yeung | Eva Cheung | Same as above |
| Cathy Ng | HR | `hr_approver` | Helen Yeung | Eva Cheung | Chat for her own requests, and approves **IT department leave** |
| Helen Yeung | HR (manager) | `hr_approver` | none | none | Approves **HR department leave** (Cathy, Daniel); no chat |
| Eva Cheung | Finance | `finance_approver` | none | none | Approves **all claims**; no chat |

Every requester has exactly one approver per request type, stored per user (see [docs/limits-and-routing.md](docs/limits-and-routing.md)). Emails are `firstname.lastname@example.com`.

Auth API (mounted under `/api/auth`): `GET /mock-users`, `POST /mock-google/login`, `GET /me`, `POST /logout`. The backend re-reads the user and role from the database on every request, so the role inside the token is never trusted on its own. Details and error codes are in [backend/README.md](backend/README.md).

## Database and seed data

SQLite (WAL mode, foreign keys enforced) through SQLAlchemy, stored in the `api-data` volume. Tables: `departments`, `leave_entitlements`, `attachments`, `schema_meta`, `users`, `conversations`, `conversation_messages`, `leave_requests`, `claim_requests`, `external_submissions`, `notifications`, `audit_events`, `public_holidays`, `feedback`.

| Seed data | Rows | Notes |
| --- | ---: | --- |
| Users | 6 | 3 employees, 2 HR approvers, 1 Finance approver (`@example.com`), 3 departments |
| Leave requests | 10 | 2 pending, recent approved and rejected, the rest past history; half-day examples; one overlaps a colleague, one exceeds the annual balance |
| Claim requests | 10 | Same mix, HKD amounts; one pending claim takes HR over its department limit |
| Audit events | 15 | Creation, confirmation, API submission, a 429 failure then retry, approval, rejection |
| Conversations | 3 | Short fictional chats |
| Public holidays | 34 | Hong Kong 2026 and 2027 (17 each) |

Also seeded: external-submission records, notifications for the pending and decided requests, department claim limits, leave entitlements (annual 15 and sick 10 days for 2026 and 2027, with small variations) and 2 feedback rows. Every seeded record is fictional.

**Upgrading from an earlier phase:** Phase 3 changed the database schema (departments, approvers, and the reviewer note is now optional), so an existing database must be recreated once: `docker compose down -v` (or the reset command below). The API detects an old database, keeps running, and logs this instruction. Rebuild the demo data at any time:

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
| Backend unit tests (1,403, offline) | `cd backend && uv run pytest -q` | local |
| Backend lint | `cd backend && uv run ruff check . && uv run ruff format --check .` | local |
| Frontend lint, types, unit tests (123) | `cd frontend && bun run lint && bun run typecheck && bun run test` | local |
| Full-stack smoke check | `docker compose -f docker-compose.yml -f docker-compose.ollama.yml up --build`, then open both URLs above | Docker |
| Live AI check (opt-in) | `cd backend && RUN_LIVE_LLM=1 uv run python scripts/live_llm_smoke.py --provider ollama` (Gemini also needs `ALLOW_LIVE_GEMINI=1`) | local |

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
