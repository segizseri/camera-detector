"""FrameContext: что движок передаёт детектору на каждом кадре.

Это внутрипроцессная структура (не сериализуется), поэтому dataclass, а не
pydantic. Все координаты нормализованы в [0, 1] относительно кадра, как и зоны.
Соглашение: поле со значением None означает, что компонент для этой камеры не
загружен; пустой кортеж означает, что компонент работал и ничего не нашёл.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from detector_core.contract.models import BBox, Point, Zone
from detector_core.contract.ids import ZoneKind

# Индексы ключевых точек COCO-17, которыми пользуются детекторы.
KP_NOSE = 0
KP_LEFT_WRIST = 9
KP_RIGHT_WRIST = 10
KP_LEFT_HIP = 11
KP_RIGHT_HIP = 12


@dataclass(frozen=True, slots=True)
class PersonObservation:
    bbox: BBox
    score: float
    track_id: Optional[int] = None  # None, если трекер не загружен
    # 17 точек COCO: (x, y, уверенность); None, если поза не посчитана.
    keypoints: Optional[Sequence[tuple[float, float, float]]] = None

    @property
    def center(self) -> Point:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass(frozen=True, slots=True)
class ObjectObservation:
    label: str  # "product", "food", "drink", "bag", ...
    bbox: BBox
    score: float
    track_id: Optional[int] = None


@dataclass(frozen=True, slots=True)
class InteractionObservation:
    """Выход interaction_model для группы треков (обычно пары)."""

    track_ids: tuple[int, ...]
    # Вероятности по меткам модели, например {"aggression": 0.8, "fight": 0.7}.
    scores: Mapping[str, float]
    # Кто инициирует агрессию: track_id -> доля агрессивных действий в окне.
    initiator_share: Mapping[int, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FrameContext:
    camera_id: str
    frame_index: int
    timestamp: datetime  # время кадра, UTC (в пакетном режиме: начало видео + смещение)
    offset_s: float  # секунды от начала потока или видео
    fps: float  # фактическая частота анализа камеры
    frame_size: tuple[int, int]  # ширина, высота исходного кадра в пикселях
    zones: Sequence[Zone] = ()  # зоны, доступные этому детектору (с учётом zone_ids)
    persons: Optional[Sequence[PersonObservation]] = None
    objects: Optional[Sequence[ObjectObservation]] = None
    interactions: Optional[Sequence[InteractionObservation]] = None
    image: Any = None  # BGR-кадр (numpy), только для чтения

    def zones_of(self, kind: ZoneKind) -> list[Zone]:
        return [zone for zone in self.zones if zone.kind == kind]


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Чётно-нечётная проверка; граница считается внутри, как cv2.pointPolygonTest >= 0."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if _on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _on_segment(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> bool:
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > 1e-9:
        return False
    return min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9
