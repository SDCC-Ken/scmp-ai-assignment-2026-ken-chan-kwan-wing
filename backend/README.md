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
| `app/services/` | DB-aware helpers: audit trail, polymorphic-reference checks, holidays |
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
| `GET /api/auth/me` (cookie or Bearer) | `{id, email, display_name, role}`; 401 `Invalid or expired token` with `WWW-Authenticate: Bearer` |
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

Seeded fictional users: `amy.lau@`, `ben.chow@`, `cathy.ng@` (employees), `daniel.wong@`
(HR approver), `eva.cheung@` (Finance approver), all at `example.com`.

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
