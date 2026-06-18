from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Visitor
from typing import List, Dict, Any

router = APIRouter()

@router.get("/", response_model=List[Dict[str, Any]])
def get_visitors(db: Session = Depends(get_db)):
    visitors = db.query(Visitor).order_by(Visitor.last_seen.desc()).all()
    res = []
    for v in visitors:
        res.append({
            "id": v.id,
            "first_seen": v.first_seen.isoformat() if v.first_seen else None,
            "last_seen": v.last_seen.isoformat() if v.last_seen else None,
            "visit_count": v.visit_count,
            "face_snapshot": v.face_snapshot,
            "is_flagged": v.is_flagged
        })
    return res

@router.delete("/{visitor_id}")
def delete_visitor(visitor_id: str, db: Session = Depends(get_db)):
    visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")
    db.delete(visitor)
    db.commit()
    return {"status": "ok"}
