import threading
import time
import requests
import hmac
import hashlib
import json
from datetime import datetime
from libs.database import SessionLocal
from libs.models import Webhook

def send_webhook(event):
    db = SessionLocal()
    try:
        webhooks = db.query(Webhook).filter(Webhook.enabled == True).all()
        if not webhooks:
            return
            
        payload = {
            "event_id": event.id,
            "event_type": event.event_type,
            "camera_id": event.camera_id,
            "timestamp": event.timestamp.isoformat(),
            "confidence": event.confidence,
            "snapshot_url": f"/media/snapshots/{event.snapshot_path}" if event.snapshot_path else None,
        }
        raw_body = json.dumps(payload).encode('utf-8')
        
        for hooks in webhooks:
            try:
                signature = hmac.new(hooks.secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
                headers = {
                    "Content-Type": "application/json",
                    "X-Signature": signature
                }
                
                res = requests.post(hooks.url, data=raw_body, headers=headers, timeout=5)
                # In a real app we'd log this delivery attempt to WebhookDelivery
                print(f"Webhook {hooks.url} returned {res.status_code}")
            except Exception as e:
                print(f"Failed to send webhook {hooks.url}: {e}")
    finally:
        db.close()

def queue_webhook(event):
    # Simply fire and forget for MVP
    t = threading.Thread(target=send_webhook, args=(event,))
    t.start()
