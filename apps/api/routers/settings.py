from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from libs.database import SessionLocal
from libs.models import GlobalSetting
from pydantic import BaseModel

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SettingUpdate(BaseModel):
    settings: Dict[str, str]

@router.get("/")
async def get_settings(db: Session = Depends(get_db)):
    settings = db.query(GlobalSetting).all()
    # If empty, seed some defaults
    if not settings:
        defaults = [
            GlobalSetting(key="retention_days", value="7", description="How many days to keep events"),
            GlobalSetting(key="min_confidence", value="0.65", description="Minimum AI confidence threshold"),
            GlobalSetting(key="fight_sensitivity", value="medium", description="Sensitivity for fight detection (low, medium, high)")
        ]
        db.add_all(defaults)
        db.commit()
        settings = defaults
    
    return {s.key: s.value for s in settings}

@router.post("/update")
async def update_settings(update: SettingUpdate, db: Session = Depends(get_db)):
    for key, value in update.settings.items():
        s = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
        if s:
            s.value = value
        else:
            s = GlobalSetting(key=key, value=value)
            db.add(s)
    db.commit()
    return {"status": "ok"}
