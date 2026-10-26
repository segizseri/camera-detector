import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from libs.config import settings
from libs.models import DetectionTestJob, Event, GlobalSetting


def _allowed_roots() -> list[Path]:
    return [
        Path("data").resolve(),
        Path(settings.SNAPSHOTS_DIR).resolve(),
        Path(settings.CLIPS_DIR).resolve(),
        Path(settings.HLS_OUTPUT_DIR).resolve(),
        Path(settings.DETECTION_TESTS_DIR).resolve(),
    ]


def _is_allowed_path(path: Path) -> bool:
    roots = _allowed_roots()
    return any(path == root or root in path.parents for root in roots)


def _retention_days(db, default: int = 7) -> int:
    row = db.query(GlobalSetting).filter(GlobalSetting.key == "retention_days").first()
    if not row:
        return default
    try:
        return max(1, int(row.value))
    except (TypeError, ValueError):
        return default


def _safe_unlink(path: str | None, base_dir: str) -> bool:
    if not path:
        return False

    candidate = Path(path)
    base = Path(base_dir)
    if not candidate.is_absolute() and not str(candidate).startswith(str(base)):
        candidate = base / candidate

    try:
        resolved = candidate.resolve()
        if not _is_allowed_path(resolved):
            return False
        if resolved.is_file():
            resolved.unlink()
            return True
    except OSError:
        return False

    return False


def _safe_rmtree(path: Path, base_dir: str) -> bool:
    try:
        root = Path(base_dir).resolve()
        resolved = path.resolve()
        if resolved == root or root not in resolved.parents or not _is_allowed_path(resolved):
            return False
        if resolved.is_dir():
            shutil.rmtree(resolved)
            return True
    except OSError:
        return False
    return False


def cleanup_retention(db, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    days = _retention_days(db)
    cutoff = now - timedelta(days=days)

    old_events = db.query(Event).filter(Event.timestamp < cutoff).all()
    removed_snapshots = 0
    removed_clips = 0

    for event in old_events:
        if _safe_unlink(event.snapshot_path, settings.SNAPSHOTS_DIR):
            removed_snapshots += 1
        if _safe_unlink(event.clip_path, settings.CLIPS_DIR):
            removed_clips += 1
        db.delete(event)

    old_detection_jobs = (
        db.query(DetectionTestJob)
        .filter(
            DetectionTestJob.created_at < cutoff,
            DetectionTestJob.status.in_(["completed", "failed"]),
        )
        .all()
    )
    removed_detection_dirs = 0
    for job in old_detection_jobs:
        job_dir = Path(settings.DETECTION_TESTS_DIR) / job.id
        if _safe_rmtree(job_dir, settings.DETECTION_TESTS_DIR):
            removed_detection_dirs += 1
        db.delete(job)

    removed_hls_files = cleanup_old_hls_files(cutoff)
    db.commit()

    return {
        "retention_days": days,
        "deleted_events": len(old_events),
        "deleted_snapshots": removed_snapshots,
        "deleted_clips": removed_clips,
        "deleted_hls_files": removed_hls_files,
        "deleted_detection_jobs": len(old_detection_jobs),
        "deleted_detection_test_dirs": removed_detection_dirs,
    }


def cleanup_old_hls_files(cutoff: datetime) -> int:
    root = Path(settings.HLS_OUTPUT_DIR)
    if not root.exists():
        return 0

    deleted = 0
    cutoff_ts = cutoff.timestamp()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".m3u8", ".ts"}:
            continue
        try:
            if path.stat().st_mtime < cutoff_ts:
                path.unlink()
                deleted += 1
        except OSError:
            pass

    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass

    return deleted


def data_disk_usage() -> dict:
    usage = shutil.disk_usage("data" if os.path.exists("data") else ".")
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "used_percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0,
    }
