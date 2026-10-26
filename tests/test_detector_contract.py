import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from detector_core.contract import (
    BUILTIN_CATALOG,
    BaseDetector,
    BuiltinDetectorId,
    CameraConfig,
    ComponentId,
    Detection,
    Detector,
    DetectorConfig,
    Event,
    EventPhase,
    EventSubject,
    ExternalEvent,
    FrameContext,
    IssueCode,
    IssueSeverity,
    PersonObservation,
    SubjectRole,
    ZoneKind,
    camera_components,
    diff_components,
    effective_params,
    has_errors,
    point_in_polygon,
    resolve_components,
    validate_camera_config,
)
from detector_core.contract.catalog import CASH_THEFT
from detector_core.contract.schema_export import build_documents, render
from detector_core.legacy import (
    LEGACY_BATCH_KEY_TO_DETECTOR,
    LEGACY_CLASS_TO_DETECTOR,
    LEGACY_FLAG_TO_DETECTOR,
    camera_config_from_legacy,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "docs" / "schemas"
EXAMPLES_DIR = SCHEMAS_DIR / "examples"
FORBIDDEN_MODULES = {"libs", "apps", "fastapi", "starlette", "sqlalchemy", "ultralytics", "torch"}

DRAWER = {"id": "cash_drawer", "kind": "cash_drawer", "polygon": [[0.4, 0.6], [0.6, 0.6], [0.6, 0.8], [0.4, 0.8]]}
DISPLAY = {"id": "display", "kind": "display", "polygon": [[0.0, 0.2], [0.5, 0.2], [0.5, 0.7], [0.0, 0.7]]}


def camera(detectors=None, **overrides):
    data = {
        "camera_id": "cam-1",
        "scene": {"typical_person_height_frac": 0.5},
        "detectors": detectors or {},
    }
    data.update(overrides)
    return CameraConfig.model_validate(data)


def codes(issues, severity=IssueSeverity.ERROR):
    return {(issue.detector_id, issue.code) for issue in issues if issue.severity == severity}


def load_example(name):
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- каталог


def test_catalog_declares_five_detectors_without_passenger_counting():
    ids = [info.id for info in BUILTIN_CATALOG]
    assert ids == [item.value for item in BuiltinDetectorId]
    assert set(ids) == {"fight", "bullying", "cash_theft", "shelf_theft", "eating"}
    assert not any("passeng" in detector_id for detector_id in ids)


def test_catalog_shares_components_as_designed():
    by_id = {info.id: set(info.components) for info in BUILTIN_CATALOG}
    assert by_id["fight"] == by_id["bullying"]
    assert ComponentId.INTERACTION_MODEL in by_id["fight"]
    assert ComponentId.OBJECT_DETECTOR in by_id["shelf_theft"] & by_id["eating"]
    assert ComponentId.POS_INGEST in by_id["cash_theft"]
    assert ComponentId.OBJECT_DETECTOR not in by_id["fight"] | by_id["cash_theft"]


def test_catalog_params_have_valid_defaults():
    for info in BUILTIN_CATALOG:
        issues = validate_camera_config(
            camera(
                {info.id: {"params": {spec.name: spec.default for spec in info.params}}},
                zones=[DRAWER, DISPLAY],
                external_sources={"pos": ["register-1"]},
            ),
            BUILTIN_CATALOG,
        )
        assert not has_errors(issues), (info.id, issues)


def test_legacy_thresholds_and_cooldowns_are_catalog_defaults():
    # libs/rules.py: thresholds {1: 0.6, 2: 0.6, 3: 0.5, 4: 0.55, 5: 0.55}, cooldowns {1: 20, 2: 30, 3: 40, 4: 30, 5: 30}
    legacy = {1: (0.6, 20), 2: (0.6, 30), 3: (0.5, 40), 4: (0.55, 30), 5: (0.55, 30)}
    infos = {info.id: info for info in BUILTIN_CATALOG}
    for class_id, (threshold, cooldown) in legacy.items():
        info = infos[LEGACY_CLASS_TO_DETECTOR[class_id]]
        assert info.param("threshold").default == threshold
        assert info.param("cooldown_s").default == cooldown


# ---------------------------------------------------------------- примеры и схемы


@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.json")), ids=lambda path: path.name)
def test_examples_validate(path):
    model = {"camera_config": CameraConfig, "event": Event, "external_event": ExternalEvent}[path.name.split(".")[0]]
    parsed = model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if isinstance(parsed, CameraConfig):
        assert not has_errors(validate_camera_config(parsed, BUILTIN_CATALOG))


def test_example_event_lifecycle_is_consistent():
    events = [
        Event.model_validate(load_example(f"event.fight.{phase}.json"))
        for phase in ("started", "updated", "ended")
    ]
    assert [event.phase for event in events] == [EventPhase.STARTED, EventPhase.UPDATED, EventPhase.ENDED]
    assert len({event.event_id for event in events}) == 1
    assert [event.seq for event in events] == [0, 1, 2]
    assert events[-1].peak_confidence == max(event.peak_confidence for event in events)


def test_published_schemas_are_up_to_date():
    for filename, document in build_documents().items():
        path = SCHEMAS_DIR / filename
        assert path.is_file(), f"{filename} missing: python -m detector_core.contract.schema_export"
        assert path.read_text(encoding="utf-8") == render(document), (
            f"{filename} is stale: python -m detector_core.contract.schema_export"
        )


# ---------------------------------------------------------------- модели


def test_camera_config_rejects_bad_input():
    with pytest.raises(ValidationError):
        CameraConfig.model_validate({"camera_id": "cam-1", "detectors": {"fight": {"enabeld": True}}})
    with pytest.raises(ValidationError):
        CameraConfig.model_validate(
            {"camera_id": "cam-1", "zones": [{"id": "z", "kind": "display", "polygon": [[0, 0], [1, 1]]}]}
        )
    with pytest.raises(ValidationError):
        CameraConfig.model_validate(
            {"camera_id": "cam-1", "zones": [{"id": "z", "kind": "display", "polygon": [[0, 0], [1.2, 0], [1, 1]]}]}
        )
    with pytest.raises(ValidationError):
        CameraConfig.model_validate({"camera_id": "cam-1", "zones": [DISPLAY, DISPLAY]})
    with pytest.raises(ValidationError):
        CameraConfig.model_validate({"camera_id": "cam-1", "detectors": {"Fight!": {}}})


def test_event_lifecycle_rules():
    started = load_example("event.fight.started.json")
    ended = load_example("event.fight.ended.json")

    with pytest.raises(ValidationError):
        Event.model_validate({**ended, "ended_at": None})
    with pytest.raises(ValidationError):
        Event.model_validate({**started, "seq": 3})
    with pytest.raises(ValidationError):
        Event.model_validate({**started, "ended_at": started["started_at"]})
    with pytest.raises(ValidationError):
        Event.model_validate({**started, "peak_confidence": 0.1})
    with pytest.raises(ValidationError):
        Event.model_validate({**started, "started_at": "2026-10-26T14:03:11"})


def test_event_tolerates_fields_from_newer_engine():
    event = Event.model_validate({**load_example("event.fight.started.json"), "future_field": 1})
    assert event.phase == EventPhase.STARTED


def test_pos_event_rules():
    payment = load_example("external_event.pos_payment.json")
    assert ExternalEvent.model_validate(payment).amount_minor == 1250000
    with pytest.raises(ValidationError):
        ExternalEvent.model_validate({**payment, "occurred_at": "2026-10-20T09:21:05"})
    with pytest.raises(ValidationError):
        ExternalEvent.model_validate({**payment, "type": "teleport"})
    with pytest.raises(ValidationError):
        ExternalEvent.model_validate({**payment, "amount": 12500.0})


# ---------------------------------------------------------------- ленивая загрузка


def test_only_fight_does_not_need_object_detector():
    required = resolve_components([camera({"fight": {}})], BUILTIN_CATALOG)
    assert required == {ComponentId.POSE, ComponentId.TRACKER, ComponentId.INTERACTION_MODEL}
    assert ComponentId.OBJECT_DETECTOR not in required
    assert ComponentId.POS_INGEST not in required


def test_shelf_theft_and_eating_share_one_object_detector():
    same_camera = resolve_components([camera({"shelf_theft": {}, "eating": {}})], BUILTIN_CATALOG)
    two_cameras = resolve_components(
        [camera({"shelf_theft": {}}, camera_id="cam-1"), camera({"eating": {}}, camera_id="cam-2")],
        BUILTIN_CATALOG,
    )
    expected = {ComponentId.POSE, ComponentId.TRACKER, ComponentId.OBJECT_DETECTOR}
    assert same_camera == expected
    assert two_cameras == expected
    assert ComponentId.INTERACTION_MODEL not in same_camera


def test_camera_without_detectors_needs_nothing():
    assert resolve_components([camera()], BUILTIN_CATALOG) == set()
    assert resolve_components([camera({"fight": {"enabled": False}})], BUILTIN_CATALOG) == set()
    assert resolve_components([camera({"fight": {}}, enabled=False)], BUILTIN_CATALOG) == set()
    assert resolve_components([camera({"not_installed": {}})], BUILTIN_CATALOG) == set()
    assert resolve_components([], BUILTIN_CATALOG) == set()


def test_components_are_per_camera_and_unload_when_unused():
    checkout = camera({"cash_theft": {}}, camera_id="checkout")
    hall = camera({"fight": {}, "eating": {}}, camera_id="hall")
    assert camera_components(checkout, BUILTIN_CATALOG) == {
        ComponentId.POSE,
        ComponentId.TRACKER,
        ComponentId.POS_INGEST,
    }
    loaded = resolve_components([checkout, hall], BUILTIN_CATALOG)

    hall_without_eating = camera({"fight": {}}, camera_id="hall")
    delta = diff_components(loaded, resolve_components([checkout, hall_without_eating], BUILTIN_CATALOG))
    assert delta.to_load == set()
    assert delta.to_unload == {ComponentId.OBJECT_DETECTOR}


# ---------------------------------------------------------------- валидация


def test_cash_theft_without_drawer_zone_is_an_error():
    issues = validate_camera_config(
        camera({"cash_theft": {}}, external_sources={"pos": ["register-1"]}),
        BUILTIN_CATALOG,
    )
    assert codes(issues) == {("cash_theft", IssueCode.ZONE_MISSING)}
    missing = next(issue for issue in issues if issue.code == IssueCode.ZONE_MISSING)
    assert missing.details["zone_kind"] == ZoneKind.CASH_DRAWER.value
    assert "cash_drawer" in missing.message


def test_cash_theft_without_pos_stream_is_an_error():
    issues = validate_camera_config(camera({"cash_theft": {}}, zones=[DRAWER]), BUILTIN_CATALOG)
    assert codes(issues) == {("cash_theft", IssueCode.EXTERNAL_SOURCE_MISSING)}


def test_zone_restriction_must_point_to_zone_of_required_kind():
    issues = validate_camera_config(
        camera({"shelf_theft": {"zone_ids": ["cash_drawer", "nope"]}}, zones=[DRAWER, DISPLAY]),
        BUILTIN_CATALOG,
    )
    assert codes(issues) == {
        ("shelf_theft", IssueCode.ZONE_MISSING),
        ("shelf_theft", IssueCode.UNKNOWN_ZONE),
    }


def test_fps_person_size_params_and_version_are_checked():
    issues = validate_camera_config(
        camera(
            {
                "fight": {"version": "1.0", "params": {"threshold": 1.5, "colour": "red"}},
                "eating": {"params": {"object_labels": ["shoes"], "hand_to_mouth_min": 2.5}},
                "teleport": {},
            },
            fps=2,
            zones=[DISPLAY],
            scene={"typical_person_height_frac": 0.1},
        ),
        BUILTIN_CATALOG,
    )
    assert codes(issues) == {
        ("fight", IssueCode.VERSION_MISMATCH),
        ("fight", IssueCode.INVALID_PARAM),
        ("fight", IssueCode.UNKNOWN_PARAM),
        ("fight", IssueCode.FPS_TOO_LOW),
        ("fight", IssueCode.PERSON_TOO_SMALL),
        ("eating", IssueCode.INVALID_PARAM),
        ("eating", IssueCode.FPS_TOO_LOW),
        ("eating", IssueCode.PERSON_TOO_SMALL),
        ("teleport", IssueCode.UNKNOWN_DETECTOR),
    }
    eating_params = [i for i in issues if i.detector_id == "eating" and i.code == IssueCode.INVALID_PARAM]
    assert len(eating_params) == 2


def test_unknown_person_size_is_only_a_warning_and_disabled_detectors_are_skipped():
    config = CameraConfig.model_validate(
        {"camera_id": "cam-1", "detectors": {"fight": {}, "cash_theft": {"enabled": False}}}
    )
    issues = validate_camera_config(config, BUILTIN_CATALOG)
    assert not has_errors(issues)
    assert codes(issues, IssueSeverity.WARNING) == {("fight", IssueCode.PERSON_SIZE_UNKNOWN)}


def test_effective_params_merge_defaults():
    params = effective_params(CASH_THEFT, DetectorConfig(params={"pos_match_window_s": 15}))
    assert params["pos_match_window_s"] == 15
    assert params["threshold"] == 0.5
    assert params["cooldown_s"] == 40


# ---------------------------------------------------------------- интерфейс детектора


class _HandInDrawer(BaseDetector):
    info = CASH_THEFT

    def configure(self, camera, config):
        self.drawers = [zone for zone in camera.zones if zone.kind == ZoneKind.CASH_DRAWER]

    def process(self, frame):
        return [
            Detection(
                detector_id=self.id,
                camera_id=frame.camera_id,
                timestamp=frame.timestamp,
                label="hand_in_drawer",
                score=person.score,
                subjects=[EventSubject(track_id=person.track_id, role=SubjectRole.ACTOR)],
                zone_id=zone.id,
            )
            for person in frame.persons or ()
            for zone in frame.zones_of(ZoneKind.CASH_DRAWER)
            if point_in_polygon(person.center, zone.polygon)
        ]


def test_detector_protocol_is_implementable_without_heavy_dependencies():
    config = CameraConfig.model_validate(load_example("camera_config.checkout.json"))
    detector = _HandInDrawer()
    assert isinstance(detector, Detector)
    detector.configure(config, config.detectors["cash_theft"])
    frame = FrameContext(
        camera_id=config.camera_id,
        frame_index=10,
        timestamp=datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc),
        offset_s=2.0,
        fps=5.0,
        frame_size=(1920, 1080),
        zones=config.zones,
        persons=[
            PersonObservation(bbox=(0.45, 0.6, 0.55, 0.8), score=0.9, track_id=3),
            PersonObservation(bbox=(0.0, 0.0, 0.1, 0.3), score=0.9, track_id=4),
        ],
    )
    detections = detector.process(frame)
    assert [[s.track_id for s in d.subjects] for d in detections] == [[3]]
    assert detector.components == frozenset(CASH_THEFT.components)


def test_point_in_polygon_counts_border_as_inside():
    square = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    assert point_in_polygon((0.5, 0.5), square)
    assert point_in_polygon((0.2, 0.5), square)
    assert not point_in_polygon((0.9, 0.5), square)


# ---------------------------------------------------------------- миграция без потерь


def test_legacy_camera_converts_without_losing_zones_or_selection():
    theft_zone = [[0.1, 0.1], [0.3, 0.1], [0.3, 0.4]]
    display_zone = [[0.5, 0.5], [0.9, 0.5], [0.9, 0.9], [0.5, 0.9]]
    result = camera_config_from_legacy(
        {
            "id": "legacy-cam",
            "enabled": True,
            "ai_enabled": True,
            "fps_limit": 5,
            "theft_zone": json.dumps(theft_zone),
            "display_zone": json.dumps(display_zone),
            "counting_config": json.dumps([{"label": "Front", "line": [[0, 0.5], [1, 0.5]]}]),
            "detect_fights": True,
            "detect_bullying": False,
            "detect_theft": True,
            "detect_passengers": True,
            "detect_shoplifting": True,
            "detect_eating": False,
        },
        fight_sensitivity="high",
    )
    config = result.config
    zones = {zone.kind: zone for zone in config.zones}
    assert [list(point) for point in zones[ZoneKind.CASH_DRAWER].polygon] == theft_zone
    assert [list(point) for point in zones[ZoneKind.DISPLAY].polygon] == display_zone
    assert {key: value.enabled for key, value in config.detectors.items()} == {
        "fight": True,
        "bullying": False,
        "cash_theft": True,
        "shelf_theft": True,
        "eating": False,
    }
    assert config.detectors["fight"].params == {"threshold": 0.4}
    assert any("counting_config" in note for note in result.notes)
    # Без POS кража из кассы не включится: это осознанное изменение поведения.
    assert codes(validate_camera_config(config, BUILTIN_CATALOG)) == {
        ("cash_theft", IssueCode.EXTERNAL_SOURCE_MISSING)
    }


def test_legacy_ai_disabled_keeps_selection_and_short_zone_is_reported():
    result = camera_config_from_legacy(
        {"id": "c", "ai_enabled": False, "theft_zone": "[[0.1, 0.1], [0.2, 0.2]]", "display_zone": "[]"}
    )
    assert result.config.enabled is False
    assert all(item.enabled for item in result.config.detectors.values())
    assert result.config.zones == []
    assert len(result.notes) == 1 and "theft_zone" in result.notes[0]
    assert resolve_components([result.config], BUILTIN_CATALOG) == set()


def test_legacy_mappings_cover_current_application():
    from apps.api.routers.detection_tests import DETECTORS
    from libs.models import Camera

    flag_columns = {column.name for column in Camera.__table__.columns if column.name.startswith("detect_")}
    assert flag_columns - set(LEGACY_FLAG_TO_DETECTOR) == {"detect_passengers"}
    assert set(DETECTORS) - set(LEGACY_BATCH_KEY_TO_DETECTOR) == {"passengers"}
    for key, meta in DETECTORS.items():
        if meta["class_id"] is not None:
            assert LEGACY_CLASS_TO_DETECTOR[meta["class_id"]] == LEGACY_BATCH_KEY_TO_DETECTOR[key]
    assert {"theft_zone", "display_zone"} <= {column.name for column in Camera.__table__.columns}


# ---------------------------------------------------------------- граница пакета


def _imported_top_level_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def test_detector_core_does_not_import_app_or_heavy_runtimes():
    for path in (ROOT / "detector_core").rglob("*.py"):
        forbidden = set(_imported_top_level_modules(path)) & FORBIDDEN_MODULES
        assert not forbidden, f"{path.relative_to(ROOT)} imports {sorted(forbidden)}"


def test_contract_depends_only_on_stdlib_and_pydantic():
    allowed = set(sys.stdlib_module_names) | {"pydantic", "detector_core"}
    for path in (ROOT / "detector_core" / "contract").rglob("*.py"):
        extra = set(_imported_top_level_modules(path)) - allowed
        assert not extra, f"{path.relative_to(ROOT)} imports {sorted(extra)}"


def test_importing_contract_does_not_load_forbidden_modules():
    code = (
        "import json, sys\n"
        "import detector_core.contract, detector_core.contract.schema_export, detector_core.legacy\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {sorted(FORBIDDEN_MODULES)!r})\n"
        "print(json.dumps(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60, check=True
    )
    assert json.loads(result.stdout) == []
