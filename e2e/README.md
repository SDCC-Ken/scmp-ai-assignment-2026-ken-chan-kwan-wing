# End-to-end tests (Playwright)

Browser tests of the real stack: the built Nuxt frontend talking to the FastAPI backend, driven
through Google Chrome. **Fully offline and deterministic**: the backend runs with the fake LLM
(`LLM_PROVIDER=fake`) and the fake submission adapter (`SUBMISSION_PROVIDER=fake`), every API key is
forced empty, and the only network traffic is between `localhost` ports. No Gemini, no Ollama, no
ReqRes, and nothing from the repo `.env` can take effect (explicit variables override it).

## What is covered

| Spec | Scenario |
| --- | --- |
| `tests/employee-to-approval.spec.ts` | Amy Lau signs in (mock Google) and asks for annual leave in the chat; the confirmation card shows type, dates, working days and the balance line; Submit gives a "Pending approval" result that says it used the offline fake adapter, not ReqRes. Cathy Ng (assigned HR approver) opens Approvals, picks the new request by its dates, sees the limits panel and team-overlap section, adds a note, approves in the confirmation dialog, and the item leaves her list. Amy asks "what is the status of my requests?" and the status card shows Approved with the note. The audit table holds exactly one `request.approved` event for it. |
| `tests/role-denial.spec.ts` | Finance approver Eva cannot open or decide an assigned leave request; HR approver Cathy cannot open or decide a claim (UI shows "This request is no longer available" with no details; API 404 for GET and decision; the request stays pending, no approve/reject audit event; each queue holds only its own type). Employee Amy is bounced from `/approvals` and gets 403 from the API; HR manager Helen gets 404 for Amy's leave (not assigned to her). |
| `tests/failure-retry.spec.ts` | Network failure on send (request aborted): inline error, typed text kept, Retry recovers, no uncaught page errors. HTTP 500 on send: same, server text never shown. LLM outage (test-only `[[llm-down]]` trigger of the fake LLM): warning banner and assistant message, earlier draft card still open and later submittable, composer usable, next message works. |

The bell inbox is not covered yet: `employee-to-approval.spec.ts` has a `TODO(bell-inbox)` marker where those steps belong.

## Run

```bash
cd e2e
bun install
bun run test            # headless
bun run test:headed     # watch the browser
bun run test:ui         # Playwright UI mode (pick, replay and time-travel tests)
bun run report          # open the HTML report of the last run
bunx tsc --noEmit       # typecheck the test code
```

Prerequisites: Bun, `uv` with the backend environment (`cd backend && uv sync`), `frontend/node_modules`
(`cd frontend && bun install`), `rsync` (present on macOS) and Google Chrome. Playwright starts and stops
both servers itself:

| Server | Port | Notes |
| --- | --- | --- |
| Web (production build of `frontend/`) | **9280** | `node .output/server/index.mjs` |
| API (`uvicorn app.main:app`) | **9281** | fake LLM, fake submission adapter, SQLite in `e2e/.tmp/` |

The ports differ from Docker (9180/9181) and other dev servers (9190/9191/9199), so the suite can run
next to them. `localhost` is used everywhere so the host-scoped session cookie is shared by both ports.

### Frontend build

The first run builds the frontend (about a minute). The build happens in a private copy, `e2e/.build/web`
(rsync of `frontend/`), so it never touches `frontend/.output`. Later runs reuse it and rebuild only when
a frontend source file changed. Force a rebuild with `E2E_REBUILD=1 bun run test`.

## How the data is reset

* At the start of a run the API launcher (`support/start-api.mjs`) deletes `e2e/.tmp/e2e.db*` and
  `e2e/.tmp/uploads`. (Playwright starts web servers before its global setup, so this is done in the launcher.)
* Before **every test** an automatic fixture (`support/fixtures.ts`) runs
  `uv run python -m app.cli seed --reset --yes` against the same database, so each test starts from the
  known fictional seed and tests are independent of order. The running API copes with the tables being recreated.
* Tests look ids up through the API (as an allowed user) and compute dates in the test (`support/dates.ts`:
  Tuesday-Wednesday ranges, six or more weeks ahead, never a Hong Kong public holiday and never clashing with the seed).
* The only direct database access is a read-only `sqlite3 -readonly` query for the audit events (`support/db.ts`).

## Reports and traces

Reports go to `e2e/playwright-report` (HTML) and `e2e/test-results` (screenshots, traces of failed tests);
both are git-ignored. `bun run report` opens the report. Open a trace with
`bunx playwright show-trace test-results/<test-folder>/trace.zip`. Traces are kept only for failures
(`trace: retain-on-failure`). Server logs (`[api]`, `[web]`) are printed in the console output of the run.

## Troubleshooting

* **Port busy** ("Port 9280/9281 (...) is already in use"): something already listens there.
  Find it with `lsof -iTCP:9280 -iTCP:9281 -sTCP:LISTEN` and stop it. The suite never reuses existing servers.
* **Chrome missing** ("Chromium distribution 'chrome' is not found"): install Google Chrome, or use Playwright's
  own Chromium: `bunx playwright install chromium`, then run `E2E_BROWSER=chromium bun run test`.
* **Stale build** (the UI does not match the source): `E2E_REBUILD=1 bun run test`, or delete `e2e/.build`.
* **Build fails**: run `cd frontend && bun install`, then try again; the error is printed with the `[web]` prefix.
* **`uv` errors**: run `cd backend && uv sync` once.
* **A test fails after a schema change**: the seed is recreated for every test, so a failure is real; open the
  trace of the failed test.
