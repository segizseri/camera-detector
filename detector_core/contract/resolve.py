"""Чистые функции выбора детекторов: какие компоненты грузить и чего не хватает."""

from typing import Iterable, Mapping, NamedTuple, Optional, Union

from detector_core.contract.ids import COMPONENT_DEPENDENCIES, ComponentId
from detector_core.contract.models import (
    CameraConfig,
    ConfigIssue,
    DetectorConfig,
    DetectorInfo,
    IssueCode,
    IssueSeverity,
    ParamSpec,
    ParamType,
    ParamValue,
)

CatalogLike = Union[Mapping[str, DetectorInfo], Iterable[DetectorInfo]]


def index_catalog(catalog: CatalogLike) -> dict[str, DetectorInfo]:
    if isinstance(catalog, Mapping):
        return dict(catalog)
    return {info.id: info for info in catalog}


def with_dependencies(components: Iterable[ComponentId]) -> set[ComponentId]:
    result: set[ComponentId] = set()
    pending = list(components)
    while pending:
        component = pending.pop()
        if component in result:
            continue
        result.add(component)
        pending.extend(COMPONENT_DEPENDENCIES.get(component, ()))
    return result


def active_detector_ids(camera: CameraConfig, catalog: CatalogLike) -> list[str]:
    """Включённые детекторы камеры, известные каталогу. Пусто = AI на камере не запускается."""
    if not camera.enabled:
        return []
    known = index_catalog(catalog)
    return [
        detector_id
        for detector_id, config in camera.detectors.items()
        if config.enabled and detector_id in known
    ]


def camera_components(camera: CameraConfig, catalog: CatalogLike) -> set[ComponentId]:
    """Компоненты, которые нужно прогонять на кадрах этой камеры."""
    known = index_catalog(catalog)
    needed: set[ComponentId] = set()
    for detector_id in active_detector_ids(camera, known):
        needed.update(known[detector_id].components)
    return with_dependencies(needed)


def resolve_components(
    camera_configs: Iterable[CameraConfig], catalog: CatalogLike
) -> set[ComponentId]:
    """Общие компоненты, нужные хотя бы одному включённому детектору на какой-либо камере.

    Отключённые камеры и детекторы, а также id вне каталога ничего не добавляют
    (последние ловит validate_camera_config).
    """
    known = index_catalog(catalog)
    needed: set[ComponentId] = set()
    for camera in camera_configs:
        needed |= camera_components(camera, known)
    return needed


class ComponentDelta(NamedTuple):
    to_load: set[ComponentId]
    to_unload: set[ComponentId]


def diff_components(loaded: Iterable[ComponentId], required: Iterable[ComponentId]) -> ComponentDelta:
    loaded_set, required_set = set(loaded), set(required)
    return ComponentDelta(to_load=required_set - loaded_set, to_unload=loaded_set - required_set)


def effective_params(info: DetectorInfo, config: DetectorConfig) -> dict[str, ParamValue]:
    """Дефолты каталога, поверх них параметры камеры."""
    params: dict[str, ParamValue] = {spec.name: spec.default for spec in info.params}
    params.update(config.params)
    return params


def has_errors(issues: Iterable[ConfigIssue]) -> bool:
    return any(issue.severity == IssueSeverity.ERROR for issue in issues)


def validate_camera_config(camera: CameraConfig, catalog: CatalogLike) -> list[ConfigIssue]:
    """Чего не хватает включённым детекторам камеры. Ошибки блокируют включение."""
    known = index_catalog(catalog)
    issues: list[ConfigIssue] = []
    for detector_id, config in camera.detectors.items():
        if not config.enabled:
            continue
        info = known.get(detector_id)
        if info is None:
            issues.append(
                _issue(
                    camera,
                    detector_id,
                    IssueCode.UNKNOWN_DETECTOR,
                    f"detectors.{detector_id}",
                    f"Детектор «{detector_id}» не установлен в движке.",
                )
            )
            continue
        issues.extend(_validate_detector(camera, info, config))
    return issues


def _validate_detector(camera: CameraConfig, info: DetectorInfo, config: DetectorConfig) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    prefix = f"detectors.{info.id}"
    req = info.requirements

    if config.version and not (info.version == config.version or info.version.startswith(config.version + ".")):
        issues.append(
            _issue(
                camera,
                info.id,
                IssueCode.VERSION_MISMATCH,
                f"{prefix}.version",
                f"Ожидалась версия «{info.title}» {config.version}, в движке {info.version}.",
                expected=config.version,
                actual=info.version,
            )
        )

    zone_ids = {zone.id for zone in camera.zones}
    for zone_id in config.zone_ids or ():
        if zone_id not in zone_ids:
            issues.append(
                _issue(
                    camera,
                    info.id,
                    IssueCode.UNKNOWN_ZONE,
                    f"{prefix}.zone_ids",
                    f"Зона «{zone_id}» не найдена на камере.",
                    zone_id=zone_id,
                )
            )

    allowed = set(config.zone_ids) if config.zone_ids is not None else None
    for zone_req in req.zones:
        found = [
            zone
            for zone in camera.zones
            if zone.kind == zone_req.kind and (allowed is None or zone.id in allowed)
        ]
        if len(found) < zone_req.min_count:
            issues.append(
                _issue(
                    camera,
                    info.id,
                    IssueCode.ZONE_MISSING,
                    "zones",
                    f"Детектору «{info.title}» нужна зона типа {zone_req.kind.value}"
                    f" (минимум {zone_req.min_count}, найдено {len(found)}): "
                    f"нарисуйте полигон не меньше чем из 3 точек. {zone_req.description}".rstrip(),
                    zone_kind=zone_req.kind.value,
                    min_count=zone_req.min_count,
                    found=len(found),
                )
            )

    for ext in req.external_events:
        if ext.required and not camera.external_sources.get(ext.kind):
            issues.append(
                _issue(
                    camera,
                    info.id,
                    IssueCode.EXTERNAL_SOURCE_MISSING,
                    f"external_sources.{ext.kind.value}",
                    f"Детектору «{info.title}» нужен поток событий {ext.kind.value}: "
                    f"укажите external_sources.{ext.kind.value} (идентификатор источника).",
                    kind=ext.kind.value,
                )
            )

    if camera.fps < req.min_fps:
        issues.append(
            _issue(
                camera,
                info.id,
                IssueCode.FPS_TOO_LOW,
                "fps",
                f"Детектору «{info.title}» нужно не меньше {req.min_fps:g} кадров/с анализа, "
                f"у камеры {camera.fps:g}.",
                min_fps=req.min_fps,
                fps=camera.fps,
            )
        )

    if req.min_person_height_frac > 0:
        person = camera.scene.typical_person_height_frac
        if person is None:
            issues.append(
                _issue(
                    camera,
                    info.id,
                    IssueCode.PERSON_SIZE_UNKNOWN,
                    "scene.typical_person_height_frac",
                    f"Размер человека в кадре неизвестен; «{info.title}» рассчитан на людей "
                    f"не ниже {req.min_person_height_frac:.0%} высоты кадра. Движок проверит это на лету.",
                    severity=IssueSeverity.WARNING,
                    min_person_height_frac=req.min_person_height_frac,
                )
            )
        elif person < req.min_person_height_frac:
            issues.append(
                _issue(
                    camera,
                    info.id,
                    IssueCode.PERSON_TOO_SMALL,
                    "scene.typical_person_height_frac",
                    f"Люди занимают {person:.0%} высоты кадра, «{info.title}» нужно не меньше "
                    f"{req.min_person_height_frac:.0%}: приблизьте камеру или выберите другой ракурс.",
                    min_person_height_frac=req.min_person_height_frac,
                    typical_person_height_frac=person,
                )
            )

    specs = {spec.name: spec for spec in info.params}
    for name, value in config.params.items():
        field = f"{prefix}.params.{name}"
        spec = specs.get(name)
        if spec is None:
            issues.append(
                _issue(camera, info.id, IssueCode.UNKNOWN_PARAM, field, f"Неизвестный параметр «{name}».")
            )
            continue
        problem = check_param(spec, value)
        if problem:
            issues.append(
                _issue(
                    camera,
                    info.id,
                    IssueCode.INVALID_PARAM,
                    field,
                    f"Параметр «{spec.title}» ({name}): {problem}.",
                    value=value,
                )
            )
    return issues


def check_param(spec: ParamSpec, value: object) -> Optional[str]:
    """Причина, по которой значение не подходит, или None."""
    if spec.type == ParamType.BOOL:
        return None if isinstance(value, bool) else "ожидается true/false"
    if spec.type in (ParamType.INT, ParamType.FLOAT):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "ожидается число"
        if spec.type == ParamType.INT and not isinstance(value, int):
            return "ожидается целое число"
        if spec.minimum is not None and value < spec.minimum:
            return f"меньше минимума {spec.minimum:g}"
        if spec.maximum is not None and value > spec.maximum:
            return f"больше максимума {spec.maximum:g}"
        return None
    if spec.type in (ParamType.STR, ParamType.ENUM):
        if not isinstance(value, str):
            return "ожидается строка"
        if spec.type == ParamType.ENUM and spec.choices and value not in spec.choices:
            return f"допустимо: {', '.join(spec.choices)}"
        return None
    if spec.type == ParamType.STR_LIST:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return "ожидается список строк"
        if spec.choices:
            unknown = [item for item in value if item not in spec.choices]
            if unknown:
                return f"неизвестные значения {', '.join(unknown)}; допустимо: {', '.join(spec.choices)}"
        return None
    return "неизвестный тип параметра"


def _issue(
    camera: CameraConfig,
    detector_id: Optional[str],
    code: IssueCode,
    field: str,
    message: str,
    severity: IssueSeverity = IssueSeverity.ERROR,
    **details: object,
) -> ConfigIssue:
    return ConfigIssue(
        camera_id=camera.camera_id,
        detector_id=detector_id,
        code=code,
        severity=severity,
        field=field,
        message=message,
        details=details,
    )
