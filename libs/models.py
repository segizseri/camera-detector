from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from libs.database import Base

class Bus(Base):
    __tablename__ = "buses"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    license_plate = Column(String, nullable=True)
    
    cameras = relationship("Camera", back_populates="bus")

class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String, primary_key=True, index=True)
    bus_id = Column(String, ForeignKey("buses.id"), nullable=True)
    name = Column(String, index=True)
    
    bus = relationship("Bus", back_populates="cameras")
    nvr_ip = Column(String)
    rtsp_url = Column(String)
    username = Column(String)
    encrypted_password = Column(String)
    channel = Column(Integer)
    
    enabled = Column(Boolean, default=True)
    ai_enabled = Column(Boolean, default=True)
    fps_limit = Column(Integer, default=5)
    theft_zone = Column(Text, nullable=True)
    counting_config = Column(Text, nullable=True) # JSON with lines/zones
    
    # Granular AI Features
    detect_fights = Column(Boolean, default=True)
    detect_bullying = Column(Boolean, default=True)
    detect_theft = Column(Boolean, default=True)
    detect_passengers = Column(Boolean, default=True)
    detect_shoplifting = Column(Boolean, default=True)
    detect_eating = Column(Boolean, default=True)
    display_zone = Column(Text, nullable=True)  # JSON polygon for display case ROI
    
    status = Column(String, default="offline") # offline, online, error
    last_seen = Column(DateTime, nullable=True)
    
    events = relationship("Event", back_populates="camera", cascade="all, delete-orphan")

class Visitor(Base):
    __tablename__ = "visitors"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    visit_count = Column(Integer, default=1)
    
    face_embedding = Column(Text, nullable=True) # Store as JSON array of floats for sqlite simplicity or BLOB
    face_snapshot = Column(String, nullable=True)
    is_flagged = Column(Boolean, default=False)
    is_employee = Column(Boolean, default=False)
    
    events = relationship("Event", back_populates="visitor")

class PassengerCount(Base):
    __tablename__ = "passenger_counts"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String, ForeignKey("cameras.id"))
    date = Column(DateTime, default=datetime.utcnow)
    door_label = Column(String) # e.g. "Front Door", "Rear Door"
    count_in = Column(Integer, default=0)
    count_out = Column(Integer, default=0)

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, index=True)
    camera_id = Column(String, ForeignKey("cameras.id"))
    visitor_id = Column(String, ForeignKey("visitors.id"), nullable=True)
    event_type = Column(String) # person_detected, fight_suspected, camera_offline
    confidence = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    snapshot_path = Column(String, nullable=True)
    clip_path = Column(String, nullable=True)
    
    meta_json = Column(Text, nullable=True)
    camera = relationship("Camera", back_populates="events")
    visitor = relationship("Visitor", back_populates="events")
    deliveries = relationship("WebhookDelivery", cascade="all, delete-orphan", backref="event")

class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(String, primary_key=True, index=True)
    hook_type = Column(String, default="http")
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

class GlobalSetting(Base):
    __tablename__ = "global_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(String)
    description = Column(String, nullable=True)
