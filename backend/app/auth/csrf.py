"""CSRF defence for cookie-based auth (second layer on top of ``SameSite=Lax``).

Every unsafe request (POST, PUT, PATCH, DELETE) under ``/api`` must carry
``X-Requested-With: XMLHttpRequest`` (a custom header cannot be sent cross-origin without a
CORS preflight, which only allowed origins pass) and, when an ``Origin`` header is present,
it must be one of the configured CORS origins. Safe methods (GET, HEAD, OPTIONS) are exempt,
so CORS preflights are answered by the CORS middleware as usual.
"""

from collections.abc import Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "xmlhttprequest"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
API_PREFIX = "/api"


def _is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


class CSRFMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in UNSAFE_METHODS
            or not _is_api_path(scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        origin = headers.get("origin")
        header_ok = headers.get(CSRF_HEADER, "").strip().lower() == CSRF_HEADER_VALUE
        origin_ok = origin is None or origin in self.allowed_origins
        if header_ok and origin_ok:
            await self.app(scope, receive, send)
            return
        response = JSONResponse({"detail": "CSRF check failed"}, status_code=403)
        await response(scope, receive, send)
