import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.auth.csrf import CSRFMiddleware
from app.auth.tokens import resolve_jwt_secret
from app.config import Settings, get_settings
from app.db.session import Database
from app.integrations.base import SubmissionAdapter
from app.llm.base import LLMProvider
from app.seed import seed_demo_data

logger = logging.getLogger(__name__)


def startup_database(database: Database, settings: Settings) -> None:
    """Create tables and (optionally) seed. Failures are logged, never raised."""
    try:
        schema_error = database.init_db()
    except Exception:
        logger.exception("Database initialisation failed; the API will start without it")
        return
    if schema_error:
        return  # a pre-Phase-3 file: already logged; requests get a 503 with the instruction
    if not settings.db_auto_seed:
        return
    try:
        with database.session_factory() as session:
            result = seed_demo_data(session)
        if result.seeded:
            logger.info("Seeded fictional demo data")
    except Exception:
        logger.exception("Demo data seeding failed; continuing without it")


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    llm_provider: LLMProvider | None = None,
    submission_adapter: SubmissionAdapter | None = None,
) -> FastAPI:
    """Build the app. Providers default to the configured ones (built lazily on first use, see
    ``app.api.deps``); tests pass doubles or use ``dependency_overrides``."""
    settings = settings or get_settings()
    jwt_secret = resolve_jwt_secret(settings)  # raises in production without a strong secret
    database = database or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        startup_database(database, settings)
        yield
        database.dispose()

    app = FastAPI(title="SCMP Internal Operations AI Assistant (PoC)", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.jwt_secret = jwt_secret
    app.state.llm_provider = llm_provider
    app.state.submission_adapter = submission_adapter
    app.state.provider_lock = threading.Lock()
    # Middleware added last is outermost: CORS wraps CSRF, so a 403 "CSRF check failed" from an
    # allowed origin still carries the CORS headers and preflights never reach the CSRF check.
    app.add_middleware(CSRFMiddleware, allowed_origins=list(settings.cors_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
