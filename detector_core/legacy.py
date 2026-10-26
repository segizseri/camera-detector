"""Миграция с колонок Camera.detect_*/theft_zone/display_zone на CameraConfig.

Временный адаптер: принимает строку камеры как Mapping (без импорта libs.models)
и удаляется после перехода приложения на JSON-конфиг детекторов.
"""

import json
from typing import Any, Mapping, NamedTuple, Optional

from detector_core.contract.ids import BuiltinDetectorId, ZoneKind
from detector_core.contract.models import CameraConfig, DetectorConfig, Zone

# Классы ActionLSTM (libs/rules.py) -> детекторы движка.
LEGACY_CLASS_TO_DETECTOR: dict[int, str] = {
    1: BuiltinDetectorId.FIGHT.value,
    2: BuiltinDetectorId.BULLYING.value,
    3: BuiltinDetectorId.CASH_THEFT.value,
    4: BuiltinDetectorId.SHELF_THEFT.value,
    5: BuiltinDetectorId.EATING.value,
}

# Ключи ACTION_META / DETECTORS пакетного режима -> детекторы движка.
LEGACY_BATCH_KEY_TO_DETECTOR: dict[str, str] = {
    "fight": BuiltinDetectorId.FIGHT.value,
    "bullying": BuiltinDetectorId.BULLYING.value,
    "theft": BuiltinDetectorId.CASH_THEFT.value,
    "shoplifting": BuiltinDetectorId.SHELF_THEFT.value,
    "eating": BuiltinDetectorId.EATING.value,
}

LEGACY_FLAG_TO_DETECTOR: dict[str, str] = {
    "detect_fights": BuiltinDetectorId.FIGHT.value,
    "detect_bullying": BuiltinDetectorId.BULLYING.value,
    "detect_theft": BuiltinDetectorId.CASH_THEFT.value,
    "detect_shoplifting": BuiltinDetectorId.SHELF_THEFT.value,
    "detect_eating": BuiltinDetectorId.EATING.value,
}

# Колонка с JSON-полигоном -> (тип зоны, id зоны в CameraConfig).
LEGACY_ZONE_COLUMNS: dict[str, tuple[ZoneKind, str]] = {
    "theft_zone": (ZoneKind.CASH_DRAWER, "cash_drawer"),
    "display_zone": (ZoneKind.DISPLAY, "display"),
}

# GlobalSetting fight_sensitivity -> fight.params.threshold (apps/worker/pipeline.py).
FIGHT_SENSITIVITY_THRESHOLDS: dict[str, float] = {"low": 0.8, "medium": 0.6, "high": 0.4}

# Остаются в приложении и в движок не переносятся.
APP_ONLY_COLUMNS = ("detect_passengers", "counting_config")


class LegacyConversion(NamedTuple):
    config: CameraConfig
    notes: list[str]


def parse_legacy_polygon(raw: Optional[str]) -> Optional[list[tuple[float, float]]]:
    """JSON [[x, y], ...] в долях кадра; None, если пусто или меньше 3 точек.

    Повторяет текущий pipeline: полигон из < 3 точек игнорируется. Координаты
    за пределами кадра (клик по краю canvas) прижимаются к [0, 1].
    """
    if not raw:
        return None
    try:
        points = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(points, list) or len(points) < 3:
        return None
    polygon = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
        polygon.append((min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)))
    return polygon


def camera_config_from_legacy(
    row: Mapping[str, Any], fight_sensitivity: Optional[str] = None
) -> LegacyConversion:
    """Строка таблицы cameras -> CameraConfig без потери выбора детекторов и зон.

    ai_enabled=False не стирает флаги детекторов: камера выключается целиком
    (CameraConfig.enabled=False), выбор сохраняется на случай включения.
    """
    notes: list[str] = []
    zones: list[Zone] = []
    for column, (kind, zone_id) in LEGACY_ZONE_COLUMNS.items():
        raw = row.get(column)
        polygon = parse_legacy_polygon(raw)
        if polygon is not None:
            zones.append(Zone(id=zone_id, kind=kind, polygon=polygon))
        elif raw not in (None, "", "[]"):
            notes.append(f"{column}: полигон пропущен (не JSON или меньше 3 точек), как и в текущем pipeline")

    detectors: dict[str, DetectorConfig] = {}
    for column, detector_id in LEGACY_FLAG_TO_DETECTOR.items():
        # Колонки detect_* в модели по умолчанию True.
        detectors[detector_id] = DetectorConfig(enabled=bool(row.get(column, True)))

    threshold = FIGHT_SENSITIVITY_THRESHOLDS.get(fight_sensitivity or "")
    if threshold is not None and threshold != FIGHT_SENSITIVITY_THRESHOLDS["medium"]:
        detectors[BuiltinDetectorId.FIGHT.value].params["threshold"] = threshold

    for column in APP_ONLY_COLUMNS:
        if row.get(column):
            notes.append(f"{column}: подсчёт пассажиров остаётся в приложении, в движок не переносится")

    config = CameraConfig(
        camera_id=str(row["id"]),
        enabled=bool(row.get("enabled", True)) and bool(row.get("ai_enabled", True)),
        fps=float(max(1, int(row.get("fps_limit") or 5))),
        zones=zones,
        detectors=detectors,
    )
    return LegacyConversion(config=config, notes=notes)
