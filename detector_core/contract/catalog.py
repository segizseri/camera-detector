"""Эталонные объявления пяти встроенных детекторов.

Это целевой контракт: реализация детектора обязана объявлять ровно эти
требования, компоненты и параметры (или новую версию с записью в changelog).
Текущая готовность отражена в maturity; подробности в docs/detector_engine.md.
"""

from detector_core.contract.ids import (
    BuiltinDetectorId,
    ComponentId,
    ExternalSourceKind,
    Maturity,
    ZoneKind,
)
from detector_core.contract.models import (
    DetectorCatalog,
    DetectorInfo,
    ExternalEventRequirement,
    OperatingEnvelope,
    OutputField,
    ParamSpec,
    ParamType,
    Requirements,
    ZoneRequirement,
)

OBJECT_LABELS = ["product", "food", "drink", "bag"]


def _lifecycle_params(
    threshold: float, min_duration_s: float, end_after_s: float, cooldown_s: float
) -> list[ParamSpec]:
    return [
        ParamSpec(
            name="threshold",
            type=ParamType.FLOAT,
            default=threshold,
            minimum=0.05,
            maximum=0.99,
            title="Порог уверенности",
            description="Детекция со score не ниже порога считается активной.",
        ),
        ParamSpec(
            name="min_duration_s",
            type=ParamType.FLOAT,
            default=min_duration_s,
            minimum=0.0,
            maximum=120.0,
            unit="s",
            title="Минимальная длительность",
            description="Сколько секунд сигнал должен держаться, прежде чем уйдёт started.",
        ),
        ParamSpec(
            name="end_after_s",
            type=ParamType.FLOAT,
            default=end_after_s,
            minimum=1.0,
            maximum=300.0,
            unit="s",
            title="Завершение после тишины",
            description="ended уходит, если активных детекций нет дольше этого времени.",
        ),
        ParamSpec(
            name="cooldown_s",
            type=ParamType.FLOAT,
            default=cooldown_s,
            minimum=0.0,
            maximum=3600.0,
            unit="s",
            title="Пауза между событиями",
            description="После ended новое событие с тем же ключом инцидента не начнётся раньше.",
        ),
        ParamSpec(
            name="update_interval_s",
            type=ParamType.FLOAT,
            default=5.0,
            minimum=1.0,
            maximum=300.0,
            unit="s",
            title="Частота updated",
            description="Не чаще одного updated за этот интервал (и сразу при новом участнике).",
        ),
        ParamSpec(
            name="max_duration_s",
            type=ParamType.FLOAT,
            default=600.0,
            minimum=10.0,
            maximum=86400.0,
            unit="s",
            title="Максимальная длительность",
            description="Длинный инцидент закрывается с end_reason=max_duration.",
        ),
    ]


_PERSON_ENVELOPE_NOTES = [
    "Модель обучена на последовательностях 5 кадров/с, окно 30 кадров (6 с).",
    "Плотная толпа и сильные перекрытия людей выходят за пределы envelope.",
]

FIGHT = DetectorInfo(
    id=BuiltinDetectorId.FIGHT.value,
    version="0.1.0",
    title="Драка",
    description="Обоюдная физическая агрессия двух и более людей: удары, толчки, борьба.",
    maturity=Maturity.PROTOTYPE,
    event_type="fight",
    legacy_event_type="fight_suspected",
    requirements=Requirements(
        min_fps=5.0,
        recommended_fps=5.0,
        min_person_height_frac=0.15,
        operating_envelope=OperatingEnvelope(
            camera_views=["high_angle", "eye_level"],
            max_people_in_view=15,
            notes=_PERSON_ENVELOPE_NOTES,
        ),
    ),
    components=[ComponentId.POSE, ComponentId.TRACKER, ComponentId.INTERACTION_MODEL],
    params=_lifecycle_params(threshold=0.6, min_duration_s=1.5, end_after_s=5.0, cooldown_s=20.0)
    + [
        ParamSpec(
            name="min_participants",
            type=ParamType.INT,
            default=2,
            minimum=2,
            maximum=10,
            title="Минимум участников",
        ),
    ],
    output_attributes=[
        OutputField(name="participants", type="integer", description="Число участников драки."),
        OutputField(name="intensity", type="number", description="Средняя оценка агрессии за окно, 0..1."),
    ],
    license_feature="detector.fight",
)

BULLYING = DetectorInfo(
    id=BuiltinDetectorId.BULLYING.value,
    version="0.1.0",
    title="Буллинг",
    description=(
        "Длительная односторонняя агрессия против одного человека: та же модель "
        "взаимодействия, что у драки, плюс правила длительности и окружения."
    ),
    maturity=Maturity.PROTOTYPE,
    event_type="bullying",
    legacy_event_type="bullying_suspected",
    requirements=Requirements(
        min_fps=5.0,
        recommended_fps=5.0,
        min_person_height_frac=0.15,
        operating_envelope=OperatingEnvelope(
            camera_views=["high_angle", "eye_level"],
            max_people_in_view=15,
            notes=_PERSON_ENVELOPE_NOTES,
        ),
    ),
    components=[ComponentId.POSE, ComponentId.TRACKER, ComponentId.INTERACTION_MODEL],
    params=_lifecycle_params(threshold=0.6, min_duration_s=8.0, end_after_s=10.0, cooldown_s=30.0)
    + [
        ParamSpec(
            name="one_sided_ratio",
            type=ParamType.FLOAT,
            default=0.7,
            minimum=0.5,
            maximum=1.0,
            title="Односторонность агрессии",
            description="Доля агрессивных действий со стороны нападающих; отличает буллинг от драки.",
        ),
        ParamSpec(
            name="min_aggressors",
            type=ParamType.INT,
            default=1,
            minimum=1,
            maximum=10,
            title="Минимум нападающих",
        ),
        ParamSpec(
            name="max_targets",
            type=ParamType.INT,
            default=1,
            minimum=1,
            maximum=5,
            title="Максимум жертв",
        ),
        ParamSpec(
            name="count_onlookers",
            type=ParamType.BOOL,
            default=True,
            title="Учитывать зрителей",
            description="Люди рядом без участия (круг зрителей) повышают уверенность.",
        ),
    ],
    output_attributes=[
        OutputField(name="duration_s", type="number", description="Длительность агрессии, с."),
        OutputField(name="one_sided_ratio", type="number", description="Фактическая односторонность, 0..1."),
        OutputField(name="onlookers", type="integer", description="Число зрителей рядом."),
    ],
    license_feature="detector.bullying",
)

CASH_THEFT = DetectorInfo(
    id=BuiltinDetectorId.CASH_THEFT.value,
    version="0.1.0",
    title="Кража из кассы",
    description=(
        "Доступ к денежному ящику без подтверждающего POS-события: рука в зоне "
        "ящика вне транзакции, no_sale, открытие ящика при оплате картой."
    ),
    maturity=Maturity.CONCEPT,
    event_type="cash_theft",
    legacy_event_type="theft_suspected",
    requirements=Requirements(
        min_fps=5.0,
        recommended_fps=5.0,
        min_person_height_frac=0.25,
        zones=[
            ZoneRequirement(
                kind=ZoneKind.CASH_DRAWER,
                description="Полигон денежного ящика (бывшая theft_zone).",
            )
        ],
        external_events=[
            ExternalEventRequirement(
                kind=ExternalSourceKind.POS,
                description="Поток событий кассы, привязанной к камере.",
            )
        ],
        operating_envelope=OperatingEnvelope(
            camera_views=["overhead", "high_angle"],
            notes=[
                "Ящик и руки кассира видны без перекрытия.",
                "Часы POS и NVR синхронизированы (NTP), рассинхрон меньше pos_match_window_s.",
            ],
        ),
    ),
    components=[ComponentId.POSE, ComponentId.TRACKER, ComponentId.POS_INGEST],
    params=_lifecycle_params(threshold=0.5, min_duration_s=1.0, end_after_s=5.0, cooldown_s=40.0)
    + [
        ParamSpec(
            name="pos_match_window_s",
            type=ParamType.FLOAT,
            default=10.0,
            minimum=1.0,
            maximum=120.0,
            unit="s",
            title="Окно сопоставления с POS",
            description="Доступ к ящику легитимен, если в этом окне есть подходящее POS-событие.",
        ),
        ParamSpec(
            name="alert_on_no_sale",
            type=ParamType.BOOL,
            default=True,
            title="Тревога при no_sale",
        ),
        ParamSpec(
            name="alert_on_card_payment",
            type=ParamType.BOOL,
            default=True,
            title="Тревога при доступе к ящику во время оплаты картой",
        ),
    ],
    output_attributes=[
        OutputField(
            name="reason",
            type="string",
            description="access_without_transaction | no_sale_access | card_payment_access | access_after_void",
        ),
        OutputField(name="drawer_zone_id", type="string", description="Зона ящика."),
        OutputField(name="pos_transaction_id", type="string", nullable=True, description="Ближайшая транзакция."),
        OutputField(name="operator_id", type="string", nullable=True, description="Кассир из POS."),
        OutputField(
            name="seconds_from_pos_event",
            type="number",
            nullable=True,
            description="Разница во времени с ближайшим POS-событием, с.",
        ),
    ],
    license_feature="detector.cash_theft",
)

SHELF_THEFT = DetectorInfo(
    id=BuiltinDetectorId.SHELF_THEFT.value,
    version="0.1.0",
    title="Кража с витрины",
    description="Человек берёт товар в зоне витрины и прячет его в карман, сумку или под одежду.",
    maturity=Maturity.CONCEPT,
    event_type="shelf_theft",
    legacy_event_type="shoplifting_suspected",
    requirements=Requirements(
        min_fps=5.0,
        recommended_fps=5.0,
        min_person_height_frac=0.2,
        zones=[ZoneRequirement(kind=ZoneKind.DISPLAY, description="Полигон витрины (бывшая display_zone).")],
        operating_envelope=OperatingEnvelope(
            camera_views=["high_angle", "eye_level"],
            notes=["Товар в руке различим: от ~24 px по меньшей стороне на входе детектора предметов."],
        ),
    ),
    components=[ComponentId.POSE, ComponentId.TRACKER, ComponentId.OBJECT_DETECTOR],
    params=_lifecycle_params(threshold=0.55, min_duration_s=0.5, end_after_s=5.0, cooldown_s=30.0)
    + [
        ParamSpec(
            name="conceal_window_s",
            type=ParamType.FLOAT,
            default=3.0,
            minimum=0.5,
            maximum=15.0,
            unit="s",
            title="Окно «взял → спрятал»",
        ),
        ParamSpec(
            name="object_labels",
            type=ParamType.STR_LIST,
            default=["product"],
            choices=OBJECT_LABELS,
            title="Классы предметов",
        ),
        ParamSpec(
            name="min_object_score",
            type=ParamType.FLOAT,
            default=0.35,
            minimum=0.05,
            maximum=0.99,
            title="Порог детектора предметов",
        ),
        ParamSpec(
            name="require_object",
            type=ParamType.BOOL,
            default=True,
            title="Требовать предмет в руке",
            description="False: только по позе, как в текущем прототипе (больше ложных срабатываний).",
        ),
    ],
    output_attributes=[
        OutputField(name="display_zone_id", type="string", description="Зона витрины."),
        OutputField(name="object_label", type="string", nullable=True, description="Класс взятого предмета."),
        OutputField(
            name="conceal_location",
            type="string",
            description="pocket | bag | clothing | unknown",
        ),
        OutputField(name="grab_to_conceal_s", type="number", description="Время от захвата до сокрытия, с."),
    ],
    license_feature="detector.shelf_theft",
)

EATING = DetectorInfo(
    id=BuiltinDetectorId.EATING.value,
    version="0.1.0",
    title="Поедание у витрины",
    description="Человек ест или пьёт товар у витрины: предмет из зоны витрины многократно у рта.",
    maturity=Maturity.CONCEPT,
    event_type="eating",
    legacy_event_type="eating_suspected",
    requirements=Requirements(
        min_fps=5.0,
        recommended_fps=5.0,
        min_person_height_frac=0.2,
        zones=[ZoneRequirement(kind=ZoneKind.DISPLAY, description="Полигон витрины (бывшая display_zone).")],
        operating_envelope=OperatingEnvelope(
            camera_views=["high_angle", "eye_level"],
            notes=["Лицо и кисти видны; камера сзади человека вне envelope."],
        ),
    ),
    components=[ComponentId.POSE, ComponentId.TRACKER, ComponentId.OBJECT_DETECTOR],
    params=_lifecycle_params(threshold=0.55, min_duration_s=1.0, end_after_s=10.0, cooldown_s=30.0)
    + [
        ParamSpec(
            name="object_labels",
            type=ParamType.STR_LIST,
            default=["food", "drink"],
            choices=OBJECT_LABELS,
            title="Классы предметов",
        ),
        ParamSpec(
            name="hand_to_mouth_min",
            type=ParamType.INT,
            default=2,
            minimum=1,
            maximum=20,
            title="Минимум подносов ко рту",
        ),
        ParamSpec(
            name="window_s",
            type=ParamType.FLOAT,
            default=30.0,
            minimum=5.0,
            maximum=300.0,
            unit="s",
            title="Окно подсчёта",
        ),
        ParamSpec(
            name="require_object",
            type=ParamType.BOOL,
            default=True,
            title="Требовать еду или напиток в руке",
        ),
    ],
    output_attributes=[
        OutputField(name="display_zone_id", type="string", description="Зона витрины."),
        OutputField(name="object_label", type="string", nullable=True, description="food | drink | product"),
        OutputField(name="hand_to_mouth_count", type="integer", description="Сколько раз предмет был у рта."),
    ],
    license_feature="detector.eating",
)

BUILTIN_CATALOG: tuple[DetectorInfo, ...] = (FIGHT, BULLYING, CASH_THEFT, SHELF_THEFT, EATING)


def builtin_catalog() -> DetectorCatalog:
    return DetectorCatalog(detectors=list(BUILTIN_CATALOG))
