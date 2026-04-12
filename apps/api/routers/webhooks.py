from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from libs.database import get_db
from libs.models import Webhook
from libs.schemas import WebhookCreate, WebhookUpdate
import uuid

router = APIRouter()

@router.get("/")
def get_webhooks(db: Session = Depends(get_db)):
    return db.query(Webhook).all()

@router.post("/")
def create_webhook(webhook: WebhookCreate, db: Session = Depends(get_db)):
    wh = Webhook(
        id=str(uuid.uuid4()),
        name=webhook.name,
        url=webhook.url,
        secret=webhook.secret,
        enabled=webhook.enabled
    )
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh

@router.patch("/{webhook_id}")
def update_webhook(webhook_id: str, update: WebhookUpdate, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
        
    if update.name is not None:
        wh.name = update.name
    if update.url is not None:
        wh.url = update.url
    if update.secret is not None:
        wh.secret = update.secret
    if update.enabled is not None:
        wh.enabled = update.enabled
        
    db.commit()
    db.refresh(wh)
    return wh

@router.delete("/{webhook_id}")
def delete_webhook(webhook_id: str, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
        
    db.delete(wh)
    db.commit()
    return {"status": "success"}
@router.post("/{webhook_id}/test")
def test_webhook(webhook_id: str):
    from libs.webhooks import send_test_webhook
    status_code = send_test_webhook(webhook_id)
    if status_code and status_code < 400:
        return {"status": "success", "http_code": status_code}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send test webhook. Server returned {status_code}")
