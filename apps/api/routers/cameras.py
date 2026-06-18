from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Camera, Event
from libs.schemas import CameraUpdate, RTSPTestResult, SnapshotRequest, SaveSessionRequest
import datetime
import subprocess
import time

router = APIRouter()

@router.get("/")
def get_cameras(db: Session = Depends(get_db)):
    return db.query(Camera).all()

@router.get("/{camera_id}")
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam

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
            cam.rtsp_url
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
    
    # In a perfect world we use a background task to start ffmpeg conversion
    # for /media/hls/cam_{camera_id}/index.m3u8 if it's not running
    import os
    hls_dir = f"data/media/hls/{camera_id}"
    os.makedirs(hls_dir, exist_ok=True)
    m3u8_path = os.path.join(hls_dir, "index.m3u8")
    
    cmd = [
        "ffmpeg", "-rtsp_transport", "tcp", "-i", cam.rtsp_url,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-c:a", "aac", "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list", m3u8_path
    ]
    
    # For MVP, we'll just spawn the subprocess and let it run (not robust, but MVP)
    # Ideally should be managed by a thread and killed when streams have 0 viewers
    def run_ffmpeg(command):
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    import threading
    t = threading.Thread(target=run_ffmpeg, args=(cmd,))
    t.start()
    
    return {"status": "starting", "hls_url": f"/media/hls/{camera_id}/index.m3u8"}

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
        "ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", cam.rtsp_url,
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

