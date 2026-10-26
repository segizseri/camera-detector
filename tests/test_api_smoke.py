from libs.models import Camera
from libs.crypto import encrypt_password
from libs.camera_streams import camera_rtsp_url


def _add_camera(db_session, camera_id="test-cam-01", **overrides):
    data = {
        "id": camera_id,
        "name": "Test Camera 01",
        "nvr_ip": "rtsp",
        "rtsp_url": "rtsp://rtsp:8554/cam1",
        "username": "test",
        "encrypted_password": "",
        "channel": 1,
        "enabled": True,
        "ai_enabled": False,
        "fps_limit": 2,
        "status": "offline",
    }
    data.update(overrides)
    cam = Camera(
        **data,
    )
    db_session.add(cam)
    db_session.commit()
    return cam


def test_cameras_api_returns_seeded_camera(client, db_session):
    _add_camera(db_session)

    response = client.get("/api/cameras/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "test-cam-01"
    assert data[0]["rtsp_url"] == "rtsp://rtsp:8554/cam1"
    assert data[0]["fps_limit"] == 2
    assert "encrypted_password" not in data[0]


def test_cameras_api_never_returns_rtsp_password(client, db_session):
    _add_camera(
        db_session,
        rtsp_url="rtsp://operator:secretpass@rtsp:8554/cam1",
        username="operator",
        encrypted_password=encrypt_password("secretpass"),
    )

    response = client.get("/api/cameras/")

    assert response.status_code == 200
    data = response.json()[0]
    assert "secretpass" not in data["rtsp_url"]
    assert "encrypted_password" not in data


def test_runtime_rtsp_url_injects_encrypted_password(db_session):
    cam = _add_camera(
        db_session,
        rtsp_url="rtsp://rtsp:8554/cam1",
        username="operator",
        encrypted_password=encrypt_password("secretpass"),
    )

    assert camera_rtsp_url(cam) == "rtsp://operator:secretpass@rtsp:8554/cam1"


def test_update_camera_applies_runtime_flags(client, db_session):
    _add_camera(db_session)

    response = client.patch(
        "/api/cameras/test-cam-01",
        json={"ai_enabled": True, "fps_limit": 1, "detect_fights": False, "detect_eating": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ai_enabled"] is True
    assert data["fps_limit"] == 1
    assert data["detect_fights"] is False
    assert data["detect_eating"] is False


def test_system_metrics_endpoint(client, db_session):
    _add_camera(db_session, ai_enabled=True)

    response = client.get("/api/system/metrics")

    assert response.status_code == 200
    data = response.json()
    assert data["cameras"]["total"] == 1
    assert data["cameras"]["enabled"] == 1
    assert data["cameras"]["ai_enabled"] == 1
    assert "disk" in data
    assert "hls" in data


def test_hls_trigger_reuses_running_process(client, db_session, monkeypatch):
    from apps.api.routers import cameras as cameras_router

    _add_camera(db_session)
    started_commands = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        started_commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(cameras_router.subprocess, "Popen", fake_popen)

    first = client.post("/api/cameras/test-cam-01/trigger-hls")
    second = client.post("/api/cameras/test-cam-01/trigger-hls")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "starting"
    assert second.json()["status"] == "running"
    assert len(started_commands) == 1
    assert "rtsp://rtsp:8554/cam1" in started_commands[0]
