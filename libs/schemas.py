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

class NVRChannelDiscovery(BaseModel):
    channel: int
    rtsp_url: str
    status: str # online, offline
    codec: Optional[str] = None

class NVRDiscoverResponse(BaseModel):
    channels: List[NVRChannelDiscovery]

class NVRSelectiveImportRequest(BaseModel):
    nvr: NVRImportRequest
    selected_channels: List[int]

class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    ai_enabled: Optional[bool] = None
    fps_limit: Optional[int] = None
    theft_zone: Optional[str] = None
    counting_config: Optional[str] = None
    detect_fights: Optional[bool] = None
    detect_bullying: Optional[bool] = None
    detect_theft: Optional[bool] = None
    detect_passengers: Optional[bool] = None
    detect_shoplifting: Optional[bool] = None
    display_zone: Optional[str] = None

class RTSPTestResult(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None

class WebhookCreate(BaseModel):
    name: str
    hook_type: str = "http"
    url: str
    secret: str
    enabled: bool = True

class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    hook_type: Optional[str] = None
    url: Optional[str] = None
    secret: Optional[str] = None
    enabled: Optional[bool] = None
