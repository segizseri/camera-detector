from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Bus, Camera
from pydantic import BaseModel
from typing import List, Optional
import uuid

router = APIRouter()

class BusCreate(BaseModel):
    name: str
    license_plate: Optional[str] = None

class BusUpdate(BaseModel):
    name: Optional[str] = None
    license_plate: Optional[str] = None

@router.get("/")
def get_buses(db: Session = Depends(get_db)):
    return db.query(Bus).all()

@router.post("/")
def create_bus(bus: BusCreate, db: Session = Depends(get_db)):
    new_bus = Bus(
        id=str(uuid.uuid4()),
        name=bus.name,
        license_plate=bus.license_plate
    )
    db.add(new_bus)
    db.commit()
    db.refresh(new_bus)
    return new_bus

@router.get("/{bus_id}")
def get_bus(bus_id: str, db: Session = Depends(get_db)):
    bus = db.query(Bus).filter(Bus.id == bus_id).first()
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    return bus

@router.patch("/{bus_id}")
def update_bus(bus_id: str, update: BusUpdate, db: Session = Depends(get_db)):
    bus = db.query(Bus).filter(Bus.id == bus_id).first()
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    
    if update.name is not None:
        bus.name = update.name
    if update.license_plate is not None:
        bus.license_plate = update.license_plate
        
    db.commit()
    return bus

@router.post("/{bus_id}/link-camera/{camera_id}")
def link_camera(bus_id: str, camera_id: str, db: Session = Depends(get_db)):
    bus = db.query(Bus).filter(Bus.id == bus_id).first()
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    cam.bus_id = bus_id
    db.commit()
    return {"status": "linked"}

@router.delete("/{bus_id}")
def delete_bus(bus_id: str, db: Session = Depends(get_db)):
    bus = db.query(Bus).filter(Bus.id == bus_id).first()
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    
    # Unlink cameras instead of deleting them
    for cam in bus.cameras:
        cam.bus_id = None
        
    db.delete(bus)
    db.commit()
    return {"status": "deleted"}
