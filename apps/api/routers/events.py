from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Event, Camera
import uuid
from datetime import datetime
from libs.webhooks import queue_webhook

router = APIRouter()

@router.get("/")
def get_events(db: Session = Depends(get_db)):
    events = db.query(Event).order_by(Event.timestamp.desc()).limit(100).all()
    return events

@router.delete("/all")
def delete_all_events(db: Session = Depends(get_db)):
    db.query(Event).delete()
    db.commit()
    return {"message": "All events cleared"}

@router.post("/test-trigger")
def test_trigger(camera_id: str, event_type: str = "fight_suspected", db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
        
    evt = Event(
        id=str(uuid.uuid4()),
        camera_id=camera_id,
        event_type=event_type,
        confidence=0.99,
        timestamp=datetime.utcnow(),
        meta_json='{"is_test": true}'
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    
    # Trigger webhook
    queue_webhook(evt)
    
    return evt
