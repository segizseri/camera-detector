import queue
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from apps.worker.ai import AIWorker


class _Array:
    def __init__(self, values):
        self._values = np.asarray(values, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class FakeTracker:
    """Stands in for PersonPoseTracker: every camera sees one person with track id 1."""

    def __init__(self):
        self.frames = []

    def track(self, frame):
        self.frames.append(frame)
        boxes = SimpleNamespace(data=_Array([[0, 0, 10, 10, 1, 0.9, 0]]), id=_Array([1]))
        return SimpleNamespace(boxes=boxes, keypoints=None)


class FakePipeline:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.ai_enabled = True
        self.frame_queue = queue.Queue()
        self.results = []

    def handle_ai_results(self, bboxes, keypoints, res, frame, timestamp, track_to_visitor=None):
        self.results.append((frame, track_to_visitor))


@pytest.fixture
def worker(monkeypatch):
    # Keep Re-ID (facenet weights download) out of this test.
    monkeypatch.setitem(sys.modules, "facenet_pytorch", None)
    return AIWorker(tracker_factory=FakeTracker)


def _process(worker, pipelines, expected):
    thread = threading.Thread(target=worker.loop, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline and any(len(p.results) < n for p, n in zip(pipelines, expected)):
        time.sleep(0.01)
    worker.stop()
    thread.join(timeout=5)


def test_each_camera_has_its_own_tracker_and_visitor_slice(worker):
    cam_a, cam_b = FakePipeline("cam-a"), FakePipeline("cam-b")
    worker.add_pipeline(cam_a)
    worker.add_pipeline(cam_b)
    # Both cameras use track id 1; only camera A has identified its person.
    worker.track_to_visitor[("cam-a", 1)] = "visitor-a"

    for frame in ("a1", "a2"):
        cam_a.frame_queue.put((0.0, frame))
    cam_b.frame_queue.put((0.0, "b1"))
    _process(worker, [cam_a, cam_b], [2, 1])

    tracker_a, tracker_b = worker.trackers["cam-a"], worker.trackers["cam-b"]
    assert tracker_a is not tracker_b
    assert tracker_a.frames == ["a1", "a2"]
    assert tracker_b.frames == ["b1"]
    assert [visitors for _, visitors in cam_a.results] == [{1: "visitor-a"}, {1: "visitor-a"}]
    assert [visitors for _, visitors in cam_b.results] == [{}]


def test_removing_a_camera_drops_only_its_state(worker):
    worker.add_pipeline(FakePipeline("cam-a"))
    worker.add_pipeline(FakePipeline("cam-b"))
    worker.track_to_visitor.update({("cam-a", 1): "visitor-a", ("cam-b", 1): "visitor-b"})
    worker._face_attempt_count.update({("cam-a", 2): 3, ("cam-b", 2): 5})

    worker.remove_pipeline("cam-a")

    assert set(worker.trackers) == {"cam-b"}
    assert worker.track_to_visitor == {("cam-b", 1): "visitor-b"}
    assert worker._face_attempt_count == {("cam-b", 2): 5}
    assert worker.visitors_for_camera("cam-a") == {}


def test_visitor_cache_drops_tracks_that_left(worker, monkeypatch):
    from apps.worker import ai

    cam = FakePipeline("cam-a")
    worker.add_pipeline(cam)
    tracker = worker.trackers["cam-a"]
    clock = [1000.0]
    monkeypatch.setattr(ai.time, "time", lambda: clock[0])
    # Track 1 is in every frame of FakeTracker; track 2 was identified earlier and has left.
    worker.track_to_visitor.update({("cam-a", 1): "visitor-1", ("cam-a", 2): "visitor-2"})
    worker._visitor_last_seen.update({("cam-a", 1): clock[0], ("cam-a", 2): clock[0]})

    clock[0] += ai.VISITOR_CACHE_TTL_SECONDS - 1
    worker.process_frame(cam, tracker, clock[0], "f1")
    assert worker.visitors_for_camera("cam-a") == {1: "visitor-1", 2: "visitor-2"}

    clock[0] += 31  # the cache is swept at most every 30 s
    worker.process_frame(cam, tracker, clock[0], "f2")
    assert worker.visitors_for_camera("cam-a") == {1: "visitor-1"}
    assert set(worker._visitor_last_seen) == {("cam-a", 1)}


def test_restarted_pipeline_gets_a_fresh_tracker(worker):
    worker.add_pipeline(FakePipeline("cam-a"))
    old_tracker = worker.trackers["cam-a"]
    worker.track_to_visitor[("cam-a", 1)] = "visitor-a"

    worker.remove_pipeline("cam-a")
    worker.add_pipeline(FakePipeline("cam-a"))

    assert worker.trackers["cam-a"] is not old_tracker
    assert worker.visitors_for_camera("cam-a") == {}


def test_new_tracker_does_not_reuse_ids_of_a_running_camera():
    pytest.importorskip("ultralytics")
    from libs.ai_models import PersonPoseTracker

    def detections(*boxes):
        xywh = np.array([[x, y, 40, 80] for x, y in boxes], dtype=np.float32)
        return SimpleNamespace(
            conf=np.full(len(boxes), 0.9, dtype=np.float32),
            xywh=xywh,
            cls=np.zeros(len(boxes), dtype=np.float32),
        )

    cam_a = PersonPoseTracker(model=None).tracker
    cam_a.update(detections((100, 100), (300, 100)))
    # Stock ultralytics resets its global id counter whenever a tracker is created.
    cam_b = PersonPoseTracker(model=None).tracker
    ids_b = {int(t) for t in cam_b.update(detections((100, 100)))[:, 4]}
    # A third person enters camera A; a new track is confirmed on its second hit.
    cam_a.update(detections((100, 100), (300, 100), (500, 100)))
    ids_a = [int(t) for t in cam_a.update(detections((100, 100), (300, 100), (500, 100)))[:, 4]]

    assert len(ids_a) == 3
    assert len(set(ids_a)) == 3
    assert not ids_b & set(ids_a)
