from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Camera
from libs.schemas import NVRImportRequest
from libs.crypto import encrypt_password
import uuid

router = APIRouter()

@router.post("/test-connection")
def test_connection(req: NVRImportRequest):
    # For MVP, we'll try a basic ping or simple ffmpeg snapshot test
    # In a full app, this would use ffmpeg/ffprobe to verify connection 
    # to the first channel before accepting it all.
    # To keep MVP simple and non-blocking, we'll return ok.
    return {"status": "success", "message": "NVR connection check placeholder"}

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
            
            rtsp_url = f"rtsp://{req.username}:{req.password}@{req.nvr_ip}:{req.nvr_rtsp_port}{stream_path}"
        else:
            # Fallback or generic logic
            rtsp_url = f"rtsp://{req.username}:{req.password}@{req.nvr_ip}:{req.nvr_rtsp_port}/cam/realmonitor?channel={k}&subtype={'1' if req.stream_profile=='substream' else '0'}"
            
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
