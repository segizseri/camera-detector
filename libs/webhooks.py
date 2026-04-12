import threading
import time
import requests
import hmac
import hashlib
import json
from datetime import datetime
from libs.database import SessionLocal
from libs.models import Webhook

def send_webhook(event_data):
    db = SessionLocal()
    try:
        webhooks = db.query(Webhook).filter(Webhook.enabled == True).all()
        if not webhooks:
            return
            
        raw_body = json.dumps(event_data).encode('utf-8')
        
        for hooks in webhooks:
            try:
                signature = hmac.new(hooks.secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
                headers = {
                    "Content-Type": "application/json",
                    "X-Signature": signature
                }
                
                res = requests.post(hooks.url, data=raw_body, headers=headers, timeout=5)
                print(f"Webhook {hooks.url} returned {res.status_code}")
            except Exception as e:
                print(f"Failed to send webhook {hooks.url}: {e}")
    finally:
        db.close()

def queue_webhook(event):
    # Serializing event before threading to avoid DetachedInstanceError
    label_map = {
        'person_detected': 'Обнаружен человек',
        'fight_suspected': 'Подозрение на драку',
        'theft_suspected': 'Подозрение на кражу',
        'camera_offline': 'Камера отключена'
    }
    
    event_data = {
        "event_id": event.id,
        "event_type": event.event_type,
        "event_type_ru": label_map.get(event.event_type, event.event_type),
        "camera_id": event.camera_id,
        "timestamp": event.timestamp.isoformat(),
        "confidence": event.confidence,
        "snapshot_url": f"/media/snapshots/{event.snapshot_path}" if event.snapshot_path else None,
    }
    t = threading.Thread(target=send_webhook, args=(event_data,))
    t.start()

def send_test_webhook(hook_id):
    db = SessionLocal()
    try:
        hook = db.query(Webhook).filter(Webhook.id == hook_id).first()
        if not hook:
            return
            
        payload = {
            "event_id": "test-uuid-123",
            "event_type": "test_connection",
            "camera_id": "none",
            "timestamp": datetime.now().isoformat(),
            "confidence": 1.0,
            "snapshot_url": None,
            "is_test": True
        }
        raw_body = json.dumps(payload).encode('utf-8')
        signature = hmac.new(hook.secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature
        }
        
        res = requests.post(hook.url, data=raw_body, headers=headers, timeout=5)
        print(f"Test Webhook {hook.url} returned {res.status_code}")
        return res.status_code
    finally:
        db.close()
