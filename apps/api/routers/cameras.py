import datetime
import os
import subprocess
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.camera_streams import camera_rtsp_url, public_camera
from libs.config import settings
from libs.database import get_db
from libs.models import Camera, Event
from libs.schemas import CameraUpdate, RTSPTestResult, SnapshotRequest, SaveSessionRequest

router = APIRouter()

_hls_lock = threading.Lock()
_hls_processes = {}
_hls_reaper_started = False


def _hls_dir(camera_id: str) -> str:
    return os.path.join(settings.HLS_OUTPUT_DIR, camera_id)


def _hls_url(camera_id: str) -> str:
    return f"/media/hls/{camera_id}/index.m3u8"


def _is_running(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def _terminate_process(proc: subprocess.Popen | None):
    if not _is_running(proc):
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _drop_hls_files(camera_id: str):
    hls_dir = _hls_dir(camera_id)
    if not os.path.isdir(hls_dir):
        return
    for name in os.listdir(hls_dir):
        if name.endswith((".m3u8", ".ts")):
            try:
                os.remove(os.path.join(hls_dir, name))
            except OSError:
                pass


def stop_hls_stream(camera_id: str, remove_files: bool = False) -> bool:
    with _hls_lock:
        entry = _hls_processes.pop(camera_id, None)
    if not entry:
        if remove_files:
            _drop_hls_files(camera_id)
        return False

    _terminate_process(entry.get("proc"))
    if remove_files:
        _drop_hls_files(camera_id)
    return True


def cleanup_idle_hls_processes(now: float | None = None) -> int:
    now = now or time.time()
    to_stop = []
    with _hls_lock:
        for camera_id, entry in list(_hls_processes.items()):
            proc = entry.get("proc")
            if not _is_running(proc):
                _hls_processes.pop(camera_id, None)
                continue
            if now - entry.get("last_touch", 0) > settings.HLS_IDLE_TIMEOUT_SECONDS:
                to_stop.append(camera_id)

    stopped = 0
    for camera_id in to_stop:
        if stop_hls_stream(camera_id):
            stopped += 1
    return stopped


def hls_process_count() -> int:
    cleanup_idle_hls_processes()
    with _hls_lock:
        return sum(1 for entry in _hls_processes.values() if _is_running(entry.get("proc")))


def start_hls_reaper():
    global _hls_reaper_started
    if _hls_reaper_started:
        return
    _hls_reaper_started = True

    def _loop():
        while True:
            cleanup_idle_hls_processes()
            time.sleep(15)

    threading.Thread(target=_loop, daemon=True, name="hls-reaper").start()

@router.get("/")
def get_cameras(db: Session = Depends(get_db)):
    return [public_camera(cam) for cam in db.query(Camera).all()]

@router.get("/{camera_id}")
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return public_camera(cam)

@router.patch("/{camera_id}")
def update_camera(camera_id: str, update: CameraUpdate, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    if update.name is not None:
        cam.name = update.name
    if update.enabled is not None:
        cam.enabled = update.enabled
    if update.ai_enabled is not None:
        cam.ai_enabled = update.ai_enabled
    if update.fps_limit is not None:
        cam.fps_limit = update.fps_limit
    if update.theft_zone is not None:
        cam.theft_zone = update.theft_zone
    if update.counting_config is not None:
        cam.counting_config = update.counting_config
    if update.detect_fights is not None:
        cam.detect_fights = update.detect_fights
    if update.detect_bullying is not None:
        cam.detect_bullying = update.detect_bullying
    if update.detect_theft is not None:
        cam.detect_theft = update.detect_theft
    if update.detect_passengers is not None:
        cam.detect_passengers = update.detect_passengers
    if update.detect_shoplifting is not None:
        cam.detect_shoplifting = update.detect_shoplifting
    if update.detect_eating is not None:
        cam.detect_eating = update.detect_eating
    if update.display_zone is not None:
        cam.display_zone = update.display_zone
        
    db.commit()
    db.refresh(cam)
    return cam

@router.post("/{camera_id}/test-rtsp", response_model=RTSPTestResult)
def test_rtsp(camera_id: str, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    start_time = time.time()
    try:
        # Run ffprobe to get stream info in 5 seconds
        cmd = [
            "ffprobe", "-rtsp_transport", "tcp", "-v", "error",
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
            camera_rtsp_url(cam)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        latency = (time.time() - start_time) * 1000
        
        if res.returncode == 0 and res.stdout.strip():
            cam.status = "online"
            cam.last_seen = datetime.datetime.utcnow()
            db.commit()
            return {"status": "success", "latency_ms": latency}
        else:
            cam.status = "offline"
            db.commit()
            return {"status": "error", "error": "No stream info", "latency_ms": latency}
    except subprocess.TimeoutExpired:
        cam.status = "error"
        db.commit()
        return {"status": "error", "error": "Timeout"}
    except Exception as e:
        cam.status = "error"
        db.commit()
        return {"status": "error", "error": str(e)}

@router.post("/{camera_id}/trigger-hls")
def trigger_hls(camera_id: str, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    hls_dir = _hls_dir(camera_id)
    os.makedirs(hls_dir, exist_ok=True)
    m3u8_path = os.path.join(hls_dir, "index.m3u8")

    with _hls_lock:
        entry = _hls_processes.get(camera_id)
        proc = entry.get("proc") if entry else None
        if _is_running(proc):
            entry["last_touch"] = time.time()
            return {"status": "running", "hls_url": _hls_url(camera_id)}

        if entry:
            _hls_processes.pop(camera_id, None)

        _drop_hls_files(camera_id)
    
        cmd = [
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-i", camera_rtsp_url(cam),
            "-an",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-g", "30",
            "-sc_threshold", "0",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-f", "hls",
            "-hls_time", "2",
            "-hls_list_size", "6",
            "-hls_flags", "delete_segments+omit_endlist",
            m3u8_path
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _hls_processes[camera_id] = {"proc": proc, "last_touch": time.time()}
    
    return {"status": "starting", "hls_url": _hls_url(camera_id)}


@router.post("/{camera_id}/hls-keepalive")
def keepalive_hls(camera_id: str):
    with _hls_lock:
        entry = _hls_processes.get(camera_id)
        proc = entry.get("proc") if entry else None
        if _is_running(proc):
            entry["last_touch"] = time.time()
            return {"status": "running", "hls_url": _hls_url(camera_id)}
    return {"status": "stopped"}


@router.post("/{camera_id}/stop-hls")
def stop_hls(camera_id: str):
    stopped = stop_hls_stream(camera_id)
    return {"status": "stopped" if stopped else "not_running"}

@router.delete("/{camera_id}")
def delete_camera(camera_id: str, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    db.delete(cam)
    db.commit()
    return {"status": "success"}

@router.post("/{camera_id}/snapshot")
def capture_snapshot(camera_id: str, request: SnapshotRequest, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    if request.session_id:
        dataset_dir = f"data/dataset/.temp_{request.session_id}"
    elif request.dataset_folder:
        dataset_dir = f"data/dataset/{request.dataset_folder}"
    else:
        raise HTTPException(status_code=400, detail="Must provide session_id or dataset_folder")

    import os
    os.makedirs(dataset_dir, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}.jpg"
    filepath = os.path.join(dataset_dir, filename)
    
    cmd = [
        "ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", camera_rtsp_url(cam),
        "-vframes", "1", "-q:v", "2", filepath
    ]
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and os.path.exists(filepath):
            return {"status": "success", "filepath": filepath}
        else:
            return {"status": "error", "error": "Failed to capture snapshot", "details": res.stderr}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Timeout capturing snapshot"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@router.post("/{camera_id}/save-session")
def save_session(camera_id: str, request: SaveSessionRequest, db: Session = Depends(get_db)):
    import os
    import shutil
    
    temp_dir = f"data/dataset/.temp_{request.session_id}"
    final_dir = f"data/dataset/{request.dataset_folder}"
    
    if not os.path.exists(temp_dir):
        raise HTTPException(status_code=404, detail="Session not found or empty")
        
    os.makedirs(final_dir, exist_ok=True)
    
    moved_count = 0
    try:
        for filename in os.listdir(temp_dir):
            src = os.path.join(temp_dir, filename)
            dst = os.path.join(final_dir, filename)
            if os.path.isfile(src):
                shutil.move(src, dst)
                moved_count += 1
                
        # Clean up temp dir
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"status": "success", "moved_files": moved_count, "final_folder": request.dataset_folder}
    except Exception as e:
        return {"status": "error", "error": f"Failed to save session: {str(e)}"}
