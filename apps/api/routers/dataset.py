"""Датасет для дообучения ActionLSTM: запись роликов с камер, состав по классам, статус обучения."""

import re
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs import training
from libs.camera_streams import camera_rtsp_url
from libs.config import settings
from libs.database import get_db
from libs.models import Camera

router = APIRouter()

# Окно модели — 30 кадров при 5 кадр/с, то есть 6 секунд непрерывного трека человека.
MIN_CLIP_SECONDS = 8
MAX_CLIP_SECONDS = 60
RECOMMENDED_CLIPS = 50
RECORD_MARGIN_SECONDS = 2
_CLIP_NAME = re.compile(r"^[\w\-.()\[\], ]+\.mp4$")


class RecordRequest(BaseModel):
    camera_id: str
    folder: str
    seconds: int = Field(default=15, ge=MIN_CLIP_SECONDS, le=MAX_CLIP_SECONDS)


def _class_dir(folder: str) -> Path:
    if folder not in training.DATASET_CLASSES:
        raise HTTPException(status_code=400, detail="Неизвестный класс датасета")
    return Path(settings.DATASET_DIR) / folder


def _clip_path(folder: str, name: str) -> Path:
    if not _CLIP_NAME.match(name) or Path(name).name != name:
        raise HTTPException(status_code=400, detail="Некорректное имя ролика")
    path = _class_dir(folder) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Ролик не найден")
    return path


def _slug(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE).strip("_")
    return value[:40] or "camera"


def _probe_seconds(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return round(float(result.stdout.strip()), 1)
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def _clip_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


@router.get("/summary")
def dataset_summary():
    classes = []
    for folder, title in training.DATASET_CLASSES.items():
        directory = Path(settings.DATASET_DIR) / folder
        clips = sorted(directory.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if directory.is_dir() else []
        frames = sum(1 for _ in directory.glob("*.jpg")) if directory.is_dir() else 0
        classes.append({
            "folder": folder,
            "title": title,
            "clips": len(clips),
            "size_bytes": sum(p.stat().st_size for p in clips),
            "frames": frames,
            "recent": [_clip_info(p) for p in clips[:20]],
        })
    return {
        "classes": classes,
        "recommended_clips": RECOMMENDED_CLIPS,
        "min_clip_seconds": MIN_CLIP_SECONDS,
        "max_clip_seconds": MAX_CLIP_SECONDS,
    }


@router.post("/record")
def record_clip(request: RecordRequest, db: Session = Depends(get_db)):
    directory = _class_dir(request.folder)
    cam = db.query(Camera).filter(Camera.id == request.camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Камера не найдена")

    directory.mkdir(parents=True, exist_ok=True)
    name = f"{_slug(cam.name or cam.id)}_{datetime.now():%Y%m%d_%H%M%S}.mp4"
    target = directory / name
    # Пишем во временный файл: обучение берёт только *.mp4 и не увидит недописанный ролик.
    partial = directory / f".{name}.part"
    # Кадры до первого опорного ffmpeg отбрасывает (до ~2 с), поэтому пишем с запасом,
    # чтобы ролик был не короче запрошенного.
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", camera_rtsp_url(cam),
        "-t", str(request.seconds + RECORD_MARGIN_SECONDS), "-an",
        "-vf", "scale='min(1280,iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-f", "mp4", str(partial),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=request.seconds + RECORD_MARGIN_SECONDS + 30)
    except subprocess.TimeoutExpired:
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=504, detail="Камера не отдала видео вовремя")
    if result.returncode != 0 or not partial.is_file() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()
        # В ошибке ffmpeg может оказаться RTSP-адрес с паролем
        last = re.sub(r"(rtsp://[^:@\s/]+:)[^@\s]+@", r"\1***@", detail[-1]) if detail else ""
        raise HTTPException(status_code=502, detail=f"Не удалось записать ролик с камеры. {last}".strip())
    partial.replace(target)
    return {**_clip_info(target), "folder": request.folder, "seconds": _probe_seconds(target)}


@router.get("/clips/{folder}/{name}")
def get_clip(folder: str, name: str):
    return FileResponse(_clip_path(folder, name), media_type="video/mp4")


@router.delete("/clips/{folder}/{name}")
def delete_clip(folder: str, name: str):
    _clip_path(folder, name).unlink()
    return {"status": "deleted"}


@router.get("/training")
def training_status():
    return {**training.read_status(), "log": training.read_log_tail()}
