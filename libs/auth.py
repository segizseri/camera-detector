import base64
import secrets

from fastapi import Request
from starlette.responses import Response

from libs.config import settings


_EXEMPT_PREFIXES = (
    "/static",
    "/favicon.ico",
    "/health",
)


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Camera Detector"'},
        content="Authentication required",
    )


def _is_valid_basic_auth(header: str | None) -> bool:
    if not header or not header.startswith("Basic "):
        return False

    try:
        raw = base64.b64decode(header.removeprefix("Basic ").strip()).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception:
        return False

    return secrets.compare_digest(username, settings.ADMIN_USER) and secrets.compare_digest(
        password, settings.ADMIN_PASS
    )


async def basic_auth_middleware(request: Request, call_next):
    if not settings.AUTH_ENABLED:
        return await call_next(request)

    if any(request.url.path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
        return await call_next(request)

    if not _is_valid_basic_auth(request.headers.get("Authorization")):
        return _unauthorized()

    return await call_next(request)
