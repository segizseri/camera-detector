from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Visitor, Event
from typing import List, Dict, Any, Optional
import math

router = APIRouter()

class VisitorUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    is_flagged: Optional[bool] = None
    is_employee: Optional[bool] = None

class PaginatedVisitors(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    page: int
    pages: int

@router.get("/", response_model=PaginatedVisitors)
def get_visitors(
    status_filter: str = Query("all"),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1),
    db: Session = Depends(get_db)
):
    query = db.query(Visitor)
    
    if status_filter == "employee":
        query = query.filter(Visitor.is_employee == True)
    elif status_filter == "flagged":
        query = query.filter(Visitor.is_employee == False, Visitor.is_flagged == True)
    elif status_filter == "normal":
        query = query.filter(Visitor.is_employee == False, Visitor.is_flagged == False)
    else:  # "all" - show all non-employees
        query = query.filter(Visitor.is_employee == False)
        
    total = query.count()
    pages = math.ceil(total / limit) if total > 0 else 1
    
    visitors = query.order_by(Visitor.last_seen.desc()).offset((page - 1) * limit).limit(limit).all()
    
    items = []
    for v in visitors:
        items.append({
            "id": v.id,
            "name": v.name,
            "notes": v.notes,
            "first_seen": v.first_seen.isoformat() if v.first_seen else None,
            "last_seen": v.last_seen.isoformat() if v.last_seen else None,
            "visit_count": v.visit_count,
            "face_snapshot": v.face_snapshot,
            "is_flagged": v.is_flagged,
            "is_employee": v.is_employee
        })
        
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages
    }

@router.get("/{visitor_id}")
def get_visitor(visitor_id: str, db: Session = Depends(get_db)):
    v = db.query(Visitor).filter(Visitor.id == visitor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Visitor not found")
        
    return {
        "id": v.id,
        "name": v.name,
        "notes": v.notes,
        "first_seen": v.first_seen.isoformat() if v.first_seen else None,
        "last_seen": v.last_seen.isoformat() if v.last_seen else None,
        "visit_count": v.visit_count,
        "face_snapshot": v.face_snapshot,
        "is_flagged": v.is_flagged,
        "is_employee": v.is_employee
    }

@router.get("/{visitor_id}/events")
def get_visitor_events(visitor_id: str, db: Session = Depends(get_db)):
    events = db.query(Event).filter(Event.visitor_id == visitor_id).order_by(Event.timestamp.desc()).limit(100).all()
    res = []
    for e in events:
        res.append({
            "id": e.id,
            "event_type": e.event_type,
            "confidence": e.confidence,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "snapshot_path": e.snapshot_path,
            "camera_name": e.camera.name if e.camera else "Unknown"
        })
    return res

@router.put("/{visitor_id}")
def update_visitor(visitor_id: str, payload: VisitorUpdate, db: Session = Depends(get_db)):
    visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")
    
    if payload.name is not None:
        visitor.name = payload.name
    if payload.notes is not None:
        visitor.notes = payload.notes
    if payload.is_flagged is not None:
        visitor.is_flagged = payload.is_flagged
    if payload.is_employee is not None:
        visitor.is_employee = payload.is_employee
        
    db.commit()
    return {"status": "ok"}

@router.delete("/{visitor_id}")
def delete_visitor(visitor_id: str, db: Session = Depends(get_db)):
    visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")
    db.delete(visitor)
    db.commit()
    return {"status": "ok"}
