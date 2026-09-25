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
| `app/auth/` | JWT create/verify, `get_current_user`, `require_roles` |
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

## Auth (mock Google SSO + real JWT)

| Endpoint | Result |
| --- | --- |
| `GET /api/auth/mock-users` | active seed users (no `google_subject`) |
| `POST /api/auth/mock-google/login` `{"email": "..."}` | `{access_token, token_type, expires_in, user}`; 401 `Invalid credentials`; 403 `Account is inactive` |
| `GET /api/auth/me` (Bearer) | `{id, email, display_name, role}`; 401 with `WWW-Authenticate: Bearer` |
| `POST /api/auth/logout` (Bearer) | 204 and an `auth.logout` audit row (tokens are stateless; the client discards its token) |

Tokens are HS256 with `sub, email, role, iss, iat, exp, jti`. Only HS256 is accepted (`alg: none`
is rejected). The user, role and `is_active` are re-read from the database on every request, so
the token's role claim is informational only. `MOCK_SSO_ENABLED=false` turns the mock endpoints
into 404. With an empty `JWT_SECRET_KEY` a random per-process secret is used (a warning is
logged); `APP_ENV=production` requires a secret of at least 32 characters.

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
