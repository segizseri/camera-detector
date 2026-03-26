from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Event

router = APIRouter()

@router.get("/")
def get_events(db: Session = Depends(get_db)):
    events = db.query(Event).order_by(Event.timestamp.desc()).limit(100).all()
    return events
