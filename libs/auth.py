"""Авторизация панели: страница входа с сессионной cookie и Basic Auth для скриптов.

Браузер входит через /login и получает подписанную HttpOnly-cookie. Скрипты и
интеграции (curl, requests) по-прежнему могут слать заголовок Basic Auth. От
браузеров (запросы с заголовком Sec-Fetch-Mode) Basic не принимается: иначе
закэшированный браузером логин делал бы кнопку «Выйти» бесполезной.
"""

import base64
import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import quote

from fastapi import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from libs.config import settings


SESSION_COOKIE = "aibox_session"
SESSION_TTL_SECONDS = 12 * 3600
REMEMBER_TTL_SECONDS = 30 * 24 * 3600

LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 300

_PUBLIC_PATHS = {"/login", "/logout", "/health", "/favicon.ico"}
_PUBLIC_PREFIXES = ("/static/",)

_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _same(a: str, b: str) -> bool:
    # compare_digest на str принимает только ASCII; пароль может быть любым.
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def check_credentials(username: str, password: str) -> bool:
    user_ok = _same(username or "", settings.ADMIN_USER)
    pass_ok = _same(password or "", settings.ADMIN_PASS)
    return user_ok and pass_ok


def _is_valid_basic_auth(header: str | None) -> bool:
    if not header or not header.startswith("Basic "):
        return False

    try:
        raw = base64.b64decode(header.removeprefix("Basic ").strip()).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception:
        return False

    return check_credentials(username, password)


def _session_key() -> bytes:
    # Смена логина или пароля администратора делает старые сессии недействительными.
    secret = settings.SESSION_SECRET or settings.ENCRYPTION_KEY
    material = f"aibox-session-v1|{secret}|{settings.ADMIN_USER}|{settings.ADMIN_PASS}"
    return hashlib.sha256(material.encode("utf-8")).digest()


def _sign(payload: str) -> str:
    return hmac.new(_session_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token(username: str, ttl_seconds: int, now: float | None = None) -> str:
    expires = int((now or time.time()) + ttl_seconds)
    user = base64.urlsafe_b64encode(username.encode("utf-8")).decode("ascii").rstrip("=")
    payload = f"{user}.{expires}"
    return f"{payload}.{_sign(payload)}"


def read_session(token: str | None, now: float | None = None) -> str | None:
    """Имя пользователя из действительной cookie или None."""
    if not token:
        return None
    try:
        user, expires, signature = token.split(".")
        payload = f"{user}.{expires}"
        if not secrets.compare_digest(signature, _sign(payload)):
            return None
        if int(expires) < (now or time.time()):
            return None
        username = base64.urlsafe_b64decode(user + "=" * (-len(user) % 4)).decode("utf-8")
    except Exception:
        return None
    return username if _same(username, settings.ADMIN_USER) else None


def safe_next(value: str | None) -> str:
    """Куда вернуть после входа: только локальный путь этого сервера."""
    if not value or not value.startswith("/") or value.startswith("//") or value.startswith("/\\"):
        return "/"
    if value.split("?", 1)[0] in ("/login", "/logout"):
        return "/"
    return value


def login_lockout_remaining(client: str, now: float | None = None) -> int:
    now = now or time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(client, []) if now - t < LOGIN_LOCKOUT_SECONDS]
        _failures[client] = recent
        if len(recent) < LOGIN_MAX_FAILURES:
            return 0
        return max(1, int(LOGIN_LOCKOUT_SECONDS - (now - recent[0])))


def register_login_failure(client: str, now: float | None = None) -> None:
    with _failures_lock:
        _failures.setdefault(client, []).append(now or time.time())


def reset_login_failures(client: str) -> None:
    with _failures_lock:
        _failures.pop(client, None)


def _is_browser(request: Request) -> bool:
    return "sec-fetch-mode" in request.headers


def _wants_page(request: Request) -> bool:
    path = request.url.path
    return (
        request.method in ("GET", "HEAD")
        and not path.startswith(("/api/", "/media/"))
        and "text/html" in request.headers.get("accept", "")
    )


async def auth_middleware(request: Request, call_next):
    request.state.user = None
    if not settings.AUTH_ENABLED:
        return await call_next(request)

    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)

    user = read_session(request.cookies.get(SESSION_COOKIE))
    if user is None and not _is_browser(request) and _is_valid_basic_auth(request.headers.get("Authorization")):
        user = settings.ADMIN_USER
    if user is not None:
        request.state.user = user
        return await call_next(request)

    if _wants_page(request):
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)

    # Браузеру не шлём WWW-Authenticate, чтобы не всплывало системное окно Basic Auth:
    # интерфейс сам переведёт на страницу входа по ответу 401.
    headers = {} if _is_browser(request) else {"WWW-Authenticate": 'Basic realm="Camera Detector"'}
    return JSONResponse({"detail": "Требуется вход в систему"}, status_code=401, headers=headers)


def set_session_cookie(response: Response, request: Request, username: str, remember: bool) -> None:
    ttl = REMEMBER_TTL_SECONDS if remember else SESSION_TTL_SECONDS
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(username, ttl),
        max_age=ttl if remember else None,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
