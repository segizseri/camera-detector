"""Снимок каталога детекторов для веб-интерфейса.

API-контейнер не монтирует detector_core, поэтому UI получает каталог как
статический файл apps/api/static/js/detector-catalog.js. Файл генерируется
из detector_core/contract/catalog.py и колонок legacy-адаптера:

    python scripts/export_ui_catalog.py

tests/test_ui_pages.py падает, если снимок устарел.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector_core.contract.catalog import BUILTIN_CATALOG  # noqa: E402
from detector_core.contract.ids import CONTRACT_VERSION  # noqa: E402
from detector_core.legacy import (  # noqa: E402
    LEGACY_BATCH_KEY_TO_DETECTOR,
    LEGACY_FLAG_TO_DETECTOR,
    LEGACY_ZONE_COLUMNS,
)

OUTPUT = ROOT / "apps" / "api" / "static" / "js" / "detector-catalog.js"

ZONE_TITLES = {
    "cash_drawer": "Зона кассы",
    "display": "Зона витрины",
}


def _invert(mapping: dict[str, str]) -> dict[str, str]:
    return {detector_id: key for key, detector_id in mapping.items()}


def build_ui_catalog() -> dict:
    flag_by_detector = _invert(LEGACY_FLAG_TO_DETECTOR)
    batch_key_by_detector = _invert(LEGACY_BATCH_KEY_TO_DETECTOR)
    column_by_zone_kind = {kind.value: column for column, (kind, _zone_id) in LEGACY_ZONE_COLUMNS.items()}

    detectors = []
    for info in BUILTIN_CATALOG:
        requirements = info.requirements
        detectors.append(
            {
                "id": info.id,
                "title": info.title,
                "description": info.description,
                "maturity": info.maturity.value,
                "event_type": info.event_type,
                "legacy_event_type": info.legacy_event_type,
                "legacy_flag": flag_by_detector[info.id],
                "legacy_batch_key": batch_key_by_detector[info.id],
                "min_fps": requirements.min_fps,
                "recommended_fps": requirements.recommended_fps,
                "zones": [
                    {
                        "kind": zone.kind.value,
                        "title": ZONE_TITLES.get(zone.kind.value, zone.kind.value),
                        "description": zone.description,
                        "legacy_column": column_by_zone_kind.get(zone.kind.value),
                    }
                    for zone in requirements.zones
                ],
                "external_events": [
                    {"kind": item.kind.value, "description": item.description}
                    for item in requirements.external_events
                ],
                "components": [component.value for component in info.components],
            }
        )
    return {"contract_version": CONTRACT_VERSION, "detectors": detectors}


def render(catalog: dict) -> str:
    body = json.dumps(catalog, ensure_ascii=False, indent=2)
    return (
        "// Сгенерировано scripts/export_ui_catalog.py из detector_core/contract/catalog.py.\n"
        "// Не редактируйте вручную: tests/test_ui_pages.py сверяет файл с каталогом.\n"
        f"window.DETECTOR_CATALOG = {body};\n"
    )


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(build_ui_catalog()), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
