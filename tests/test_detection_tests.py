from pathlib import Path

from apps.api.routers import detection_tests
from libs.models import DetectionTestJob


def _enable_model(monkeypatch, tmp_path):
    model_path = tmp_path / "action_lstm.pt"
    model_path.write_bytes(b"test-model-placeholder")
    monkeypatch.setattr(detection_tests.settings, "ACTION_MODEL_PATH", str(model_path))
    return model_path


def test_detection_test_page_is_available(client):
    response = client.get("/detection-test")

    assert response.status_code == 200
    assert "Проверка детекций на видео" in response.text
    assert "/api/detection-tests/youtube" in response.text
    assert "/api/detection-tests/upload" in response.text


def test_youtube_job_is_queued(client, db_session, monkeypatch, tmp_path):
    _enable_model(monkeypatch, tmp_path)

    response = client.post(
        "/api/detection-tests/youtube",
        json={
            "url": "https://youtu.be/example123",
            "detectors": ["fight", "eating", "passengers"],
            "sample_fps": 5,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"
    assert data["detectors"] == ["fight", "eating", "passengers"]
    assert data["model_key"] == "general"
    job = db_session.query(DetectionTestJob).filter_by(id=data["id"]).one()
    assert job.source_type == "youtube"
    assert job.source_url == "https://youtu.be/example123"


def test_youtube_job_rejects_non_youtube_url(client, monkeypatch, tmp_path):
    _enable_model(monkeypatch, tmp_path)

    response = client.post(
        "/api/detection-tests/youtube",
        json={"url": "https://example.com/video.mp4", "detectors": ["fight"]},
    )

    assert response.status_code == 400
    assert "YouTube" in response.json()["detail"] or "youtube" in response.json()["detail"]


def test_upload_job_saves_video(client, db_session, monkeypatch, tmp_path):
    _enable_model(monkeypatch, tmp_path)
    jobs_dir = tmp_path / "detection-tests"
    monkeypatch.setattr(detection_tests.settings, "DETECTION_TESTS_DIR", str(jobs_dir))

    response = client.post(
        "/api/detection-tests/upload",
        data={"detectors": '["shoplifting", "eating"]', "sample_fps": "2"},
        files={"video": ("shop sample.mp4", b"fake-video-content", "video/mp4")},
    )

    assert response.status_code == 201
    data = response.json()
    job = db_session.query(DetectionTestJob).filter_by(id=data["id"]).one()
    assert job.source_type == "upload"
    assert job.original_filename == "shop sample.mp4"
    assert job.sample_fps == 2
    assert job.model_key == "general"
    assert Path(job.input_path).read_bytes() == b"fake-video-content"


def test_eating_candidate_can_be_selected(client, monkeypatch, tmp_path):
    monkeypatch.setattr(detection_tests.settings, "ACTION_MODEL_PATH", str(tmp_path / "missing-general.pt"))
    monkeypatch.setattr(detection_tests.settings, "MODELS_DIR", str(tmp_path))
    (tmp_path / "action_lstm_eating.pt").write_bytes(b"eating-candidate")

    response = client.post(
        "/api/detection-tests/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=example",
            "detectors": ["eating"],
            "model_key": "eating",
            "sample_fps": 5,
        },
    )

    assert response.status_code == 201
    assert response.json()["model_key"] == "eating"


def test_job_creation_requires_trained_model(client, monkeypatch, tmp_path):
    monkeypatch.setattr(detection_tests.settings, "ACTION_MODEL_PATH", str(tmp_path / "missing.pt"))

    response = client.post(
        "/api/detection-tests/youtube",
        json={"url": "https://www.youtube.com/watch?v=example", "detectors": ["fight"]},
    )

    assert response.status_code == 409
    assert "AI-модель" in response.json()["detail"]
