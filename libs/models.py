from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from libs.database import Base

class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    nvr_ip = Column(String)
    rtsp_url = Column(String)
    username = Column(String)
    encrypted_password = Column(String)
    channel = Column(Integer)
    
    enabled = Column(Boolean, default=True)
    ai_enabled = Column(Boolean, default=True)
    fps_limit = Column(Integer, default=5)
    
    status = Column(String, default="offline") # offline, online, error
    last_seen = Column(DateTime, nullable=True)
    
    events = relationship("Event", back_populates="camera", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, index=True)
    camera_id = Column(String, ForeignKey("cameras.id"))
    event_type = Column(String) # person_detected, fight_suspected, camera_offline
    confidence = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    snapshot_path = Column(String, nullable=True)
    clip_path = Column(String, nullable=True)
    
    meta_json = Column(Text, nullable=True)

    camera = relationship("Camera", back_populates="events")

class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    url = Column(String)
    secret = Column(String)
    enabled = Column(Boolean, default=True)

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(String, ForeignKey("webhooks.id"))
    event_id = Column(String, ForeignKey("events.id"))
    status = Column(String, default="pending") # pending, success, failed
    attempts = Column(Integer, default=0)
    next_attempt = Column(DateTime, default=datetime.utcnow)
    last_error = Column(Text, nullable=True)
