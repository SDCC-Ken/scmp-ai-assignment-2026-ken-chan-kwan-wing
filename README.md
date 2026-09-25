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

**Phase 0 (foundation) is complete:** repository, environment template, Python backend skeleton, Nuxt 4 frontend skeleton with env-driven theming, and Docker Compose deployment. The chat workflows, mock SSO, LangGraph agent, and approvals are added in later phases; this README is updated with each one.

## Deployment (Docker Compose)

Prerequisite: Docker Desktop (or Docker Engine) with the Compose plugin. Use `docker compose`, not `docker-compose`.

```bash
cp .env.example .env      # then edit .env and fill in the secrets (see below)
docker compose up --build
```

| Service | URL | Notes |
| --- | --- | --- |
| Frontend (Nuxt 4) | <http://localhost:9180> | Placeholder Phase 0 page with theme toggle |
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
