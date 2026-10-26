from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.camera_streams import inject_rtsp_credentials, nvr_stream_path, public_rtsp_url
from libs.database import get_db
from libs.models import Camera
from libs.schemas import NVRImportRequest, NVRDiscoverResponse, NVRChannelDiscovery, NVRSelectiveImportRequest
from libs.crypto import encrypt_password
import uuid
import subprocess
from concurrent.futures import ThreadPoolExecutor

router = APIRouter()

# По умолчанию ffprobe анализирует живой RTSP-поток около 5 секунд, и рабочие каналы
# не успевали ответить за таймаут поиска. Для проверки «есть ли поток и какой кодек»
# хватает одной секунды анализа.
PROBE_ARGS = ["-analyzeduration", "1000000", "-probesize", "1000000"]
DISCOVER_TIMEOUT_SECONDS = 6
TEST_TIMEOUT_SECONDS = 8

def check_channel(k: int, req: NVRImportRequest) -> NVRChannelDiscovery:
    stream_path = nvr_stream_path(k, req.brand_preset, req.stream_profile)
    rtsp_url = public_rtsp_url(req.nvr_ip, req.nvr_rtsp_port, stream_path)
    probe_url = inject_rtsp_credentials(rtsp_url, req.username, req.password)
    
    try:
        cmd = [
            "ffprobe", "-rtsp_transport", req.rtsp_transport, "-v", "error", *PROBE_ARGS,
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
            probe_url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=DISCOVER_TIMEOUT_SECONDS)
        if res.returncode == 0:
            return NVRChannelDiscovery(channel=k, rtsp_url=rtsp_url, status="online", codec=res.stdout.strip())
        else:
            return NVRChannelDiscovery(channel=k, rtsp_url=rtsp_url, status="offline")
    except Exception:
        return NVRChannelDiscovery(channel=k, rtsp_url=rtsp_url, status="offline")

@router.post("/discover", response_model=NVRDiscoverResponse)
def discover_cameras(req: NVRImportRequest):
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(check_channel, k, req) for k in range(1, req.channels_count + 1)]
        for f in futures:
            results.append(f.result())
    return {"channels": results}

@router.post("/import-selected")
def import_selected(req: NVRSelectiveImportRequest, db: Session = Depends(get_db)):
    added = 0
    enc_pass = encrypt_password(req.nvr.password)
    
    for k in req.selected_channels:
        stream_path = nvr_stream_path(k, req.nvr.brand_preset, req.nvr.stream_profile)
        rtsp_url = public_rtsp_url(req.nvr.nvr_ip, req.nvr.nvr_rtsp_port, stream_path)
            
        cam_id = str(uuid.uuid4())
        new_cam = Camera(
            id=cam_id,
            name=f"Camera {k}",
            nvr_ip=req.nvr.nvr_ip,
            rtsp_url=rtsp_url,
            username=req.nvr.username,
            encrypted_password=enc_pass,
            channel=k,
            enabled=True,
            ai_enabled=True,
            fps_limit=5
        )
        db.add(new_cam)
        added += 1
        
    db.commit()
    return {"status": "success", "imported_count": added}

@router.post("/test-connection")
def test_connection(req: NVRImportRequest):
    # Construct URL for the first channel (substream preferred)
    stream_path = nvr_stream_path(1, req.brand_preset, req.stream_profile)
    rtsp_url = public_rtsp_url(req.nvr_ip, req.nvr_rtsp_port, stream_path)
    probe_url = inject_rtsp_credentials(rtsp_url, req.username, req.password)
    
    # Run ffprobe to verify
    try:
        cmd = [
            "ffprobe", "-rtsp_transport", "tcp", "-v", "error", *PROBE_ARGS,
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
            probe_url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=TEST_TIMEOUT_SECONDS)
        
        if res.returncode == 0:
            return {"status": "success", "message": "NVR connection successful"}
        else:
            return {"status": "error", "message": f"Connection failed: {res.stderr.strip() or 'Invalid stream'}"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Connection timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/import-cameras")
def import_cameras(req: NVRImportRequest, db: Session = Depends(get_db)):
    added = 0
    enc_pass = encrypt_password(req.password)
    
    for k in range(1, req.channels_count + 1):
        stream_path = nvr_stream_path(k, req.brand_preset, req.stream_profile)
        rtsp_url = public_rtsp_url(req.nvr_ip, req.nvr_rtsp_port, stream_path)
            
        cam_id = str(uuid.uuid4())
        new_cam = Camera(
            id=cam_id,
            name=f"Camera {k}",
            nvr_ip=req.nvr_ip,
            rtsp_url=rtsp_url,
            username=req.username,
            encrypted_password=enc_pass,
            channel=k,
            enabled=True,
            ai_enabled=True,
            fps_limit=5
        )
        db.add(new_cam)
        added += 1
        
    db.commit()
    return {"status": "success", "imported_count": added}
