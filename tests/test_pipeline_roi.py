import json
from types import SimpleNamespace

import numpy as np
import pytest

from apps.worker import pipeline as pipeline_module
from apps.worker.pipeline import CameraPipeline


LEFT_HALF = json.dumps([[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]])
FRAME = np.zeros((100, 200, 3), dtype=np.uint8)
# [x1, y1, x2, y2, track_id, conf, cls] as produced by the tracker.
INSIDE_BOX = [20, 20, 60, 80, 1, 0.9, 0]   # center x = 40 / 200 = 0.2 -> left half
OUTSIDE_BOX = [140, 20, 180, 80, 2, 0.9, 0]  # center x = 160 / 200 = 0.8 -> right half


class _Array:
    def __init__(self, values):
        self._values = np.asarray(values, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class FakeActionDetector:
    def __init__(self, camera_id, weights_path=None):
        self.seq_len = 30
        self.thresholds = {1: 0.6, 2: 0.6, 3: 0.5, 4: 0.55, 5: 0.55}
        self.cooldowns = {1: 20, 2: 30, 3: 40, 4: 30, 5: 30}
        self.last_alerts = {}
        self.result = (0, 0.0, None)

    def add_frame(self, bboxes, keypoints, track_ids, timestamp):
        return self.result


@pytest.fixture
def camera(monkeypatch):
    monkeypatch.setattr(pipeline_module, "AIActionDetector", FakeActionDetector)
    monkeypatch.setattr(CameraPipeline, "_ingest_loop", lambda self: None)
    pipe = CameraPipeline("cam-roi", "rtsp://test/stream", 5)
    pipe.events = []
    pipe.syncs = 0

    def trigger(event_type, conf, res, frame, visitor_id=None):
        pipe.events.append((event_type, visitor_id))

    def sync():
        pipe.syncs += 1

    monkeypatch.setattr(pipe, "_trigger_event", trigger)
    monkeypatch.setattr(pipe, "_sync_and_status", sync)
    monkeypatch.setattr(pipe, "_save_passenger_stats", lambda: None)
    return pipe


def _run(pipe, action, bboxes, visitors=None):
    pipe.action_det.result = action
    ids = [box[4] for box in bboxes]
    res = SimpleNamespace(boxes=SimpleNamespace(id=_Array(ids)))
    pipe.handle_ai_results(bboxes, None, res, FRAME, 0.0, visitors or {})


def test_theft_by_person_outside_register_zone_is_ignored(camera):
    camera.theft_zone = LEFT_HALF

    # Track 1 stands in the zone, but track 2 (outside) is the one doing the "theft".
    _run(camera, (3, 0.9, 2), [INSIDE_BOX, OUTSIDE_BOX])

    assert camera.events == []
    # Skipping the event must not skip the periodic camera status sync.
    assert camera.syncs == 1


def test_theft_by_person_inside_register_zone_fires_with_their_visitor(camera):
    camera.theft_zone = LEFT_HALF

    _run(camera, (3, 0.9, 1), [INSIDE_BOX, OUTSIDE_BOX], visitors={1: "visitor-1", 2: "visitor-2"})

    assert camera.events == [("theft_suspected", "visitor-1")]


@pytest.mark.parametrize("action_class, event_type", [(4, "shoplifting_suspected"), (5, "eating_suspected")])
def test_display_zone_checks_the_acting_track(camera, action_class, event_type):
    camera.display_zone = LEFT_HALF

    _run(camera, (action_class, 0.9, 2), [INSIDE_BOX, OUTSIDE_BOX])
    assert camera.events == []

    _run(camera, (action_class, 0.9, 1), [INSIDE_BOX, OUTSIDE_BOX])
    assert camera.events == [(event_type, None)]


def test_acting_track_missing_from_frame_does_not_fire(camera):
    camera.theft_zone = LEFT_HALF

    _run(camera, (3, 0.9, 7), [INSIDE_BOX])

    assert camera.events == []


def test_no_zone_configured_fires_regardless_of_position(camera):
    _run(camera, (3, 0.9, 2), [OUTSIDE_BOX])

    assert camera.events == [("theft_suspected", None)]


def test_fps_limit_mismatch_with_training_rate_is_logged(camera, capsys):
    camera.set_fps_limit(10)

    assert "differs from the ActionLSTM training rate" in capsys.readouterr().out
