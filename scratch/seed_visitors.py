"""Seed test visitors into the database."""
import sys
import os
sys.path.insert(0, '/app')

from libs.database import SessionLocal
from libs.models import Visitor, Event
from datetime import datetime, timedelta
import uuid
import json

db = SessionLocal()

# Clear existing test visitors
existing = db.query(Visitor).filter(Visitor.id.like("test-%")).all()
for v in existing:
    db.delete(v)
db.commit()
print(f"Cleared {len(existing)} existing test visitors")

visitors_data = [
    {
        "id": "test-001-" + str(uuid.uuid4())[:8],
        "face_snapshot": "visitor_test_1.jpg",
        "first_seen": datetime.utcnow() - timedelta(days=14),
        "last_seen": datetime.utcnow() - timedelta(hours=2),
        "visit_count": 12,
        "is_flagged": False,
    },
    {
        "id": "test-002-" + str(uuid.uuid4())[:8],
        "face_snapshot": "visitor_test_2.jpg",
        "first_seen": datetime.utcnow() - timedelta(days=45),
        "last_seen": datetime.utcnow() - timedelta(minutes=30),
        "visit_count": 87,
        "is_flagged": False,
    },
    {
        "id": "test-003-" + str(uuid.uuid4())[:8],
        "face_snapshot": "visitor_test_3.jpg",
        "first_seen": datetime.utcnow() - timedelta(days=3),
        "last_seen": datetime.utcnow() - timedelta(hours=1),
        "visit_count": 5,
        "is_flagged": True,  # Flagged - caught shoplifting
    },
    {
        "id": "test-004-" + str(uuid.uuid4())[:8],
        "face_snapshot": "visitor_test_4.jpg",
        "first_seen": datetime.utcnow() - timedelta(days=60),
        "last_seen": datetime.utcnow() - timedelta(days=2),
        "visit_count": 34,
        "is_flagged": False,
    },
    {
        "id": "test-005-" + str(uuid.uuid4())[:8],
        "face_snapshot": "visitor_test_5.jpg",
        "first_seen": datetime.utcnow() - timedelta(days=7),
        "last_seen": datetime.utcnow() - timedelta(hours=4),
        "visit_count": 8,
        "is_flagged": False,
    },
    {
        "id": "test-006-" + str(uuid.uuid4())[:8],
        "face_snapshot": "visitor_test_6.jpg",
        "first_seen": datetime.utcnow() - timedelta(days=1),
        "last_seen": datetime.utcnow() - timedelta(minutes=15),
        "visit_count": 3,
        "is_flagged": True,  # Flagged - suspected theft
    },
]

for vd in visitors_data:
    # Create a dummy face embedding (512 floats for InceptionResnetV1)
    import random
    random.seed(hash(vd["id"]))
    dummy_embedding = [random.gauss(0, 0.1) for _ in range(512)]
    
    visitor = Visitor(
        id=vd["id"],
        face_snapshot=vd["face_snapshot"],
        face_embedding=json.dumps(dummy_embedding),
        first_seen=vd["first_seen"],
        last_seen=vd["last_seen"],
        visit_count=vd["visit_count"],
        is_flagged=vd["is_flagged"],
    )
    db.add(visitor)
    status = "🔴 FLAGGED" if vd["is_flagged"] else "🟢 OK"
    print(f"  Added: {vd['id'][:14]}... | Visits: {vd['visit_count']:>3} | {status}")

db.commit()
db.close()
print(f"\n✅ Seeded {len(visitors_data)} test visitors successfully!")
