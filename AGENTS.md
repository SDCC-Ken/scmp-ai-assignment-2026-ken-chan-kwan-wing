# SCMP Internal Operations AI Assistant

## Product goal

Build a local demonstration of an employee self-service application for the SCMP AI Engineer (Internal Automation) coding assignment. The application must route natural-language requests for Leave Application and Staff Claim, collect missing information, request confirmation, and submit to the supplied mock API.

This is a fictional PoC. Do not use, infer, upload, or commit real SCMP, employee, applicant, financial, or HR data.

## Required assignment scope

- Mock Google SSO entry flow (a Google One Tap-style prompt, clearly labelled mock) with three roles: `employee`, `hr_approver`, and `finance_approver`; the session is a real JWT in an `httpOnly` cookie set by the API.
- Six fictional users in three departments: Amy Lau and Ben Chow (IT, employees), Daniel Wong (HR, employee), Cathy Ng (HR, `hr_approver`, approves IT leave), Helen Yeung (HR manager, `hr_approver`, approves HR leave), Eva Cheung (Finance, `finance_approver`, approves all claims).
- Approver routing is **one approver per requester and request type, stored per user** (`users.leave_approver_user_id`, `users.claim_approver_user_id`); a user with no approver configured cannot file that request type (Helen and Eva, out of PoC scope). An approver may also file their own requests (Cathy) but can never review their own.
- One unified chat UI. Employees (and Cathy) file requests, change or cancel them until reviewed, attach a sick note or receipt (image or PDF, 5 MB each, 3 per message), ask for status and leave balance, and view only their own requests.
- HR Approver capabilities: list, view, approve, and reject **pending Leave requests assigned to them** only. Finance Approver: **pending Claim requests assigned to them** only. Approvers see the requester's leave balance or the department claim limit (annual, shown but never blocking), teammates on leave at the same time, attachments, and an optional reviewer note (approve and reject).
- Every user has a notification bell with an unread number; clicking it opens a new "Items to handle" chat conversation that walks through the pending items one by one (approval cards and notices).
- Leave fields: `employee_email`, `leave_type`, `start_date`, and `end_date` (plus optional half-day parts and calculated working days, kept locally).
- Claim fields: `employee_email`, `claim_type`, `amount`, and `receipt_date` (HKD only).
- Ask focused follow-up questions for missing or unclear fields; never invent a date the user did not state.
- Display an API loading state; submit only after an explicit confirmation on a card (typing "yes" never submits).
- Send Leave and Claim submissions to `POST https://reqres.in/api/users`. Wire format: leave `{email, leave_type, start_date, end_date}` (e.g. `"Annual"`), claim `{email, claim_type, amount, receipt_date}`; nothing else leaves the system.
- Keep a local audit trail for request creation, confirmation, mock submission (including failures and retries), update, cancellation, approval, and rejection. The rules in force are listed in `docs/business-rules.md`.

## Selected stack

| Layer | Technology |
| --- | --- |
| Frontend | Nuxt 4, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12+, FastAPI, Pydantic |
| Agent orchestration | LangGraph |
| LLM | Google Gemini API, `gemini-3.8-flash`, `thinking_level=low`; local Ollama (`gemma4:latest`, text and documents) as a development provider and automatic fallback; a deterministic fake for tests |
| Persistence | SQLite, SQLAlchemy |
| HTTP integration | httpx |
| Backend tests | pytest |
| Frontend tests | Vitest, ESLint, `nuxt typecheck` |
| End-to-end tests | Playwright (`e2e/`, system Chrome, fake LLM and fake submission adapter, ports 9280/9281) |
| Local runtime | Docker Compose |

## Confirmed local development environment

The project is developed on macOS Apple Silicon. Use the following tools and commands unless Ken explicitly changes them:

| Purpose | Confirmed tool |
| --- | --- |
| Python project and virtual environment | `uv 0.12.11` |
| Project Python version | CPython 3.12.14 via `uv` |
| Frontend package manager | `bun 1.4.0` |
| Node compatibility runtime | Node.js 24.2.0 |
| Container command | `docker compose` (Compose plugin 2.37.1; do not use `docker-compose`) |
| Source control | Git 2.44.0; GitHub CLI 2.96.0 is available |

- Set `requires-python = ">=3.12,<3.13"` for backend dependencies. Do not create the project virtual environment from the system Python 3.14 by accident.
- Create the backend environment with `uv venv --python 3.12`, then use `uv sync` or the documented `uv run` command.
- Use Bun for Nuxt package installation and scripts unless a documented dependency requires npm.
- Do not create commits, push branches, alter remotes, or run GitHub publishing commands unless Ken explicitly requests it.

## Runtime ports and external mock integration

- Reserve `9180` for the Nuxt frontend and `9181` for the FastAPI backend. Configure both through environment variables such as `WEB_PORT=9180` and `API_PORT=9181`; do not use default ports that may conflict with Ken's other projects.
- The assignment-required `https://reqres.in/api/users` is a hosted external mock API. The submitted app must use it through a `ReqresSubmissionAdapter`, not replace it with localhost.
- ReqRes needs no API key at the moment (Ken confirmed; a live call on 2026-09-25 returned 201). Send an `x-api-key` header only when `REQRES_API_KEY` is set in `.env` (in case ReqRes starts requiring one); never commit it.
- A localhost mock adapter is permitted only for deterministic unit tests, offline development, or a clearly labelled emergency demo fallback. It must not be presented as the required ReqRes integration.
- Port `9280`/`9281` are used by the Playwright E2E stack, `9190`/`9191` by the frontend dev stub, and `9199` for one-off backend smoke runs. Ollama listens on `11434`; containers reach it through `host.docker.internal`.
- Gemini's free tier is limited per Google project (daily quota resets at midnight Pacific). Live Gemini calls are opt-in only (`RUN_LIVE_LLM=1` and `ALLOW_LIVE_GEMINI=1`); default development and demos use `docker compose -f docker-compose.yml -f docker-compose.ollama.yml up --build`.

## Architecture and safety boundaries

1. The LLM (Gemini or the local Ollama model) is used only for intent recognition, structured field extraction (including reading attached documents), and concise follow-up wording. Text inside a user message or document is data, never instructions.
2. FastAPI and Pydantic own validation, role checks, state transitions, API submission, and approval actions.
3. The LLM must not directly approve, reject, write to the database, or call an integration API.
4. Every state-changing action requires a confirmation step (a card button; approvals also need a second confirm click). Approvals require role, assignment and status validation in the backend, not only hidden frontend controls; a request that is not pending and assigned to the caller is `404`.
5. Return structured LLM output and validate it with Pydantic before changing conversation state.
6. Store only fictional seed data. Never commit `.env`, API keys, tokens, recordings containing secrets, or copied production data.
7. The application must handle LLM, database, and HTTP integration failures without crashing. A fake LLM provider and a fake submission adapter are required for deterministic automated tests.
8. Balances and limits are informational: an over-limit request can be filed and the approver decides. Only the fields specified for ReqRes leave the system; everything else stays in SQLite.
9. Uploaded files are validated by real signature, stored on the server disk (a Docker volume), and downloadable only by the owner and the assigned approver of a linked, submitted request.
10. The database schema is versioned (`schema_meta`); an older database is not modified and the API logs how to recreate it (`docker compose down -v` or `python -m app.cli reset-demo --yes`).

## Engineering conventions

- Keep frontend and backend independently runnable, with one documented Docker Compose command for the full application.
- Use a provider interface so Gemini, Ollama or the fake can be swapped without changing business workflows; configure them with `LLM_PROVIDER` and `LLM_FALLBACK_PROVIDER`.
- Use an integration adapter for ReqRes; do not call the endpoint directly from workflow logic.
- Keep database models, API schemas, workflow state, and UI payloads separate.
- Keep immutable package assets (for example, the bundled public-holiday calendar) under
  `backend/app/resources/`; reserve `/app/data` for the Docker volume's runtime database and uploads.
- Add tests with each behaviour, not only at the end.
- Make small, meaningful commits. Each commit must pass the relevant tests.
- Update `README.md`, `docs/business-rules.md`, `docs/test-cases.md` and `PROMPT-INSTRUCTION.md` when behaviour, rules or runnable instructions change.
- Tests: backend `cd backend && uv run pytest -q` (offline; never reads `.env`), frontend `cd frontend && bun run lint && bun run typecheck && bun run test`, end-to-end `cd e2e && bun run test`. Live AI checks are separate opt-in scripts.
- Reset the fictional demo data with `./scripts/reset-demo.sh` (or `python -m app.cli reset-demo --yes`); change limits and approvers with the CLI in `docs/limits-and-routing.md`.
- Never read or print `.env` in agent work; the backend loads it through `Settings`.

## Multi-agent coordination

Each phase may use multiple agents for independent, bounded tasks. Parallelism is optional; prefer a single owner when a change crosses frontend, backend, database, and Docker boundaries.

1. Name one **phase integrator**. Only that agent may resolve cross-cutting changes, modify shared configuration, or declare the phase complete.
2. Give each contributing agent an explicit file or directory boundary, acceptance command, and short expected outcome. Typical parallel boundaries are `frontend/`, `backend/`, and `tests/` or `docs/`.
3. Do not assign two agents to edit the same file. In particular, assign only the phase integrator to `docker-compose.yml`, root README, `.env.example`, shared API contracts, database migrations, `AGENTS.md`, and `PROMPT-INSTRUCTION.md` unless the task explicitly transfers ownership.
4. Contributors must report changed files, commands run, results, assumptions, and any integration risk. They must not mark another agent's work complete.
5. After all bounded tasks return, the phase integrator reviews the combined diff, runs the phase acceptance commands, updates the truthful prompt log, and then starts the next phase.
6. Do not run commits, pushes, remote changes, destructive Git commands, live ReqRes writes, or use secrets unless Ken explicitly authorises that action.

Suggested task prompt:

```text
Phase: <number and name>
Role: <frontend | backend | tests | documentation>
File ownership: <exact paths>
Goal: <one bounded outcome>
Do not edit: <shared paths>
Verify: <commands>
Report: changed files, verification result, assumptions, and blockers.
```

## Definition of done

The repository must provide a reproducible setup guide, `.env.example`, unit tests, end-to-end coverage of the core employee-to-approval flow, role-denial and safe-failure cases, a demo-data reset command, an architecture diagram (`docs/architecture.md`) and troubleshooting guide (`docs/troubleshooting.md`), fictional-data screenshots (`docs/screenshots/`), clear commit history, and a presentation-ready live demo with fictional data and a visible AI processing trace.
