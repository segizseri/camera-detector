from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

class NVRImportRequest(BaseModel):
    nvr_ip: str
    nvr_rtsp_port: int = 554
    nvr_http_port: int = 80
    username: str
    password: str
    channels_count: int
    stream_profile: str = "substream"
    rtsp_transport: str = "tcp"
    brand_preset: str = "hikvision"

class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    ai_enabled: Optional[bool] = None
    fps_limit: Optional[int] = None

class RTSPTestResult(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None

class WebhookCreate(BaseModel):
    name: str
    url: str
    secret: str
    enabled: bool = True

class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    secret: Optional[str] = None
    enabled: Optional[bool] = None
