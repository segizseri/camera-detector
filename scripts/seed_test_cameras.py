import os
import sys
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from libs.database import Base, SessionLocal, engine
from libs.models import Bus, Camera, GlobalSetting


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
    count = int(os.getenv("TEST_CAMERA_COUNT", "2"))
    rtsp_host = os.getenv("TEST_RTSP_HOST", "rtsp")
    rtsp_port = int(os.getenv("TEST_RTSP_PORT", "8554"))
    fps_limit = int(os.getenv("TEST_CAMERA_FPS", "2"))
    ai_enabled = _as_bool(os.getenv("TEST_AI_ENABLED", "false"))
    id_prefix = os.getenv("TEST_CAMERA_ID_PREFIX", "test-cam-")

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(Camera).filter(Camera.id.like(f"{id_prefix}%")).all()
        for cam in existing:
            db.delete(cam)
        db.commit()

        bus = db.query(Bus).filter(Bus.name == "Test RTSP Bench").first()
        if not bus:
            bus = Bus(
                id=str(uuid.uuid4()),
                name="Test RTSP Bench",
                license_plate="TEST",
            )
            db.add(bus)
            db.commit()
            db.refresh(bus)

        for idx in range(1, count + 1):
            cam = Camera(
                id=f"{id_prefix}{idx:02d}",
                bus_id=bus.id,
                name=f"Test Camera {idx:02d}",
                nvr_ip=rtsp_host,
                rtsp_url=f"rtsp://{rtsp_host}:{rtsp_port}/cam{idx}",
                username="test",
                encrypted_password="",
                channel=idx,
                enabled=True,
                ai_enabled=ai_enabled,
                fps_limit=fps_limit,
                detect_fights=True,
                detect_bullying=True,
                detect_theft=True,
                detect_passengers=False,
                detect_shoplifting=True,
                detect_eating=True,
                status="offline",
            )
            db.add(cam)

        defaults = {
            "retention_days": "1",
            "fight_sensitivity": "medium",
            "visitor_scanning_enabled": "false",
        }
        for key, value in defaults.items():
            setting = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
            if setting:
                setting.value = value
            else:
                db.add(GlobalSetting(key=key, value=value))

        db.commit()
        print(
            f"Seeded {count} test cameras at rtsp://{rtsp_host}:{rtsp_port}/camN "
            f"(ai_enabled={ai_enabled}, fps_limit={fps_limit})"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
