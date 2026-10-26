"""Запись роликов в датасет, состав по классам и фоновое дообучение."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from apps.api.routers import dataset as dataset_router
from libs import training
from libs.config import settings
from libs.crypto import encrypt_password
from libs.models import Camera

EVALUATE_OUTPUT = """Held-out videos: 4

Held-out videos (not used for training)
Samples: 40
Accuracy: 0.8500
Confusion matrix rows=true cols=pred
       class precision  recall      f1 avg_conf support
      normal    0.9000  0.8182  0.8571   0.7000      22
       fight    0.8000  0.8889  0.8421   0.6500      18

For comparison, accuracy on training videos: 0.9900 (160 windows)
"""


class _FakeProcess:
    def __init__(self, output, code):
        self.stdout = iter(output.splitlines(keepends=True))
        self._code = code

    def wait(self):
        return self._code


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATASET_DIR", str(tmp_path / "dataset"))
    monkeypatch.setattr(settings, "MODELS_DIR", str(tmp_path / "models"))
    return tmp_path


@pytest.fixture
def camera(db_session):
    cam = Camera(id="cam-1", name="Касса 2", nvr_ip="rtsp", rtsp_url="rtsp://rtsp:8554/cam1", username="admin",
                 encrypted_password=encrypt_password("secret"), channel=1, enabled=True, ai_enabled=False,
                 fps_limit=5, status="online")
    db_session.add(cam)
    db_session.commit()
    return cam


def _fake_ffmpeg(calls, returncode=0, stderr=""):
    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout="15.0\n", stderr="")
        if returncode == 0:
            Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    return run


def test_record_writes_clip_into_class_folder(client, dirs, camera, monkeypatch):
    calls = []
    monkeypatch.setattr(dataset_router.subprocess, "run", _fake_ffmpeg(calls))

    response = client.post("/api/dataset/record", json={"camera_id": "cam-1", "folder": "1_fight", "seconds": 15})

    assert response.status_code == 200
    clip = response.json()
    assert clip["folder"] == "1_fight" and clip["seconds"] == 15.0
    assert clip["name"].startswith("Касса_2_") and clip["name"].endswith(".mp4")
    folder = Path(settings.DATASET_DIR) / "1_fight"
    assert [p.name for p in folder.iterdir()] == [clip["name"]]  # временный .part не остался
    ffmpeg = calls[0]
    assert ffmpeg[ffmpeg.index("-t") + 1] == str(15 + dataset_router.RECORD_MARGIN_SECONDS)
    assert "rtsp://admin:secret@rtsp:8554/cam1" in ffmpeg


def test_record_validates_input(client, dirs, camera):
    assert client.post("/api/dataset/record", json={"camera_id": "cam-1", "folder": "../x", "seconds": 15}).status_code == 400
    assert client.post("/api/dataset/record", json={"camera_id": "nope", "folder": "1_fight", "seconds": 15}).status_code == 404
    assert client.post("/api/dataset/record", json={"camera_id": "cam-1", "folder": "1_fight", "seconds": 3}).status_code == 422


def test_record_failure_hides_password_and_cleans_up(client, dirs, camera, monkeypatch):
    error = "rtsp://admin:secret@rtsp:8554/cam1: Connection refused"
    monkeypatch.setattr(dataset_router.subprocess, "run", _fake_ffmpeg([], returncode=1, stderr=error))

    response = client.post("/api/dataset/record", json={"camera_id": "cam-1", "folder": "0_normal", "seconds": 10})

    assert response.status_code == 502
    assert "secret" not in response.json()["detail"]
    assert "admin:***@" in response.json()["detail"]
    assert not any((Path(settings.DATASET_DIR) / "0_normal").iterdir())


def test_summary_lists_clips_and_frames_per_class(client, dirs):
    fight = Path(settings.DATASET_DIR) / "1_fight"
    fight.mkdir(parents=True)
    (fight / "a.mp4").write_bytes(b"1234")
    (fight / "b.mp4").write_bytes(b"12")
    (fight / ".c.mp4.part").write_bytes(b"x")
    (fight / "frame.jpg").write_bytes(b"x")

    data = client.get("/api/dataset/summary").json()

    classes = {c["folder"]: c for c in data["classes"]}
    assert list(classes) == list(training.DATASET_CLASSES)
    assert classes["1_fight"]["clips"] == 2
    assert classes["1_fight"]["size_bytes"] == 6
    assert classes["1_fight"]["frames"] == 1
    assert classes["0_normal"]["clips"] == 0
    assert data["recommended_clips"] == dataset_router.RECOMMENDED_CLIPS


def test_clip_can_be_viewed_and_deleted(client, dirs):
    fight = Path(settings.DATASET_DIR) / "1_fight"
    fight.mkdir(parents=True)
    (fight / "take 1.mp4").write_bytes(b"video")

    assert client.get("/api/dataset/clips/1_fight/take 1.mp4").content == b"video"
    assert client.get("/api/dataset/clips/1_fight/..%2F..%2Fsecret.mp4").status_code in (400, 404)
    assert client.get("/api/dataset/clips/etc/take 1.mp4").status_code == 400
    assert client.delete("/api/dataset/clips/1_fight/take 1.mp4").status_code == 200
    assert not (fight / "take 1.mp4").exists()


def test_training_status_defaults_to_idle(client, dirs):
    data = client.get("/api/dataset/training").json()

    assert data["state"] == "idle"
    assert data["log"] == []


def test_parse_metrics_reads_held_out_report():
    metrics = training.parse_metrics(EVALUATE_OUTPUT)

    assert metrics["accuracy"] == 0.85
    assert metrics["classes"]["1_fight"] == {"precision": 0.8, "recall": 0.8889, "f1": 0.8421, "support": 18}
    assert set(metrics["classes"]) == {"0_normal", "1_fight"}
    assert training.parse_metrics("Missing X.npy") is None


def test_training_pipeline_runs_steps_and_reports(dirs, monkeypatch):
    Path(settings.DATASET_DIR).mkdir(parents=True)
    np.save(Path(settings.DATASET_DIR) / "y.npy", np.array([0, 0, 1, 1, 1, 5]))
    fight = Path(settings.DATASET_DIR) / "1_fight"
    fight.mkdir()
    for name in ("a.mp4", "b.mp4"):
        (fight / name).write_bytes(b"x")
    commands = []
    statuses = []

    def popen(cmd, **kwargs):
        commands.append(cmd)
        if "evaluate_action_lstm.py" in cmd[1]:
            output = EVALUATE_OUTPUT
        elif "--extract" in cmd:
            output = "Processing data/dataset/1_fight/a.mp4...\nProcessing data/dataset/1_fight/b.mp4...\n"
        else:
            output = "ok\n"
        assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
        return _FakeProcess(output, 0)

    monkeypatch.setattr(training.subprocess, "Popen", popen)
    original_write = training._write_status
    monkeypatch.setattr(training, "_write_status", lambda **f: statuses.append(f) or original_write(**f))
    reloaded = []
    training._write_status(state="running")
    training._running = True

    training._pipeline(lambda: reloaded.append(True))

    status = training.read_status()
    assert status["state"] == "completed"
    assert status["windows"]["1_fight"] == 3 and status["windows"]["5_eating"] == 1
    assert status["metrics"]["classes"]["1_fight"]["recall"] == 0.8889
    assert [c[2] for c in commands] == ["--extract", "--train", "--weights", "--train"]
    assert "--holdout-frac" in commands[1] and commands[1][-1] == str(training.eval_weights_path())
    assert commands[2][-1] == str(training.eval_weights_path())
    assert reloaded == [True]
    assert training._running is False
    assert "Обучение финальной модели" in "\n".join(training.read_log_tail())
    assert {"done": 2, "total": 2} in [f.get("progress") for f in statuses]
    assert "Processing data/dataset/1_fight/b.mp4..." in training.read_log_tail()


def test_training_failure_is_reported(dirs, monkeypatch):
    monkeypatch.setattr(training.subprocess, "Popen", lambda cmd, **kw: _FakeProcess("boom\n", 1))
    training._write_status(state="running")

    training._pipeline(None)

    status = training.read_status()
    assert status["state"] == "failed"
    assert "извлечь позы" in status["error"]


def test_stale_running_status_is_recovered(dirs):
    training._write_status(state="running")

    training.recover_stale_status()

    assert training.read_status()["state"] == "failed"
