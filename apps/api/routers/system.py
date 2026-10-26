import os
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.routers.cameras import cleanup_idle_hls_processes, hls_process_count
from libs.config import settings
from libs.database import get_db
from libs.models import Camera, Event
from libs.retention import cleanup_retention, data_disk_usage

router = APIRouter()


def _load_average() -> list[float] | None:
    try:
        return list(os.getloadavg())
    except OSError:
        return None


@router.get("/metrics")
def get_system_metrics(db: Session = Depends(get_db)):
    cleanup_idle_hls_processes()
    total_cameras = db.query(Camera).count()
    enabled_cameras = db.query(Camera).filter(Camera.enabled == True).count()
    ai_cameras = db.query(Camera).filter(Camera.enabled == True, Camera.ai_enabled == True).count()
    events_total = db.query(Event).count()

    return {
        "timestamp": int(time.time()),
        "cameras": {
            "total": total_cameras,
            "enabled": enabled_cameras,
            "ai_enabled": ai_cameras,
        },
        "hls": {
            "active_processes": hls_process_count(),
            "idle_timeout_seconds": settings.HLS_IDLE_TIMEOUT_SECONDS,
        },
        "disk": data_disk_usage(),
        "load_average": _load_average(),
        "events_total": events_total,
    }


@router.post("/cleanup")
def run_cleanup(db: Session = Depends(get_db)):
    cleanup_idle_hls_processes()
    return cleanup_retention(db)
