"""Smoke-тесты веб-интерфейса: страницы, общий layout, локальные ресурсы."""

import re
from pathlib import Path

import pytest

from scripts.export_ui_catalog import OUTPUT as CATALOG_JS, build_ui_catalog, render

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "apps" / "api" / "templates"
STATIC = ROOT / "apps" / "api" / "static"

PAGES = [
    "/",
    "/cameras",
    "/cameras/test-cam-01",
    "/events-page",
    "/detection-test",
    "/visitors",
    "/visitors/some-visitor",
    "/reports",
    "/reports/passengers",
    "/buses",
    "/nvr",
    "/ai",
    "/finetune",
    "/integrations/webhooks",
    "/settings",
]

STATIC_ASSETS = [
    "/static/styles.css",
    "/static/icons.svg",
    "/static/js/app.js",
    "/static/js/detector-catalog.js",
    "/static/vendor/hls/hls.light.min.js",
    "/static/favicon.png",
]


@pytest.mark.parametrize("path", PAGES)
def test_page_renders_with_shared_layout(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert '<html lang="ru"' in html
    assert 'id="app-sidebar"' in html
    assert 'id="toast-region"' in html
    assert 'id="confirm-dialog"' in html
    assert "/static/js/app.js" in html


@pytest.mark.parametrize("path", PAGES)
def test_page_marks_current_section_in_navigation(client, path):
    html = client.get(path).text

    assert html.count('aria-current="page"') >= 1


@pytest.mark.parametrize("asset", STATIC_ASSETS)
def test_static_asset_is_served(client, asset):
    response = client.get(asset)

    assert response.status_code == 200
    assert response.content


def test_templates_do_not_load_external_resources():
    pattern = re.compile(r"""<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)=["'](?:https?:)?//""", re.I)
    offenders = [
        path.name
        for path in TEMPLATES.glob("*.html")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"Внешние ресурсы в шаблонах: {offenders}"


def test_no_native_alert_or_confirm_dialogs():
    pattern = re.compile(r"(?<![\w.])(?:window\.)?(?:alert|confirm)\(")
    sources = list(TEMPLATES.glob("*.html"))
    offenders = [path.name for path in sources if pattern.search(path.read_text(encoding="utf-8"))]

    assert offenders == [], f"alert()/confirm() вместо UI.toast/UI.confirm: {offenders}"


def test_referenced_icons_exist_in_sprite():
    sprite = set(re.findall(r'id="i-([a-z0-9-]+)"', (STATIC / "icons.svg").read_text(encoding="utf-8")))
    sources = list(TEMPLATES.glob("*.html")) + [STATIC / "js" / "app.js"]
    used = set()
    for path in sources:
        text = path.read_text(encoding="utf-8")
        used.update(re.findall(r"""icon\(\s*["']([a-z0-9-]+)["']""", text))
        used.update(re.findall(r"""iconName:\s*'([a-z0-9-]+)'""", text))

    assert used, "иконки не найдены — проверьте регулярные выражения теста"
    assert sorted(used - sprite) == []


def test_ui_detector_catalog_is_up_to_date():
    assert CATALOG_JS.read_text(encoding="utf-8") == render(build_ui_catalog()), (
        "apps/api/static/js/detector-catalog.js устарел: запустите python scripts/export_ui_catalog.py"
    )


def test_ui_catalog_matches_engine_catalog():
    from detector_core.contract.catalog import BUILTIN_CATALOG

    ui = build_ui_catalog()
    assert [d["id"] for d in ui["detectors"]] == [d.id for d in BUILTIN_CATALOG]
    assert all(d["legacy_flag"].startswith("detect_") for d in ui["detectors"])
    # Подсчёт пассажиров — модуль приложения, в каталог детекторов он не входит
    assert "detect_passengers" not in {d["legacy_flag"] for d in ui["detectors"]}


def test_detection_test_page_keeps_api_endpoints(client):
    html = client.get("/detection-test").text

    assert "Проверка детекций на видео" in html
    assert "/api/detection-tests/youtube" in html
    assert "/api/detection-tests/upload" in html
