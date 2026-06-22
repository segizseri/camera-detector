from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Visitor
from typing import List, Dict, Any, Optional

router = APIRouter()

class VisitorUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    is_flagged: Optional[bool] = None

@router.get("/", response_model=List[Dict[str, Any]])
def get_visitors(status_filter: str = Query("all"), db: Session = Depends(get_db)):
    query = db.query(Visitor)
    
    if status_filter == "flagged":
        query = query.filter(Visitor.is_flagged == True)
    elif status_filter == "normal":
        query = query.filter(Visitor.is_flagged == False)
        
    visitors = query.order_by(Visitor.last_seen.desc()).all()
    res = []
    for v in visitors:
        res.append({
            "id": v.id,
            "name": v.name,
            "notes": v.notes,
            "first_seen": v.first_seen.isoformat() if v.first_seen else None,
            "last_seen": v.last_seen.isoformat() if v.last_seen else None,
            "visit_count": v.visit_count,
            "face_snapshot": v.face_snapshot,
            "is_flagged": v.is_flagged
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
