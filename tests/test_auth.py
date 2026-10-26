"""Авторизация: страница входа, сессионная cookie, Basic Auth для скриптов."""

import base64

import pytest

from libs import auth
from libs.config import settings

BROWSER = {"Sec-Fetch-Mode": "navigate", "Accept": "text/html,application/xhtml+xml"}
BROWSER_FETCH = {"Sec-Fetch-Mode": "cors", "Accept": "*/*"}


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "пароль-1")
    auth._failures.clear()
    yield
    auth._failures.clear()


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _login(client, password="пароль-1", **extra):
    data = {"username": "admin", "password": password, "next": "/cameras", **extra}
    return client.post("/login", data=data, headers=BROWSER, follow_redirects=False)


def test_page_redirects_browser_to_login(client, auth_on):
    response = client.get("/cameras?x=1", headers=BROWSER, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fcameras%3Fx%3D1"


def test_api_without_auth_challenges_scripts_but_not_browsers(client, auth_on):
    script = client.get("/api/cameras/")
    browser = client.get("/api/cameras/", headers=BROWSER_FETCH)

    assert script.status_code == 401
    assert script.headers["www-authenticate"].startswith("Basic")
    assert browser.status_code == 401
    assert "www-authenticate" not in browser.headers
    assert client.get("/media/snapshots/x.jpg").status_code == 401


def test_public_paths_stay_open(client, auth_on):
    for path in ("/login", "/health", "/static/styles.css", "/static/js/app.js", "/favicon.ico"):
        assert client.get(path, headers=BROWSER).status_code == 200, path


def test_basic_auth_still_works_for_scripts(client, auth_on):
    assert client.get("/api/cameras/", headers=_basic("admin", "пароль-1")).status_code == 200
    assert client.get("/api/cameras/", headers=_basic("admin", "wrong")).status_code == 401
    # Браузер с закэшированным Basic-логином должен проходить через страницу входа
    assert client.get("/", headers={**BROWSER, **_basic("admin", "пароль-1")}, follow_redirects=False).status_code == 303


def test_login_page_renders_form(client, auth_on):
    response = client.get("/login?next=/events-page", headers=BROWSER)

    assert response.status_code == 200
    assert 'action="/login"' in response.text
    assert 'name="next" value="/events-page"' in response.text
    assert 'autocomplete="current-password"' in response.text


def test_login_sets_session_cookie_and_grants_access(client, auth_on):
    response = _login(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/cameras"
    cookie = response.headers["set-cookie"]
    assert auth.SESSION_COOKIE in cookie
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Max-Age" not in cookie  # без «Запомнить меня» — до закрытия браузера

    page = client.get("/cameras", headers=BROWSER)
    assert page.status_code == 200
    assert 'action="/logout"' in page.text
    assert client.get("/api/cameras/", headers=BROWSER_FETCH).status_code == 200


def test_remember_me_sets_long_lived_cookie(client, auth_on):
    response = _login(client, remember="on")

    assert f"Max-Age={auth.REMEMBER_TTL_SECONDS}" in response.headers["set-cookie"]


def test_wrong_password_shows_error(client, auth_on):
    response = _login(client, password="nope")

    assert response.status_code == 401
    assert "Неверный логин или пароль" in response.text
    assert auth.SESSION_COOKIE not in response.headers.get("set-cookie", "")


def test_login_is_throttled_after_repeated_failures(client, auth_on, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("apps.api.main.asyncio.sleep", no_sleep)
    for _ in range(auth.LOGIN_MAX_FAILURES):
        assert _login(client, password="nope").status_code == 401

    blocked = _login(client)
    assert blocked.status_code == 429
    assert "Слишком много" in blocked.text


def test_logout_clears_session(client, auth_on):
    _login(client)
    response = client.post("/logout", headers=BROWSER, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert client.get("/", headers=BROWSER, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("target", ["//evil.example/", "https://evil.example/", "/\\evil.example", "javascript:alert(1)", "/login"])
def test_next_only_allows_local_paths(client, auth_on, target):
    response = _login(client, next=target)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_tampered_or_expired_session_is_rejected(auth_on):
    token = auth.create_session_token("admin", 60)
    assert auth.read_session(token) == "admin"

    user, expires, signature = token.split(".")
    assert auth.read_session(f"{user}.{int(expires) + 3600}.{signature}") is None
    assert auth.read_session(auth.create_session_token("admin", -1)) is None
    assert auth.read_session(auth.create_session_token("someone", 60)) is None
    assert auth.read_session("garbage") is None


def test_password_change_invalidates_sessions(auth_on, monkeypatch):
    token = auth.create_session_token("admin", 60)
    monkeypatch.setattr(settings, "ADMIN_PASS", "new-password")

    assert auth.read_session(token) is None


def test_login_page_redirects_when_auth_disabled(client):
    response = client.get("/login?next=/buses", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/buses"
