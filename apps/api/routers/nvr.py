from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Camera
from libs.schemas import NVRImportRequest, NVRDiscoverResponse, NVRChannelDiscovery, NVRSelectiveImportRequest
from libs.crypto import encrypt_password
import uuid
import urllib.parse
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

router = APIRouter()

def check_channel(k: int, req: NVRImportRequest) -> NVRChannelDiscovery:
    if req.brand_preset == "hikvision":
        stream_path = f"/Streaming/Channels/{k}02" if req.stream_profile == "substream" else f"/Streaming/Channels/{k}01"
    else:
        stream_path = f"/cam/realmonitor?channel={k}&subtype={'1' if req.stream_profile=='substream' else '0'}"
        
    user_enc = urllib.parse.quote(req.username)
    pass_enc = urllib.parse.quote(req.password)
    rtsp_url = f"rtsp://{user_enc}:{pass_enc}@{req.nvr_ip}:{req.nvr_rtsp_port}{stream_path}"
    
    try:
        cmd = [
            "ffprobe", "-rtsp_transport", req.rtsp_transport, "-v", "error",
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
            rtsp_url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
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
        if req.nvr.brand_preset == "hikvision":
            stream_path = f"/Streaming/Channels/{k}02" if req.nvr.stream_profile == "substream" else f"/Streaming/Channels/{k}01"
        else:
            stream_path = f"/cam/realmonitor?channel={k}&subtype={'1' if req.nvr.stream_profile=='substream' else '0'}"
            
        user_enc = urllib.parse.quote(req.nvr.username)
        pass_enc = urllib.parse.quote(req.nvr.password)
        rtsp_url = f"rtsp://{user_enc}:{pass_enc}@{req.nvr.nvr_ip}:{req.nvr.nvr_rtsp_port}{stream_path}"
            
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
    if req.brand_preset == "hikvision":
        stream_path = "/Streaming/Channels/102" if req.stream_profile == "substream" else "/Streaming/Channels/101"
    else:
        stream_path = "/cam/realmonitor?channel=1&subtype=1" if req.stream_profile == "substream" else "/cam/realmonitor?channel=1&subtype=0"
        
    user_enc = urllib.parse.quote(req.username)
    pass_enc = urllib.parse.quote(req.password)
    rtsp_url = f"rtsp://{user_enc}:{pass_enc}@{req.nvr_ip}:{req.nvr_rtsp_port}{stream_path}"
    
    # Run ffprobe to verify
    try:
        cmd = [
            "ffprobe", "-rtsp_transport", "tcp", "-v", "error",
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
            rtsp_url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
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
        if req.brand_preset == "hikvision":
            if req.stream_profile == "substream":
                stream_path = f"/Streaming/Channels/{k}02"
            else:
                stream_path = f"/Streaming/Channels/{k}01"
            
            user_enc = urllib.parse.quote(req.username)
            pass_enc = urllib.parse.quote(req.password)
            rtsp_url = f"rtsp://{user_enc}:{pass_enc}@{req.nvr_ip}:{req.nvr_rtsp_port}{stream_path}"
        else:
            # Fallback or generic logic
            user_enc = urllib.parse.quote(req.username)
            pass_enc = urllib.parse.quote(req.password)
            rtsp_url = f"rtsp://{user_enc}:{pass_enc}@{req.nvr_ip}:{req.nvr_rtsp_port}/cam/realmonitor?channel={k}&subtype={'1' if req.stream_profile=='substream' else '0'}"
            
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
