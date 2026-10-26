from datetime import datetime
from types import SimpleNamespace

from libs import webhooks
from libs.models import Webhook


def test_queue_webhook_has_russian_labels_for_all_action_events(monkeypatch):
    sent = []

    class _Thread:
        def __init__(self, target, args):
            sent.append(args[0])

        def start(self):
            pass

    monkeypatch.setattr(webhooks.threading, "Thread", _Thread)
    for event_type in ("bullying_suspected", "eating_suspected"):
        event = SimpleNamespace(
            id="evt", event_type=event_type, camera_id="cam-1",
            timestamp=datetime(2026, 1, 1), confidence=0.8, snapshot_path=None,
        )
        webhooks.queue_webhook(event)

    assert [e["event_type_ru"] for e in sent] == [
        "Подозрение на буллинг",
        "Подозрение на поедание/распитие у витрины",
    ]


def test_telegram_message_for_event_without_confidence(db_session, monkeypatch):
    db_session.add(Webhook(id="tg", hook_type="telegram", name="TG", url="chat-1", secret="token", enabled=True))
    db_session.commit()
    posts = []

    def fake_post(url, **kwargs):
        posts.append(kwargs)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(webhooks.requests, "post", fake_post)

    webhooks.send_webhook({
        "event_id": "evt",
        "event_type": "camera_offline",
        "event_type_ru": "Камера отключена",
        "camera_id": "cam-1",
        "timestamp": "2026-01-01T00:00:00",
        "confidence": None,
        "snapshot_url": None,
    })

    assert len(posts) == 1
    text = posts[0]["json"]["text"]
    assert "Камера отключена" in text
    assert "Уверенность" not in text
