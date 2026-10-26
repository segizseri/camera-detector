"""Стабильные идентификаторы контракта: детекторы, общие компоненты, зоны."""

from enum import Enum

CONTRACT_VERSION = "0.1"

# Идентификатор детектора. Встроенные детекторы перечислены в BuiltinDetectorId,
# плагины могут добавлять свои id в том же формате.
DETECTOR_ID_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
# Идентификаторы камер, зон и источников: uuid, "cam-01", "store-12/register-3".
OBJECT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"
SEMVER_PATTERN = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"


class BuiltinDetectorId(str, Enum):
    FIGHT = "fight"
    BULLYING = "bullying"
    CASH_THEFT = "cash_theft"
    SHELF_THEFT = "shelf_theft"
    EATING = "eating"


class ComponentId(str, Enum):
    """Общие компоненты, которые движок загружает лениво и делит между детекторами."""

    POSE = "pose"  # люди: bbox + 17 ключевых точек COCO
    TRACKER = "tracker"  # устойчивые track_id людей, состояние на каждую камеру
    INTERACTION_MODEL = "interaction_model"  # агрессия/взаимодействие между людьми
    OBJECT_DETECTOR = "object_detector"  # предметы: товар, еда, напитки, сумки
    POS_INGEST = "pos_ingest"  # приём событий кассы и маршрутизация на камеры


# Прямые зависимости компонентов. Движок замыкает набор по этому графу,
# поэтому детектор может объявить только то, что использует сам.
COMPONENT_DEPENDENCIES: dict[ComponentId, frozenset[ComponentId]] = {
    ComponentId.POSE: frozenset(),
    ComponentId.TRACKER: frozenset({ComponentId.POSE}),
    ComponentId.INTERACTION_MODEL: frozenset({ComponentId.POSE, ComponentId.TRACKER}),
    ComponentId.OBJECT_DETECTOR: frozenset(),
    ComponentId.POS_INGEST: frozenset(),
}


class ZoneKind(str, Enum):
    CASH_DRAWER = "cash_drawer"  # денежный ящик кассы (legacy Camera.theft_zone)
    DISPLAY = "display"  # витрина/полка (legacy Camera.display_zone)
    INCLUDE = "include"  # анализировать только внутри
    EXCLUDE = "exclude"  # маска: экраны, зеркала, плакаты


class ExternalSourceKind(str, Enum):
    POS = "pos"


class Maturity(str, Enum):
    CONCEPT = "concept"  # контракт объявлен, реализации по нему ещё нет
    PROTOTYPE = "prototype"  # реализация есть, качество на реальных данных не измерено
    BETA = "beta"  # измерено на реальных данных, operating envelope описан
    STABLE = "stable"
