"""Интерфейс детектора и фабрики, через которую движок (и плагины) их создают."""

from typing import Mapping, Protocol, Sequence, runtime_checkable

from detector_core.contract.frame import FrameContext
from detector_core.contract.ids import ComponentId
from detector_core.contract.models import (
    CameraConfig,
    Detection,
    DetectorConfig,
    DetectorInfo,
    ExternalEvent,
    Requirements,
)


@runtime_checkable
class Detector(Protocol):
    """Экземпляр детектора на одной камере.

    Движок гарантирует:
    - configure() вызывается до первого process() и при каждом изменении
      конфигурации камеры, только если validate_camera_config() не вернул ошибок;
      params уже дополнены дефолтами (effective_params);
    - process() вызывается последовательно, из одного потока, с растущим offset_s;
    - в FrameContext заполнены выходы всех компонентов из components.
    Детектор не пишет в БД, не шлёт вебхуки и не держит модели общих компонентов:
    он только возвращает детекции, события из них собирает движок.
    """

    @property
    def info(self) -> DetectorInfo: ...

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def requirements(self) -> Requirements: ...

    @property
    def components(self) -> frozenset[ComponentId]: ...

    def configure(self, camera: CameraConfig, config: DetectorConfig) -> None: ...

    def process(self, frame: FrameContext) -> Sequence[Detection]: ...

    def on_external_event(self, event: ExternalEvent) -> Sequence[Detection]: ...

    def reset(self) -> None:
        """Сбросить состояние треков (переподключение потока, перемотка видео)."""
        ...


@runtime_checkable
class DetectorFactory(Protocol):
    """Точка входа плагина (entry point group "camera_detector.detectors")."""

    @property
    def info(self) -> DetectorInfo: ...

    def create(self, camera_id: str, components: Mapping[ComponentId, object]) -> Detector:
        """components: загруженные общие компоненты из info.components (и их зависимости)."""
        ...


class BaseDetector:
    """Необязательная база: выводит id/version/requirements/components из info."""

    info: DetectorInfo

    @property
    def id(self) -> str:
        return self.info.id

    @property
    def version(self) -> str:
        return self.info.version

    @property
    def requirements(self) -> Requirements:
        return self.info.requirements

    @property
    def components(self) -> frozenset[ComponentId]:
        return frozenset(self.info.components)

    def on_external_event(self, event: ExternalEvent) -> Sequence[Detection]:
        return ()

    def reset(self) -> None:
        return None
