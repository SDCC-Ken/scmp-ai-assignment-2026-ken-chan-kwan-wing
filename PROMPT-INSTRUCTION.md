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
