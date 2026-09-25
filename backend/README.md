# Backend (FastAPI)

Python 3.12 managed by `uv`. Run all commands from `backend/`. Backend port is 9181.

- Install: `uv sync`
- Test: `uv run pytest -q`
- Lint: `uv run ruff check .` and `uv run ruff format --check .`
- Run: `uv run uvicorn app.main:app --port 9181` then `curl localhost:9181/health`
- Config: env vars from the repo-root `.env` (see `../.env.example`); the file may be absent.
- Secrets (`GEMINI_API_KEY`, `REQRES_API_KEY`) are `SecretStr` and never printed.
