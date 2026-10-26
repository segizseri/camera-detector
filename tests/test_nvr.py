from types import SimpleNamespace

from apps.api.routers import nvr

NVR = {
    "nvr_ip": "rtsp",
    "nvr_rtsp_port": 8554,
    "username": "admin",
    "password": "secret",
    "channels_count": 2,
    "stream_profile": "substream",
    "rtsp_transport": "tcp",
    "brand_preset": "hikvision",
}


def _fake_probe(calls):
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("timeout")))
        online = cmd[-1].endswith("/Streaming/Channels/102")
        return SimpleNamespace(returncode=0 if online else 1, stdout="h264\n" if online else "", stderr="")

    return run


def test_discover_probes_quickly_with_enough_timeout(client, monkeypatch):
    calls = []
    monkeypatch.setattr(nvr.subprocess, "run", _fake_probe(calls))

    response = client.post("/api/nvr/discover", json=NVR)

    assert response.status_code == 200
    channels = {ch["channel"]: ch for ch in response.json()["channels"]}
    assert channels[1]["status"] == "online" and channels[1]["codec"] == "h264"
    assert channels[2]["status"] == "offline"
    assert channels[1]["rtsp_url"] == "rtsp://rtsp:8554/Streaming/Channels/102"
    for cmd, timeout in calls:
        # Без ограничения анализа ffprobe отвечает ~5 с, и живые каналы считались офлайн.
        assert "-analyzeduration" in cmd
        assert timeout >= 5


def test_connection_check_uses_same_probe(client, monkeypatch):
    calls = []
    monkeypatch.setattr(nvr.subprocess, "run", _fake_probe(calls))

    response = client.post("/api/nvr/test-connection", json=NVR)

    assert response.json()["status"] == "success"
    cmd, timeout = calls[0]
    assert "-analyzeduration" in cmd
    assert timeout >= 5
