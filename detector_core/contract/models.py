"""Pydantic-модели публичного контракта движка детекций.

Входы движка (конфиги камер, POS-события) запрещают лишние поля, чтобы опечатка
не превращалась в молча проигнорированную настройку. Выходы (каталог, события)
лишние поля допускают: клиент старой версии должен читать сообщения новой.
"""

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from detector_core.contract.ids import (
    CONTRACT_VERSION,
    DETECTOR_ID_PATTERN,
    OBJECT_ID_PATTERN,
    SEMVER_PATTERN,
    ComponentId,
    ExternalSourceKind,
    Maturity,
    ZoneKind,
)

DetectorId = Annotated[str, StringConstraints(pattern=DETECTOR_ID_PATTERN)]
ObjectId = Annotated[str, StringConstraints(pattern=OBJECT_ID_PATTERN)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]
# Точка в нормализованных координатах кадра: x, y в [0, 1], начало в левом верхнем углу.
Point = tuple[Unit, Unit]
# Прямоугольник x1, y1, x2, y2 в нормализованных координатах.
BBox = tuple[Unit, Unit, Unit, Unit]
ParamValue = Union[bool, int, float, str, list[str]]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- каталог


class ParamType(str, Enum):
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    ENUM = "enum"
    STR = "str"
    STR_LIST = "str_list"


class ParamSpec(_Output):
    """Описание параметра детектора: по нему внешняя система строит форму настройки."""

    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    type: ParamType
    default: ParamValue
    title: str
    description: str = ""
    unit: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Optional[list[str]] = None


class ZoneRequirement(_Output):
    kind: ZoneKind
    min_count: int = Field(default=1, ge=1)
    description: str = ""


class ExternalEventRequirement(_Output):
    kind: ExternalSourceKind
    required: bool = True
    description: str = ""


class OperatingEnvelope(_Output):
    """Условия, в которых качество детектора измерялось и гарантируется."""

    camera_views: list[str] = Field(default_factory=list)
    max_people_in_view: Optional[int] = None
    min_illumination_lux: Optional[float] = None
    notes: list[str] = Field(default_factory=list)


class Requirements(_Output):
    """Обязательные входы детектора; проверяются при включении на камере."""

    min_fps: float = Field(gt=0)
    recommended_fps: Optional[float] = Field(default=None, gt=0)
    # Минимальная высота человека как доля высоты кадра (0 = не проверять).
    min_person_height_frac: float = Field(default=0.0, ge=0.0, le=1.0)
    zones: list[ZoneRequirement] = Field(default_factory=list)
    external_events: list[ExternalEventRequirement] = Field(default_factory=list)
    operating_envelope: OperatingEnvelope = Field(default_factory=OperatingEnvelope)


class OutputField(_Output):
    """Поле Event.attributes, которое детектор заполняет."""

    name: str
    type: Literal["integer", "number", "boolean", "string", "array"]
    description: str
    nullable: bool = False


class DetectorInfo(_Output):
    """Элемент каталога GET /detectors."""

    id: DetectorId
    version: Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)]
    title: str
    description: str
    maturity: Maturity
    event_type: DetectorId
    legacy_event_type: Optional[str] = None
    requirements: Requirements
    components: list[ComponentId]
    params: list[ParamSpec] = Field(default_factory=list)
    output_attributes: list[OutputField] = Field(default_factory=list)
    # Имя фичи в лицензионном ключе; None = входит в базовую поставку.
    license_feature: Optional[str] = None

    @field_validator("components")
    @classmethod
    def _unique_components(cls, value: list[ComponentId]) -> list[ComponentId]:
        if len(set(value)) != len(value):
            raise ValueError("components must be unique")
        return value

    @field_validator("params")
    @classmethod
    def _unique_params(cls, value: list[ParamSpec]) -> list[ParamSpec]:
        names = [spec.name for spec in value]
        if len(set(names)) != len(names):
            raise ValueError("param names must be unique")
        return value

    def param(self, name: str) -> Optional[ParamSpec]:
        return next((spec for spec in self.params if spec.name == name), None)


class DetectorCatalog(_Output):
    contract_version: str = CONTRACT_VERSION
    detectors: list[DetectorInfo]


# ---------------------------------------------------------------- конфигурация камеры


class Zone(_Input):
    id: ObjectId
    kind: ZoneKind
    polygon: list[Point] = Field(min_length=3, max_length=64)
    label: Optional[str] = None


class StreamSource(_Input):
    url: str = Field(min_length=1)
    transport: Literal["tcp", "udp"] = "tcp"
    username: Optional[str] = None
    password: Optional[SecretStr] = None


class SceneInfo(_Input):
    """Что известно о сцене; движок дополняет это измерениями на лету."""

    frame_width: Optional[int] = Field(default=None, gt=0)
    frame_height: Optional[int] = Field(default=None, gt=0)
    # Типичная (медианная) высота человека как доля высоты кадра.
    typical_person_height_frac: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    camera_view: Optional[str] = None


class DetectorConfig(_Input):
    enabled: bool = True
    # Ожидаемая версия: "0.1" (любой патч 0.1.x) или точная "0.1.0".
    version: Optional[str] = Field(default=None, pattern=r"^\d+\.\d+(?:\.\d+)?$")
    # Ограничить детектор этими зонами камеры; None = все зоны нужных типов.
    zone_ids: Optional[list[ObjectId]] = None
    params: dict[str, ParamValue] = Field(default_factory=dict)


class CameraConfig(_Input):
    """Конфигурация камеры: {camera_id, detectors: {id: {params...}}} плюс входы."""

    camera_id: ObjectId
    enabled: bool = True
    source: Optional[StreamSource] = None
    fps: float = Field(default=5.0, gt=0, le=30)
    scene: SceneInfo = Field(default_factory=SceneInfo)
    zones: list[Zone] = Field(default_factory=list)
    # Привязка внешних потоков, например {"pos": ["store-12/register-3"]}.
    external_sources: dict[ExternalSourceKind, list[ObjectId]] = Field(default_factory=dict)
    detectors: dict[DetectorId, DetectorConfig] = Field(default_factory=dict)
    # Метаданные клиента (магазин, этаж); движок копирует их в каждое событие.
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("zones")
    @classmethod
    def _unique_zone_ids(cls, value: list[Zone]) -> list[Zone]:
        ids = [zone.id for zone in value]
        if len(set(ids)) != len(ids):
            raise ValueError("zone ids must be unique within a camera")
        return value


# ---------------------------------------------------------------- результаты


class ExternalRef(_Output):
    kind: ExternalSourceKind
    source_id: str
    event_id: str
    transaction_id: Optional[str] = None


class SubjectRole(str, Enum):
    ACTOR = "actor"
    PARTICIPANT = "participant"
    AGGRESSOR = "aggressor"
    TARGET = "target"
    ONLOOKER = "onlooker"


class EventSubject(_Output):
    track_id: int
    role: SubjectRole
    bbox: Optional[BBox] = None


class Detection(_Output):
    """Сигнал детектора на одном кадре; из них движок собирает события."""

    detector_id: DetectorId
    camera_id: ObjectId
    timestamp: AwareDatetime
    label: str
    score: Unit
    # Ключ инцидента: детекции с одним ключом относятся к одному событию.
    # None = один инцидент на детектор и камеру (так работает текущий cooldown).
    incident_key: Optional[str] = None
    bbox: Optional[BBox] = None
    subjects: list[EventSubject] = Field(default_factory=list)
    zone_id: Optional[ObjectId] = None
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class EventPhase(str, Enum):
    STARTED = "started"
    UPDATED = "updated"
    ENDED = "ended"


class EndReason(str, Enum):
    INACTIVE = "inactive"  # нет активных детекций дольше end_after_s
    MAX_DURATION = "max_duration"
    CAMERA_STOPPED = "camera_stopped"
    DETECTOR_DISABLED = "detector_disabled"
    CONFIG_CHANGED = "config_changed"
    STREAM_END = "stream_end"  # пакетный режим: видео закончилось
    ENGINE_RESTART = "engine_restart"  # движок упал с открытым инцидентом и закрыл его после старта


class EventMedia(_Output):
    snapshot_url: Optional[str] = None
    clip_url: Optional[str] = None


class Event(_Output):
    """Событие с жизненным циклом started → updated* → ended.

    Все сообщения одного инцидента имеют общий event_id; seq растёт на 1
    с каждым сообщением, started имеет seq=0.
    """

    schema_version: str = Field(default=CONTRACT_VERSION, pattern=r"^\d+\.\d+$")
    event_id: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=0)
    phase: EventPhase
    detector_id: DetectorId
    detector_version: Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)]
    event_type: DetectorId
    camera_id: ObjectId
    started_at: AwareDatetime
    updated_at: AwareDatetime
    ended_at: Optional[AwareDatetime] = None
    end_reason: Optional[EndReason] = None
    confidence: Unit
    peak_confidence: Unit
    subjects: list[EventSubject] = Field(default_factory=list)
    zone_ids: list[ObjectId] = Field(default_factory=list)
    external_refs: list[ExternalRef] = Field(default_factory=list)
    media: Optional[EventMedia] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    source: Literal["live", "batch"] = "live"
    # Пакетный режим: смещения от начала видео, секунды.
    start_offset_s: Optional[float] = Field(default=None, ge=0)
    end_offset_s: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_lifecycle(self) -> "Event":
        if self.phase == EventPhase.STARTED and self.seq != 0:
            raise ValueError("started must have seq=0")
        if self.phase != EventPhase.STARTED and self.seq == 0:
            raise ValueError("only started may have seq=0")
        if self.phase == EventPhase.ENDED:
            if self.ended_at is None or self.end_reason is None:
                raise ValueError("ended requires ended_at and end_reason")
        elif self.ended_at is not None or self.end_reason is not None:
            raise ValueError("ended_at/end_reason are allowed only for phase=ended")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at must not precede started_at")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        if self.peak_confidence < self.confidence:
            raise ValueError("peak_confidence must be >= confidence")
        return self


# ---------------------------------------------------------------- внешние события


class PosEventType(str, Enum):
    TRANSACTION_STARTED = "transaction_started"
    ITEM_SCANNED = "item_scanned"
    PAYMENT = "payment"
    TRANSACTION_COMPLETED = "transaction_completed"
    TRANSACTION_VOIDED = "transaction_voided"
    REFUND = "refund"
    NO_SALE = "no_sale"
    DRAWER_OPENED = "drawer_opened"
    DRAWER_CLOSED = "drawer_closed"


class ExternalEvent(_Input):
    """Событие внешней системы (сейчас только POS), POST /v1/external-events."""

    schema_version: str = Field(default=CONTRACT_VERSION, pattern=r"^\d+\.\d+$")
    kind: ExternalSourceKind
    source_id: ObjectId  # должен совпадать с CameraConfig.external_sources[kind]
    event_id: str = Field(min_length=1, max_length=128)  # ключ идемпотентности
    type: PosEventType
    occurred_at: AwareDatetime
    transaction_id: Optional[str] = None
    operator_id: Optional[str] = None
    # Сумма в минимальных единицах валюты (тиын, копейки), без float.
    amount_minor: Optional[int] = None
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    payment_method: Optional[Literal["cash", "card", "mixed", "other"]] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- валидация


class IssueSeverity(str, Enum):
    ERROR = "error"  # детектор не включается
    WARNING = "warning"  # включается, но качество не гарантировано


class IssueCode(str, Enum):
    UNKNOWN_DETECTOR = "unknown_detector"
    VERSION_MISMATCH = "version_mismatch"
    ZONE_MISSING = "zone_missing"
    UNKNOWN_ZONE = "unknown_zone"
    EXTERNAL_SOURCE_MISSING = "external_source_missing"
    FPS_TOO_LOW = "fps_too_low"
    PERSON_TOO_SMALL = "person_too_small"
    PERSON_SIZE_UNKNOWN = "person_size_unknown"
    UNKNOWN_PARAM = "unknown_param"
    INVALID_PARAM = "invalid_param"


class ConfigIssue(_Output):
    camera_id: str
    detector_id: Optional[str] = None
    code: IssueCode
    severity: IssueSeverity
    field: str  # путь в CameraConfig, например "detectors.cash_theft.params.threshold"
    message: str  # по-русски, для показа пользователю
    details: dict[str, Any] = Field(default_factory=dict)
