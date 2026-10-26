from datetime import datetime, timedelta
from pathlib import Path

from libs.config import settings
from libs.models import DetectionTestJob, Event, GlobalSetting
from libs.retention import cleanup_retention


def test_retention_deletes_old_events_and_media(db_session):
    snapshot = Path("data-test/media/snapshots/old.jpg")
    clip = Path("data-test/media/clips/old.mp4")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    clip.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"snapshot")
    clip.write_bytes(b"clip")

    db_session.add(GlobalSetting(key="retention_days", value="7"))
    db_session.add(
        Event(
            id="old-event",
            camera_id="cam-1",
            event_type="fight_suspected",
            timestamp=datetime.utcnow() - timedelta(days=10),
            snapshot_path=str(snapshot),
            clip_path=str(clip),
        )
    )
    db_session.commit()

    result = cleanup_retention(db_session)

    assert result["deleted_events"] == 1
    assert result["deleted_snapshots"] == 1
    assert result["deleted_clips"] == 1
    assert not snapshot.exists()
    assert not clip.exists()


def test_retention_deletes_completed_detection_test(db_session):
    job_id = "old-detection-test"
    job_dir = Path(settings.DETECTION_TESTS_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "annotated.mp4").write_bytes(b"video")
    db_session.add(GlobalSetting(key="retention_days", value="7"))
    db_session.add(
        DetectionTestJob(
            id=job_id,
            source_type="upload",
            status="completed",
            stage="completed",
            progress=100,
            detectors_json='["eating"]',
            model_key="eating",
            created_at=datetime.utcnow() - timedelta(days=10),
        )
    )
    db_session.commit()

    result = cleanup_retention(db_session)

    assert result["deleted_detection_jobs"] == 1
    assert result["deleted_detection_test_dirs"] == 1
    assert not job_dir.exists()
    assert db_session.query(DetectionTestJob).filter_by(id=job_id).first() is None
