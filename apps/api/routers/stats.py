from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import PassengerCount
from datetime import datetime, date
from typing import List

router = APIRouter()

@router.get("/passengers")
def get_passenger_stats(camera_id: str = None, date_str: str = None, db: Session = Depends(get_db)):
    query = db.query(PassengerCount)
    
    if camera_id:
        query = query.filter(PassengerCount.camera_id == camera_id)
    
    # Filter by date if provided, else use today
    target_date = date.today()
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except:
            pass
            
    # Simple filtering by day (assuming the date field stores datetime)
    results = query.all()
    # In a real app we'd use SQL date() function, but for SQLite/MVP we'll filter here or use between
    
    filtered = [r for r in results if r.date.date() == target_date]
    return filtered
