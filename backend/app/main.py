import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.auth.tokens import resolve_jwt_secret
from app.config import Settings, get_settings
from app.db.session import Database
from app.seed import seed_demo_data

logger = logging.getLogger(__name__)


def startup_database(database: Database, settings: Settings) -> None:
    """Create tables and (optionally) seed. Failures are logged, never raised."""
    try:
        database.init_db()
    except Exception:
        logger.exception("Database initialisation failed; the API will start without it")
        return
    if not settings.db_auto_seed:
        return
    try:
        with database.session_factory() as session:
            result = seed_demo_data(session)
        if result.seeded:
            logger.info("Seeded fictional demo data")
    except Exception:
        logger.exception("Demo data seeding failed; continuing without it")


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
