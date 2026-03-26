import cv2
import time
import queue
import threading
import uuid
from collections import deque
from datetime import datetime
from libs.database import SessionLocal
from libs.models import Event, Camera
from libs.rules import PersonDetector, FightDetector
from libs.webhooks import queue_webhook
from libs.config import settings

class CameraPipeline:
    def __init__(self, camera_id: str, rtsp_url: str, fps_limit: int):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.fps_limit = fps_limit
        self.interval = 1.0 / (fps_limit if fps_limit > 0 else 5)
        
        self.frame_queue = queue.Queue(maxsize=2) # Drop frames if AI is slow
        self.ring_buffer = deque(maxlen=fps_limit * 12) # ~12 seconds history (6s before, 6s after)
        
        self.running = True
        self.person_det = PersonDetector(camera_id)
        self.fight_det = FightDetector(camera_id)
        
        self.ingest_thread = threading.Thread(target=self._ingest_loop, daemon=True)
        self.ingest_thread.start()

    def get_latest_frame(self):
        try:
            return self.frame_queue.get_nowait()
        except queue.Empty:
            return None

    def _ingest_loop(self):
        while self.running:
            # Reconnect logic
            print(f"[{self.camera_id}] Connecting to RTSP...")
            # Use TCP for stability as requested
            os_env = {"OPENCV_FFMPEG_CAPTURE_OPTIONS": "rtsp_transport;tcp"}
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            
            if not cap.isOpened():
                self._record_offline_event()
                time.sleep(5)
                continue
            
            last_frame_time = time.time()
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Keep minimum buffer to avoid delay
            
            err_count = 0
            while self.running and cap.isOpened():
                ret, frame = cap.read()
                now = time.time()
                
                if not ret:
                    err_count += 1
                    if err_count > 10:
                        break # Reconnect
                    continue
                err_count = 0
                
                self.ring_buffer.append((now, frame)) # Store for clips
                
                # FPS Limiting
                if now - last_frame_time >= self.interval:
                    last_frame_time = now
                    # Send to AI Queue, drop if full
                    try:
                        self.frame_queue.put_nowait((now, frame))
                    except queue.Full:
                        pass # Drop frame due to AI overload
            
            cap.release()
            self._record_offline_event()
            time.sleep(2)

    def _record_offline_event(self):
        # We should only fire "offline" every once in a while
        db = SessionLocal()
        cam = db.query(Camera).filter(Camera.id == self.camera_id).first()
        if cam and cam.status != "offline":
            cam.status = "offline"
            evt = Event(id=str(uuid.uuid4()), camera_id=self.camera_id, event_type="camera_offline")
            db.add(evt)
            db.commit()
            queue_webhook(evt)
        db.close()

    def handle_ai_results(self, bboxes, frame, timestamp):
        # bboxes: list of predictions from YOLO [x1, y1, x2, y2, conf, cls]
        # Bytetrack logic could be applied here if full model tracking is used.
        has_person, n_people = self.person_det.check_alert(bboxes)
        fight_score = self.fight_det.add_frame(bboxes, timestamp)
        
        now = time.time()
        
        if has_person and (now - self.person_det.last_alert_time > self.person_det.cooldown):
            self.person_det.last_alert_time = now
            self._trigger_event("person_detected", 1.0, frame)
            
        if fight_score > self.fight_det.fight_threshold and (now - self.fight_det.last_alert_time > self.fight_det.cooldown):
            self.fight_det.last_alert_time = now
            self._trigger_event("fight_suspected", float(fight_score), frame)
            
        # Update camera status purely to online based on frame ingestion + AI processed
        db = SessionLocal()
        cam = db.query(Camera).filter(Camera.id == self.camera_id).first()
        if cam and cam.status != "online":
            cam.status = "online"
            cam.last_seen = datetime.utcnow()
            db.commit()
        db.close()

    def _trigger_event(self, event_type, conf, frame):
        import cv2
        import os
        event_id = str(uuid.uuid4())
        
        # Snapshot
        snap_name = f"{event_id}.jpg"
        snap_path = os.path.join(settings.SNAPSHOTS_DIR, snap_name)
        
        # Draw boxes on frame
        draw_frame = frame.copy()
        cv2.putText(draw_frame, f"EVENT: {event_type}", (50,50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)
        cv2.imwrite(snap_path, draw_frame)
        
        db = SessionLocal()
        evt = Event(
            id=event_id,
            camera_id=self.camera_id,
            event_type=event_type,
            confidence=conf,
            snapshot_path=snap_name
        )
        db.add(evt)
        db.commit()
        
        # Webhook
        queue_webhook(evt)
        
        db.close()
        
        # Sub-process or thread to generate clip from ring buffer
        # A simple method: dump all ring buffer frames and compile via ffmpeg
        # For an MVP, we skip the clip mp4 generation or do it async
        threading.Thread(target=self._generate_clip, args=(event_id,)).start()

    def _generate_clip(self, event_id):
        # Taking a snapshot of the ring buffer
        # wait 5 seconds to capture post-event frames
        time.sleep(5)
        frames_to_save = list(self.ring_buffer) # duplicate
        if not frames_to_save:
            return
            
        import os, cv2
        clip_name = f"{event_id}.mp4"
        clip_path = os.path.join(settings.CLIPS_DIR, clip_name)
        
        h, w = frames_to_save[0][1].shape[:2]
        fps = self.fps_limit if self.fps_limit > 0 else 5
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(clip_path, fourcc, float(fps), (w, h))
        
        for _, f in frames_to_save:
            out.write(f)
        out.release()
        
        # Update DB
        db = SessionLocal()
        evt = db.query(Event).filter(Event.id == event_id).first()
        if evt:
            evt.clip_path = clip_name
            db.commit()
        db.close()

    def stop(self):
        self.running = False
        self.ingest_thread.join()
