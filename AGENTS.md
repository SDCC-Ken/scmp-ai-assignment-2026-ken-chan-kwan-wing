# SCMP Internal Operations AI Assistant

## Product goal

Build a local demonstration of an employee self-service application for the SCMP AI Engineer (Internal Automation) coding assignment. The application must route natural-language requests for Leave Application and Staff Claim, collect missing information, request confirmation, and submit to the supplied mock API.

This is a fictional PoC. Do not use, infer, upload, or commit real SCMP, employee, applicant, financial, or HR data.

## Required assignment scope

- Mock Google SSO entry flow with three seeded roles: `employee`, `hr_approver`, and `finance_approver`.
- One unified chat UI.
- Employee capabilities: create Leave Application and Staff Claim requests; view only their own requests.
- HR Approver capabilities: list, view, approve, and reject Leave requests only.
- Finance Approver capabilities: list, view, approve, and reject Claim requests only.
- Leave fields: `employee_email`, `leave_type`, `start_date`, and `end_date`.
- Claim fields: `employee_email`, `claim_type`, `amount`, and `receipt_date`.
- Ask focused follow-up questions for missing required fields.
- Display an API loading state; submit only after an explicit confirmation.
- Send Leave and Claim submissions to `POST https://reqres.in/api/users`. Wire format: leave `{email, leave_type, start_date, end_date}` (e.g. `"Annual"`), claim `{email, claim_type, amount, receipt_date}`; nothing else leaves the system.
- Keep a local audit trail for request creation, confirmation, mock submission, approval, and rejection.

## Selected stack

| Layer | Technology |
| --- | --- |
| Frontend | Nuxt 4, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12+, FastAPI, Pydantic |
| Agent orchestration | LangGraph |
| LLM | Google Gemini API, `gemini-3.8-flash`, `thinking_level=low` |
| Persistence | SQLite, SQLAlchemy |
| HTTP integration | httpx |
| Backend tests | pytest |
| End-to-end tests | Playwright |
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

## Architecture and safety boundaries

1. Gemini is used only for intent recognition, structured field extraction, and concise follow-up wording.
2. FastAPI and Pydantic own validation, role checks, state transitions, API submission, and approval actions.
3. The LLM must not directly approve, reject, write to the database, or call an integration API.
4. Every state-changing action requires a confirmation step. HR and Finance approvals require role validation in the backend, not only hidden frontend controls.
5. Return structured LLM output and validate it with Pydantic before changing conversation state.
6. Store only fictional seed data. Never commit `.env`, API keys, tokens, recordings containing secrets, or copied production data.
7. The application must handle LLM, database, and HTTP integration failures without crashing. A fake LLM provider is required for deterministic automated tests.

## Engineering conventions

- Keep frontend and backend independently runnable, with one documented Docker Compose command for the full application.
- Use a provider interface so Gemini can be replaced without changing business workflows.
- Use an integration adapter for ReqRes; do not call the endpoint directly from workflow logic.
- Keep database models, API schemas, workflow state, and UI payloads separate.
- Add tests with each behaviour, not only at the end.
- Make small, meaningful commits. Each commit must pass the relevant tests.
- Update `README.md` and `PROMPT-INSTRUCTION.md` when the development process or runnable instructions change.

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

The repository must provide a reproducible setup guide, `.env.example`, unit tests, end-to-end coverage of the core employee flow, clear commit history, and a presentation-ready live demo with fictional data and visible AI processing trace.
