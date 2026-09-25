# Troubleshooting

Commands assume the repository root. In Docker Compose, replace `docker compose` with
`docker compose -f docker-compose.yml -f docker-compose.ollama.yml` if you run the local-AI file.
All data is fictional.

## Quick table

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `port is already allocated` or the page does not load on 9180 or 9181 | another program uses the port | `lsof -nP -iTCP:9180 -iTCP:9181 -sTCP:LISTEN`, stop it, or set `WEB_PORT` / `API_PORT` in `.env` (see below) |
| API answers `503` with "created before Phase 3" | the database file is from an older schema | `./scripts/reset-demo.sh` or `docker compose down -v` |
| Demo data is messy or you want a clean start | you played with it | `./scripts/reset-demo.sh` |
| Reply is "I couldn't reach the AI service just now" | the primary LLM failed and no fallback answered | check Ollama or Gemini below, then `docker compose logs -f api` |
| First reply after a pause takes about 30 s | Ollama is loading the model into memory | wait; later replies are fast (the model stays loaded for 30 minutes) |
| Gemini "quota or rate limit reached" (429) | free-tier quota of the Google project | use `LLM_PROVIDER=ollama`, or keep `LLM_FALLBACK_PROVIDER=ollama`; quota resets at midnight Pacific |
| Model "is not installed" | Ollama does not have the model | `ollama pull gemma4:latest` |
| Request shows "submission failed" with Retry | ReqRes unreachable, slow (10 s timeout) or refused | press Retry; see "ReqRes" below |
| Signed in, then sent back to the login page | cookie not stored or not sent (host mismatch, `Secure` over http) | see "Sign-in" below |
| `403 CSRF check failed` | Origin is not in `CORS_ORIGINS`, or the header is missing | see "Sign-in" below |
| Upload rejected | `413` over 5 MB, `415` wrong type, `422` too many files | see "Uploads" below |
| "no approver is configured for you" | Helen and Eva have none, by design | log in as Amy, Ben, Daniel or Cathy, or use `set-approvers` |
| The AI asks for the receipt date | you did not give one | intended: dates you never stated are never assumed |
| `invalid choice: 'reset-demo'` inside the container | the image is older than the command | `docker compose up --build -d` |

## Reset the demo data

```bash
./scripts/reset-demo.sh              # Docker stack: asks y/N, then resets the running api container
./scripts/reset-demo.sh --yes        # no question
./scripts/reset-demo.sh local        # without Docker, from backend/ with uv
COMPOSE_ARGS="-f docker-compose.yml -f docker-compose.ollama.yml" ./scripts/reset-demo.sh
```

This drops every table, reloads the fictional seed data (6 users, 20 requests, 34 holidays) and
deletes the uploaded files. The same thing without the script:

```bash
docker compose exec -T api python -m app.cli reset-demo --yes
cd backend && uv run python -m app.cli reset-demo --yes
```

`python -m app.cli seed --reset --yes` also works (it now clears the uploads too). `docker compose down -v`
deletes the whole volume (database and uploads); the next `up` recreates and reseeds it.

## Ports 9180 and 9181

- Find the owner: `lsof -nP -iTCP:9180 -iTCP:9181 -sTCP:LISTEN`.
- Change a port in `.env`: `WEB_PORT`, `API_PORT`. When the web port changes also set `CORS_ORIGINS`
  to the new web origin (for example `http://localhost:9190`), and when the API port changes set
  `NUXT_PUBLIC_API_BASE` (for example `http://localhost:9191`). Then `docker compose up -d`.
- A stale stack from an earlier run: `docker compose ps`, then `docker compose down`.

## Database "created before Phase 3"

The API stays up (`/health` works) and logs one error; every endpoint that needs the database
answers `503` with the same text. Confirm with `docker compose logs api | grep "before Phase 3"`.
The file predates the current `schema_version` and is deliberately not touched. Fix: reset it with
`./scripts/reset-demo.sh`, or `docker compose down -v && docker compose up --build`.

## Ollama (local AI)

- Is it up and does it have the model? `curl -s http://localhost:11434/api/tags`. Start with
  `ollama serve` (or the app), install with `ollama pull gemma4:latest`. `OLLAMA_MODEL` and
  `OLLAMA_VISION_MODEL` in `.env` choose other models.
- **First reply about 30 s**: the model loads on first use (the first call gets a 240 s allowance,
  and it then stays loaded for 30 minutes). A normal call times out after `OLLAMA_TIMEOUT_SECONDS`
  (default 90).
- **From Docker** the API uses `http://host.docker.internal:11434` (set in `docker-compose.yml`,
  overriding `OLLAMA_BASE_URL` from `.env`). Test it from inside:
  `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=5).status)"`.
- **Listening address**: Docker Desktop reaches an Ollama bound to `127.0.0.1`. On Linux (Docker
  Engine) the container arrives from the bridge network, so start Ollama with
  `OLLAMA_HOST=0.0.0.0:11434 ollama serve` (and firewall it if the machine is shared).
- Local-AI-only run: `docker compose -f docker-compose.yml -f docker-compose.ollama.yml up --build`.

## Gemini

- **429 "quota or rate limit reached"**: limits are per Google project, not per key, and the daily
  quota resets at midnight Pacific time. Switch with `LLM_PROVIDER=ollama`, or leave
  `LLM_FALLBACK_PROVIDER=ollama` (default in `.env.example`): the chat then switches by itself and
  skips Gemini for `LLM_FALLBACK_COOLDOWN_SECONDS` (300).
- **503 "high demand"**: transient; the provider retries once, then the fallback takes over.
- **Invalid key** ("rejected the API key or access"): fix `GEMINI_API_KEY` in `.env`, then
  `docker compose up -d`. With an empty key the provider fails on the first message, not at startup.
- **Model id** ("model not found or unsupported"): check `GEMINI_MODEL` (default `gemini-3.8-flash`)
  in Google AI Studio.
- Which provider answered is shown in the trace ("How I understood this"); errors are in
  `docker compose logs api | grep -i gemini`.

## ReqRes (the hosted mock API)

- A failed call is not an error page: the request is saved as `submission_failed`, the chat says so,
  and the card offers Retry. Nothing is retried automatically (a POST is not idempotent).
- Check reachability from the API: `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('https://reqres.in/api/users', timeout=8).status)"`
  (a `GET` only; a `urllib.error.HTTPError` such as 401 still proves the host is reachable, a timeout or name error means it is not).
- ReqRes has worked without a key so far. The adapter sends `x-api-key` only when `REQRES_API_KEY`
  is set; if ReqRes starts answering `401` or `403`, put a key in `.env` and run `docker compose up -d`.
- Offline demo only: `SUBMISSION_PROVIDER=fake` (never present it as the ReqRes integration).
- Live check (two real POSTs, opt-in): `cd backend && RUN_LIVE_REQRES=1 uv run python scripts/live_reqres_smoke.py`.

## Sign-in and cookies

- Use `http://localhost:9180` consistently. The session cookie is host-scoped: `localhost` and
  `127.0.0.1` are different hosts, so signing in on one and calling the API on the other fails.
  Keep `NUXT_PUBLIC_API_BASE` and the address bar on the same host name.
- `403 CSRF check failed`: the `Origin` of the page must be listed in `CORS_ORIGINS` (default
  `http://localhost:9180`). After changing the web port or host, update it and `docker compose up -d`.
- `AUTH_COOKIE_SECURE=true` (or `APP_ENV=production`) marks the cookie `Secure`; browsers drop it over
  plain http, so login "succeeds" and you are sent back. Set it to `false` for local http.
- "Session expired" after an API restart: with an empty `JWT_SECRET_KEY` a random secret is created
  per process. Set `JWT_SECRET_KEY` (`openssl rand -hex 32`) to keep logins across restarts. Tokens
  last `JWT_EXPIRE_MINUTES` (60).
- Clear the cookie for `localhost` in the browser if it points at an old secret.

## Uploads

- `413`: over `MAX_UPLOAD_MB` (5). `415`: not JPEG, PNG, WebP, HEIC/HEIF or PDF, or the bytes do not
  match the declared type (the real file signature is checked, not the name). `422`: empty file, more
  than 3 files in one message, or more than 10 staged in a conversation.
- Files are stored under `UPLOAD_DIR` (`/app/data/uploads` in Docker, on the `api-data` volume). The
  container runs as user `app` (uid 1000). A bind mount owned by root fails with a permission error;
  use the named volume, or `chown 1000:1000` the host directory.
- Lost files after `down -v`: expected, the volume is deleted. `reset-demo` deletes them on purpose.

## "No approver is configured"

Helen Yeung and Eva Cheung have no approver by design (they only approve), so they cannot file
requests. Everyone else can. To give someone an approver:

```bash
docker compose exec api python -m app.cli show-org
docker compose exec api python -m app.cli set-approvers --email helen.yeung@example.com \
    --leave-approver cathy.ng@example.com --claim-approver eva.cheung@example.com
```

Details: [limits-and-routing.md](limits-and-routing.md). Changes apply to new requests only.

## Docker basics

```bash
docker compose ps                    # api should be (healthy), web Up
docker compose logs -f api           # follow the API log (also: web)
docker compose up --build -d         # rebuild after code changes and start in the background
docker compose up -d                 # apply .env changes (recreates the containers)
docker compose restart api
docker compose down                  # stop, keep the data
docker compose down -v               # stop and DELETE the database and uploads
```

Code changes need `--build`; `.env` changes only need `up -d`. The `web` container waits for the
`api` health check, so a failing `api` also keeps the page down: read its log first.

## Running the tests

```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd frontend && bun run lint && bun run typecheck && bun run test
# end-to-end (Playwright, offline, own servers on 9280/9281, system Chrome)
cd e2e && bun install && bun run test
# opt-in live AI check (local Ollama)
cd backend && RUN_LIVE_LLM=1 uv run python scripts/live_llm_smoke.py --provider ollama
```

Backend tests are offline (fake LLM, temporary SQLite) and never read `.env`. The Playwright
end-to-end tests are offline too (fake LLM and fake submission adapter, reseeded before every test).
If one fails to start, check that ports 9280 and 9281 are free; without system Chrome run
`bunx playwright install chromium` and `E2E_BROWSER=chromium bun run test` (see `e2e/README.md`).
