# Backend (FastAPI)

Python 3.12 managed by `uv`. Run all commands from `backend/`. Backend port is 9181.
All data is fictional (`@example.com` users, made-up requests).

- Install: `uv sync`
- Test: `uv run pytest -q` (offline; never reads the repo-root `.env`)
- Lint: `uv run ruff check .` and `uv run ruff format --check .`
- Run: `uv run uvicorn app.main:app --port 9181` then `curl localhost:9181/health`
- Config: env vars from the repo-root `.env` (see `../.env.example`); the file may be absent.
- Secrets (`GEMINI_API_KEY`, `REQRES_API_KEY`, `JWT_SECRET_KEY`) are `SecretStr` and never printed.

## Layout

| Path | Responsibility |
| --- | --- |
| `app/db/` | SQLAlchemy models, engine/session (SQLite pragmas), column types |
| `app/domain/` | Pure rules: status state machine, roles, leave day maths (no DB/FastAPI) |
| `app/schemas/` | Pydantic API and draft-input models |
| `app/services/` | DB-aware helpers: audit trail, polymorphic-reference checks, holidays, approver routing, balances and budgets (`routing.py`, `balances.py`), CLI org changes (`org_admin.py`) |
| `app/auth/` | JWT create/verify, `get_current_user`, `require_roles`, CSRF middleware |
| `app/api/routes/` | HTTP routes, mounted under `/api` (`/health` stays at the root) |
| `app/seed.py`, `app/cli.py` | Fictional demo data and the `python -m app.cli` tools |

## Database

SQLite through SQLAlchemy 2.x. Tables are created with `create_all` (no migrations). Every
connection sets `foreign_keys=ON`, `busy_timeout=5000`, `synchronous=NORMAL` and, for file
databases, `journal_mode=WAL`. Timestamps are timezone-aware UTC. Money and day counts are
exact `Decimal` values stored as integers (never floats).

On startup the API creates the tables and, when `DB_AUTO_SEED=true` and the `users` table is
empty, loads the demo data. A startup failure is logged and does not stop the API.

**Phase 3 needs a one-time database reset.** Phase 3 removed a CHECK constraint and added the
organisation tables, which SQLite cannot do in place. New databases record `schema_version = 3`
in the `schema_meta` table. If the API finds an older database it does not touch it: it logs one
`ERROR` ("This database was created before Phase 3. Recreate it: docker compose down -v, or
`python -m app.cli seed --reset --yes`"), still boots (`/health` works), and every endpoint that
needs the database answers `503` with the same instruction in `detail`. The CLI commands print
the same message and exit with 1.

```bash
uv run python -m app.cli init-db
uv run python -m app.cli seed                 # idempotent; no-op if users exist
uv run python -m app.cli seed --reset --yes   # DROP all tables, rebuild, reseed
```

## Auth (mock Google SSO + real JWT in an httpOnly cookie)

| Endpoint | Result |
| --- | --- |
| `GET /api/auth/mock-users` | active seed users (no `google_subject`) |
| `POST /api/auth/mock-google/login` `{"email": "..."}` | `{expires_in, user}` plus `Set-Cookie`; 401 `Invalid credentials`; 403 `Account is inactive` |
| `GET /api/auth/me` (cookie or Bearer) | the user (see below); 401 `Invalid or expired token` with `WWW-Authenticate: Bearer` |
| `POST /api/auth/logout` | always 204 and a cookie-clearing `Set-Cookie`; an `auth.logout` audit row only when a valid user is signed in |

**Cookie.** Login sets `AUTH_COOKIE_NAME` (default `scmp_session`) to the JWT with
`HttpOnly; SameSite=Lax; Path=/; Max-Age=<expires_in>` and no `Domain` (host-only). `Secure` is
added when `AUTH_COOKIE_SECURE=true` or `APP_ENV=production`. Logout re-sends the same cookie
(same name, path and attributes) with `Max-Age=0` and an epoch `Expires`.

**Why the body has no token.** The browser (JavaScript, extensions, XSS, logs, devtools
storage) must never handle the JWT, so it is not returned in JSON; only the API and the browser
cookie jar see it.

**Bearer still accepted.** Every authenticated route reads the JWT from the cookie, and also
accepts `Authorization: Bearer <jwt>` for non-browser clients and tools (the header wins if both
are sent). To get a token for such a client, read it from the `Set-Cookie` header, e.g.
`curl -i -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' -d '{"email":"amy.lau@example.com"}' localhost:9181/api/auth/mock-google/login`.

**CSRF.** In addition to `SameSite=Lax`, every unsafe request (POST, PUT, PATCH, DELETE) under
`/api`, login included, must send `X-Requested-With: XMLHttpRequest`, and an `Origin` header,
when present, must be one of `CORS_ORIGINS`; otherwise 403 `{"detail": "CSRF check failed"}`
(see `app/auth/csrf.py`). GET/HEAD/OPTIONS are exempt, so CORS preflights work. CORS allows
`Authorization`, `Content-Type`, `Accept` and `X-Requested-With`, with credentials and the
explicit origin list (never `*`).

**Hosts.** Cookies are scoped to the host, not the port, so a cookie set by `localhost:9181` is
also sent by the browser for `localhost:9180` requests (same site, so `SameSite=Lax` allows the
`fetch(..., {credentials: "include"})` calls). If the frontend and API are on different hosts
(for example `app.example.com` and `api.example.com`), the cookie will not be shared: serve both
behind one same-origin reverse proxy (`/api` to the backend).

Tokens are HS256 with `sub, email, role, iss, iat, exp, jti`. Only HS256 is accepted (`alg: none`
is rejected). The user, role and `is_active` are re-read from the database on every request, so
the token's role claim is informational only and disabling a user or changing their role takes
effect immediately. There are no refresh tokens or server-side sessions: logout clears the cookie
and a token copied elsewhere simply expires at `exp`. `MOCK_SSO_ENABLED=false` turns the mock
endpoints into 404. With an empty `JWT_SECRET_KEY` a random per-process secret is used (a warning
is logged); `APP_ENV=production` requires a secret of at least 32 characters.

The user object (login, `/api/auth/me`, `/api/auth/mock-users`) is `{id, email, display_name,
role, department: {id, name} | null, job_title, can_request, approves}`. `can_request` is true
when at least one approver is configured for the user; `approves` is `"leave"` (HR approver),
`"claim"` (Finance approver) or `null`. `mock-users` lists employees, then HR approvers, then
the Finance approver, then by id.

Seeded fictional users (all `@example.com`): `amy.lau@` and `ben.chow@` (IT employees),
`cathy.ng@` (HR approver, HR Business Partner for IT), `daniel.wong@` (HR employee),
`helen.yeung@` (HR approver, HR Manager), `eva.cheung@` (Finance approver). Amy and Ben have Cathy
as leave approver, Cathy and Daniel have Helen; everybody has Eva as claim approver.

## Organisation: approvers, leave balances, claim limits (Phase 3)

Routing is **per user**: `users.leave_approver_user_id` and `users.claim_approver_user_id`
(nullable). The approver is copied onto the request as `approver_user_id` when it is created and
is the only person notified. A user with no approver for a request type cannot file it (the
assistant explains and saves nothing); a user with none at all (`can_request` false: Helen and
Eva in the seed) gets 403 from `GET /api/me/balances`, and from the chat unless they decide a queue
(Phase 3-D: `require_chat_access` = can file OR approves, so Helen and Eva can use the bell inbox).
`require_requester` (`app/auth`) implements the stricter requester gate; `require_roles(
UserRole.EMPLOYEE)` means "requester".

- `app/services/routing.py`: `resolve_approver(session, user, request_type)` returns the approver
  or an `ApproverProblem` (not configured, inactive, is the requester, wrong role).
- `app/services/balances.py`: `leave_balance`, `leave_balances_for_user`, `leave_balance_after`,
  `department_budget` (+ `budget_after`), `team_overlap`. Approved requests are deducted; pending
  ones are shown separately; limits are shown, never blocking.
- `GET /api/me/balances` returns `{"year": <current HK year>, "leave": [{leave_type,
  entitled_days, approved_days, pending_days, remaining_days}]}` for annual and sick leave.
- Change the data with `python -m app.cli show-org | set-entitlement | set-claim-limit |
  set-approvers` (in Docker: `docker compose exec api python -m app.cli ...`). Full guide:
  [`../docs/limits-and-routing.md`](../docs/limits-and-routing.md).

## Approvals and notifications (Phase 3)

The approver side of the workflow. Contract: [`../docs/phase3-approval-design.md`](../docs/phase3-approval-design.md)
section 5; every rule with its tests: [`../docs/business-rules.md`](../docs/business-rules.md) section 4c.
Code: `app/services/approvals.py`, `app/services/notifications.py`, routes
`app/api/routes/approvals.py` and `notifications.py`, schemas `app/schemas/approvals.py` and
`notifications.py`. Tests: `tests/approvals/` (offline, seeded in-memory database; the concurrency
test uses a temporary file database).

| Endpoint | Who | Result |
| --- | --- | --- |
| `GET /api/approvals` | `hr_approver` (leave) or `finance_approver` (claims) | `{"items": [...], "count": n}`: the caller's `pending_approval` requests, oldest submitted first, each with a summary and `flags` (`over_limit`, `team_overlap_count`, `has_attachments`). Others: `403` |
| `GET /api/approvals/{request_type}/{id}` | the assigned approver | fields, attachments (with URLs), `limits` (leave balance or department budget after this request), `team_overlap`, `warnings`. `404` (one body) when unknown, not assigned to you, of the other type, or not pending |
| `POST /api/approvals/{request_type}/{id}/decision` `{"decision": "approve" or "reject", "note": null or text}` | the assigned approver | `200 {"request_type", "id", "status", "reviewed_at"}`; `409` if it is no longer pending or another decision won; `422` for a bad decision or a note over 500 characters (the note is trimmed, empty becomes null, optional for both decisions) |
| `GET /api/notifications?limit=20` | any signed-in user | `{"items": [...], "unread_count": n}`, the caller's own, newest first (`limit` 1 to 50) |
| `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all` | the owner | `204`; someone else's or an unknown id is `404`; both are idempotent |

- **Per-user assignment.** An approver only ever sees requests whose `approver_user_id` is
  theirs, and never their own. Being a `hr_approver` is not enough (Cathy does not see Helen's
  staff). The decision goes through the domain rules (`can_decide`, the status machine).
- **Limits are shown, never blocking.** An over-balance leave or over-budget claim can be
  approved; the detail carries a sentence such as "Over the annual leave balance by 1.5 days. You
  decide.". The request itself is excluded from "approved" and "pending other" and reported as
  "requested". Money is a string with two decimals, days are numbers.
- **One winner.** The decision is one conditional `UPDATE ... WHERE status = 'pending_approval'`
  (the status change, the audit row and the notifications share one transaction, committed
  together). Under two simultaneous decisions one gets `200`, the other `409` and writes nothing.
- **Audit.** One `audit_events` row per decision (`request.approved` / `request.rejected`) with
  `note_present`, `over_limit`, a `snapshot` of the numbers the approver saw, `team_overlap_count`
  (leave) and `employee_id`. The note text is only on the request, never in the audit metadata.
- **Notifications.** A row stores only recipient, event type and request. `title`, `body` and
  `link` are composed when read from the row and the current request (plain text; no attachments,
  no e-mail addresses), so no payload column is needed: the approver's name and the note of a
  decision are read from `reviewed_by_user_id` / `reviewer_note` of the (final) request. `link` is
  `/approvals/{type}/{id}` only for the assigned approver while the request is pending, else
  `null`. Unknown or legacy event types get the neutral title "Update on leave request #12".
  A decision creates `request.approved` / `request.rejected` for the requester and marks the
  approver's own unread `request.submitted` / `request.updated` for that request as read.
- **Attachments of a decided request.** Unchanged `can_download` rule: the owner always; the
  assigned approver of the matching type while the request is `pending_approval`, `approved` or
  `rejected` (so a file stays downloadable after the decision, although the approver's detail
  page is then `404`); nobody else; not for `cancelled`, `draft` or `submission_failed`.
- **Requester side.** After a decision the requester's balance (`GET /api/me/balances`) and the
  department budget count the approved request only, the chat status card shows the reviewer note
  of a rejected request, and the chat refuses to edit or cancel a decided request.

## Chat: balances, approver awareness, stated dates (Phase 3-C)

- **Leave balance on the card**: annual and sick leave cards carry `info` lines (year of the start
  date; approved days deducted, pending shown but not deducted) and a `warning` line when over the
  balance. Shown, never blocking. New intent `check_balance` ("how many annual leave days do I have
  left?") answers with a `balance_card`; the backend writes every number (`app/chat/balance.py`).
- **Approver awareness**: a new leave or claim is refused up front (no draft, no card) when the user
  has no valid approver; the result message names the approver; status cards carry `approver_name`.
- **Stated dates only**: a leave date or receipt date that the user never wrote is dropped
  (`app/llm/dates.py`, used by the Ollama provider and by the graph merge), so "Claim HKD 180 for a
  taxi" asks for the receipt date. A scripted test double may set `trust_dates = True` to skip the
  merge guard. **HKD wording**: a bare `$`, `HK$`, `HKD$`, "dollars" and "HK dollars" are HKD
  (`app/llm/currency.py`); `USD`, `US$` and "US dollars" are still rejected.
- Rules: `../docs/business-rules.md` (L-13, L-14, C-06, C-11, section 4d); shapes:
  `../docs/chat-api-contract.md`. Live check: `RUN_LIVE_LLM=1 uv run python scripts/live_llm_smoke.py
  --provider ollama --only balance` (also `--only date`, `--only dollar`).

## Inbox: the bell opens a "handle it one by one" conversation (Phase 3-D)

- `POST /api/chat/inbox` (any user who can file requests or decides a queue) snapshots what needs
  the caller: pending approvals assigned to them (oldest first, same detail as the approvals screen)
  and their other unread notifications. Empty: `200 {"empty": true, "unread_count": N}` and no
  conversation. Otherwise it creates a NEW conversation "Items to handle (N)" with an intro and the
  first `inbox_card`; the queue and position live in `conversations.state_json` (no new table).
- Card buttons go through the existing `POST /api/chat/conversations/{id}/actions`: `approve` and
  `reject` (need `confirmed: true`, optional `note`), `skip`, `acknowledge`. Approve and reject call
  `services.approvals.decide` (the function behind the approvals endpoint; audit metadata gets
  `"via": "inbox"`); a card is claimed with a compare-and-swap first, so a double click has one
  winner. An item decided elsewhere becomes a `stale` card and the next one is shown.
- Chat access is now "can file requests OR decides a queue" (`require_chat_access`), so Helen and
  Eva can use the inbox; they still cannot file (no approver configured).
- Code: `app/chat/inbox.py`, `app/schemas/inbox.py`, state in `app/chat/state.py` (`InboxState`).
  Rules: `../docs/business-rules.md` (IN-01..IN-19); shapes: `../docs/chat-api-contract.md`;
  tests: `uv run pytest -q tests/inbox`.

## Public holidays

Leave working days skip Saturdays, Sundays and rows in `public_holidays`. The seed loads 2026 and
2027 from the bundled `app/data/hk_public_holidays_1823.ics` (snapshot of the official 1823.gov.hk
iCal, fetched 2026-09-25), with source `seed_2026`.

1823 publishes about three years ahead. Each year, once the next calendar appears:

```bash
uv run python -m app.cli import-holidays --year 2028
# or from a downloaded file
uv run python -m app.cli import-holidays --file path/to/en.ics --year 2028
# inside Docker Compose
docker compose exec api python -m app.cli import-holidays --year 2028
```

The command downloads `https://www.1823.gov.hk/common/ical/en.ics` (override with `--url`),
upserts by date (safe to re-run, source `1823_ics`) and prints inserted/updated counts. If a
requested year is not in the feed it exits non-zero with a message and changes nothing.

## Attachments

Employees can upload an image or a PDF to a conversation (a receipt, a sick note). The file is
stored on disk under `UPLOAD_DIR` (default `./data/uploads`, the Docker volume), never as a
blob in SQLite and never sent to ReqRes. Contract: `../docs/chat-api-contract.md`
("Attachments (Phase 2b)"). Code: `app/services/attachments.py`,
`app/api/routes/attachments.py`, table `attachments` (created by `create_all`, so an existing
database only gains a new table).

| Endpoint | Result |
| --- | --- |
| `POST /api/chat/conversations/{id}/attachments` (multipart field `file`, employee, CSRF header) | `201 {"attachment": {id, filename, content_type, size_bytes, url, created_at}}`; `413` too large, `415` unsupported or mismatching type, `422` empty / no field / more than 10 staged, `404` not your conversation, `403` wrong role |
| `POST /api/chat/conversations/{id}/messages` `{"content", "attachment_ids": [..]}` | as before; `content` may be empty when 1-3 files are sent; every id must be your own staged upload of this conversation (else `422`) |
| `GET /api/attachments/{id}` | the file, or `404` (same body for every refusal), `401` without a session |

- **Type is decided by the bytes**, not by the name or the client's content type: JPEG, PNG,
  WEBP, HEIC/HEIF (ISO-BMFF `ftyp` brand) and PDF (`%PDF-` in the first KB). A declared type that
  contradicts the bytes is `415`. Everything else (SVG, HTML, EXE, ZIP, GIF, AVIF) is refused.
- **Size:** `MAX_UPLOAD_MB` (default 5) per file, `MAX_ATTACHMENTS_PER_MESSAGE` (default 3). The
  body is streamed with `python-multipart` and reading stops at the limit (a declared
  `Content-Length` over the limit is refused before reading anything).
- **Storage:** `UPLOAD_DIR/<yyyy>/<mm>/<uuid4hex>.<ext>` with the extension taken from the
  sniffed type; directories `0700`, files `0600`; written to `UPLOAD_DIR/.incoming/` first and
  moved with `os.replace`; removed again if the database insert fails. The user's file name is
  kept only for display (path, control and bidi characters removed, at most 120 characters).
- **Lifecycle:** *staged* (uploaded, `message_id` NULL, at most 10 per conversation) -> attached
  to the user message that lists it -> linked to the request (`request_type` + `request_id`)
  when the card is confirmed. `ConversationState.attachment_ids` (filled by the document-reading
  step) says which files belong to the draft; `CardActions` calls `link_to_request` on create
  and on update. `cleanup_staged_uploads(session, upload_dir)` deletes staged files older than
  24 hours (a function only; nothing schedules it).
- **Who can download:** the owner always. An approver only when the file is linked to a request
  that has been submitted (`pending_approval`, `approved` or `rejected`), their role reviews
  that type (HR: leave, Finance: claim) and it is assigned to them. Everyone else gets `404`.
- **Response headers:** `Content-Type` from the stored type, `Content-Disposition: inline` with an
  ASCII `filename` and a percent-encoded `filename*`, `X-Content-Type-Options: nosniff`,
  `Cache-Control: private, no-store`, `Content-Security-Policy: sandbox`, plus the normal CORS
  headers (explicit origin, credentials).
- **Turn input:** a message with files runs the graph with `ChatTurnDeps`
  (`app/chat/turn_input.py`): `TurnDeps` plus `attachments: list[AttachmentInput]` (id, filename,
  content type, size and the bytes). The graph reads them (see "Documents" below); a message
  with files and no text is valid.
- Tests: `tests/attachments/` (offline; each test uses its own temporary `UPLOAD_DIR`).

## Documents

A message with files runs `provider.analyse(text, context, attachments)` (an empty text becomes
"The user attached a document with no message."). The provider only READS the files
(`AgentTurn.documents`, one `DocumentExtraction` each); the backend decides the rest in the
graph node `documents` (`app/agent/graph.py`) and the merge helpers in `app/chat/documents.py`:

- A readable sick note fills a **sick leave** (`rest_start_date`, `rest_end_date`); a readable
  receipt fills a **claim** (amount, currency as printed, receipt date, suggested claim type).
  `days_advised` never becomes an end date: the last day is asked.
- **Typed values win**: what the user typed in the message or earlier in the draft is never
  overwritten; a different document value becomes a card warning naming the field and both
  values. Fields read from a document are remembered in `ConversationState.sources` and tagged
  `source: "document"` on the card. (In the update flow the stored request values are not
  "typed", so a document may change them; the card shows old and new and still needs Confirm.)
- **Missing or unreadable** values get a deterministic question naming the file ("I could not
  read the receipt date on receipt.png. What date is on the receipt?"), one at a time. A file
  that cannot be read and comes with no other information: type the details or upload a clearer
  file. A receipt during a leave draft (or the reverse) asks which one is meant and keeps the
  document in `ConversationState.held_document` until answered; the two are never mixed.
- A different name on the document is a card warning ("The name on the document (...) differs
  from your name; your approver will see this."), never a block.
- The draft's files are `ConversationState.attachment_ids` (accumulate, at most 3 per request,
  cleared by discard / supersede / a new draft) and are shown as `card.attachments`. On Confirm
  they are linked to the created or updated request (`link_to_request`). The provider's
  extraction is stored in `attachments.extraction_json` (only `DocumentExtraction` fields).
- Text inside a document is data: nothing in it can approve, submit, change the employee or
  skip validation. The normal validation and the explicit Confirm always apply.
- Trace: a `documents` step ("Read 1 document: receipt (readable)", duration, and the answering
  provider when the provider exposes `last_served_by`); no names, values or file names. With
  documents the model's rationale is left out of the trace.
- Tests: `tests/chat/test_documents.py` (scripted provider plus the real `FakeLLMProvider` on
  `samples/*.fake.pdf`, all offline).
