import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from libs import youtube
from libs.config import settings
from libs.database import get_db
from libs.models import DetectionTestJob


router = APIRouter()

DETECTORS = {
    "fight": {"class_id": 1, "label": "Драка"},
    "bullying": {"class_id": 2, "label": "Буллинг"},
    "theft": {"class_id": 3, "label": "Кража"},
    "passengers": {"class_id": None, "label": "Счетчик пассажиров"},
    "shoplifting": {"class_id": 4, "label": "Кража из витрины"},
    "eating": {"class_id": 5, "label": "Поедание у витрины"},
}
ALLOWED_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
YOUTUBE_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}


class YouTubeJobCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: str = Field(min_length=10, max_length=2048)
    detectors: list[str]
    model_key: str = "general"
    sample_fps: float = Field(default=5.0, ge=1.0, le=10.0)


def _validate_youtube_url(value: str) -> str:
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный URL") from exc

    is_youtube = any(host == item or host.endswith(f".{item}") for item in YOUTUBE_HOSTS)
    if parsed.scheme not in {"http", "https"} or not is_youtube:
        raise HTTPException(
            status_code=400,
            detail="Разрешены только ссылки youtube.com, youtu.be и youtube-nocookie.com",
        )
    return value.strip()


def _validate_detectors(values: list[str]) -> list[str]:
    detectors = list(dict.fromkeys(values))
    invalid = [item for item in detectors if item not in DETECTORS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Неизвестные детекторы: {', '.join(invalid)}")
    if not detectors:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один детектор")
    return detectors


def _parse_detectors_form(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Поле detectors должно быть JSON-массивом") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=400, detail="Поле detectors должно быть JSON-массивом строк")
    return _validate_detectors(parsed)


def _model_path(model_key: str) -> Path:
    paths = {
        "general": Path(settings.ACTION_MODEL_PATH),
        "eating": Path(settings.MODELS_DIR) / "action_lstm_eating.pt",
    }
    if model_key not in paths:
        raise HTTPException(status_code=400, detail="Неизвестная AI-модель")
    return paths[model_key]


def _require_action_model(model_key: str) -> Path:
    path = _model_path(model_key)
    if not path.is_file():
        raise HTTPException(
            status_code=409,
            detail=(
                f"AI-модель {path.name} не найдена. "
                "Сначала обучите или скопируйте ее в data/models"
            ),
        )
    return path


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        relative = Path(path).resolve().relative_to(Path("data/media").resolve())
    except (ValueError, OSError):
        return None
    return "/media/" + relative.as_posix()


def _load_json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def serialize_job(job: DetectionTestJob) -> dict:
    results = _load_json(job.results_json, {})
    for event in results.get("events", []):
        snapshot_path = event.pop("snapshot_path", None)
        if snapshot_path and not event.get("snapshot_url"):
            event["snapshot_url"] = _media_url(snapshot_path)

    return {
        "id": job.id,
        "source_type": job.source_type,
        "source_url": job.source_url,
        "original_filename": job.original_filename,
        "status": job.status,
        "stage": job.stage,
        "progress": round(float(job.progress or 0.0), 1),
        "error": job.error,
        "detectors": _load_json(job.detectors_json, []),
        "model_key": job.model_key,
        "sample_fps": job.sample_fps,
        "duration_seconds": job.duration_seconds,
        "processed_frames": job.processed_frames,
        "total_frames": job.total_frames,
        "video_url": _media_url(job.output_video_path),
        "results": results,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _new_job(
    db: Session,
    *,
    source_type: str,
    detectors: list[str],
    model_key: str,
    sample_fps: float,
    source_url: str | None = None,
    original_filename: str | None = None,
    input_path: str | None = None,
    job_id: str | None = None,
) -> DetectionTestJob:
    job = DetectionTestJob(
        id=job_id or str(uuid.uuid4()),
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        input_path=input_path,
        detectors_json=json.dumps(detectors),
        model_key=model_key,
        sample_fps=sample_fps,
        status="queued",
        stage="queued",
        progress=0.0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/system")
def detection_test_system():
    model_paths = {
        "general": ("Общая модель", _model_path("general")),
        "eating": ("Eating-кандидат (Normal/Eating)", _model_path("eating")),
    }
    models = {}
    for key, (label, path) in model_paths.items():
        available = path.is_file()
        stat = path.stat() if available else None
        models[key] = {
            "label": label,
            "available": available,
            "filename": path.name,
            "size_bytes": stat.st_size if stat else None,
            "updated_at": stat.st_mtime if stat else None,
        }
    return {
        "model": models["general"],
        "models": models,
        "detectors": DETECTORS,
        "max_upload_mb": settings.DETECTION_TEST_MAX_UPLOAD_MB,
        "max_duration_seconds": settings.DETECTION_TEST_MAX_DURATION_SECONDS,
        "youtube_cookies": youtube.cookies_file() is not None,
    }


@router.get("/")
def list_jobs(limit: int = 20, db: Session = Depends(get_db)):
    safe_limit = max(1, min(limit, 100))
    jobs = db.query(DetectionTestJob).order_by(DetectionTestJob.created_at.desc()).limit(safe_limit).all()
    return [serialize_job(job) for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(DetectionTestJob).filter(DetectionTestJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задание анализа не найдено")
    return serialize_job(job)


@router.post("/youtube", status_code=201)
def create_youtube_job(payload: YouTubeJobCreate, db: Session = Depends(get_db)):
    _require_action_model(payload.model_key)
    url = _validate_youtube_url(payload.url)
    detectors = _validate_detectors(payload.detectors)
    job = _new_job(
        db,
        source_type="youtube",
        source_url=url,
        original_filename="YouTube video",
        detectors=detectors,
        model_key=payload.model_key,
        sample_fps=payload.sample_fps,
    )
    return serialize_job(job)


@router.post("/upload", status_code=201)
async def create_upload_job(
    video: UploadFile = File(...),
    detectors: str = Form(...),
    weights_key: str = Form("general", alias="model_key"),
    sample_fps: float = Form(5.0, ge=1.0, le=10.0),
    db: Session = Depends(get_db),
):
    _require_action_model(weights_key)
    selected_detectors = _parse_detectors_form(detectors)
    original_filename = Path(video.filename or "video").name
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются MP4, MOV, AVI, MKV, WebM и M4V",
        )

    job_id = str(uuid.uuid4())
    job_dir = Path(settings.DETECTION_TESTS_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    input_path = job_dir / f"source{suffix}"
    max_bytes = settings.DETECTION_TEST_MAX_UPLOAD_MB * 1024 * 1024
    written = 0

    try:
        with input_path.open("wb") as output:
            while chunk := await video.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Видео превышает лимит {settings.DETECTION_TEST_MAX_UPLOAD_MB} МБ",
                    )
                output.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="Загруженный файл пуст")

        job = _new_job(
            db,
            job_id=job_id,
            source_type="upload",
            original_filename=original_filename,
            input_path=str(input_path),
            detectors=selected_detectors,
            model_key=weights_key,
            sample_fps=sample_fps,
        )
        return serialize_job(job)
    except Exception:
        if input_path.exists():
            input_path.unlink()
        try:
            job_dir.rmdir()
        except OSError:
            pass
        raise
    finally:
        await video.close()
