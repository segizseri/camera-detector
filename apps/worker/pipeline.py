import cv2
import time
import queue
import threading
import uuid
from collections import deque
from datetime import datetime
from libs.database import SessionLocal
from libs.models import Event, Camera
from libs.rules import PersonDetector, AIActionDetector, PassengerCounter
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
        self.action_det = AIActionDetector(camera_id)
        self.passenger_counter = PassengerCounter(camera_id)
        
        self.last_sync_time = 0
        self.last_db_save = 0
        self.last_res = None
        self.counting_config = None
        self.detect_fights = True
        self.detect_bullying = True
        self.detect_theft = True
        self.detect_passengers = True
        self.detect_shoplifting = True
        self.display_zone = None
        
        self.ingest_thread = threading.Thread(target=self._ingest_loop, daemon=True)
        self.ingest_thread.start()

    def get_latest_frame(self):
        try:
            return self.frame_queue.get_nowait()
        except queue.Empty:
            return None

    def _ingest_loop(self):
        import os
        while self.running:
            # Reconnect logic
            print(f"[{self.camera_id}] Connecting to RTSP...")
            # Use TCP for stability as requested
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
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
            # Increased backoff for 404/connection errors to reduce NVR load and log spam
            time.sleep(10)

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

    def handle_ai_results(self, bboxes, keypoints, res, frame, timestamp):
        # bboxes: list of predictions from YOLO [x1, y1, x2, y2, conf, cls]
        # keypoints: numpy array [N, 17, 3]
        has_person, n_people = self.person_det.check_alert(bboxes)
        action_class, action_prob = self.action_det.add_frame(bboxes, keypoints, timestamp)
        
        # Passenger Counting
        if self.detect_passengers:
            ids = res.boxes.id.cpu().numpy().tolist() if res.boxes.id is not None else None
            if ids:
                h, w = frame.shape[:2]
                # Normalize boxes for the counter
                norm_boxes = []
                for b in bboxes:
                    norm_boxes.append([b[0]/w, b[1]/h, b[2]/w, b[3]/h])
                self.passenger_counter.update(norm_boxes, ids, self.counting_config)
        
        # Store for snapshot drawing
        self.last_res = res
        
        now = time.time()
        
        # 1: Fight, 2: Bullying, 3: Theft
        if action_class > 0:
            # Check feature flags
            if action_class == 1 and not self.detect_fights: action_class = 0
            if action_class == 2 and not self.detect_bullying: action_class = 0
            if action_class == 3 and not self.detect_theft: action_class = 0
            if action_class == 4 and not self.detect_shoplifting: action_class = 0
            
            if action_class > 0 and action_prob > self.action_det.thresholds.get(action_class, 0.6):
                
                # Check Theft Zone
                # ROI check for cash register theft (class 3)
                if action_class == 3 and hasattr(self, 'theft_zone') and self.theft_zone:
                    try:
                        import json, numpy as np, cv2
                        zone_pts = json.loads(self.theft_zone)
                        if len(zone_pts) >= 3:
                            h, w = frame.shape[:2]
                            contour = np.array([[[int(p[0]*w), int(p[1]*h)]] for p in zone_pts], dtype=np.int32)
                            
                            is_inside = False
                            for box in bboxes:
                                cx = (box[0] + box[2]) / 2.0
                                cy = (box[1] + box[3]) / 2.0
                                if cv2.pointPolygonTest(contour, (float(cx), float(cy)), False) >= 0:
                                    is_inside = True
                                    break
                                    
                            if not is_inside:
                                return # Skip detection if out of zone!
                    except Exception as e:
                        print(f"Error evaluating theft zone ROI: {e}")

                # ROI check for display case shoplifting (class 4)
                if action_class == 4 and hasattr(self, 'display_zone') and self.display_zone:
                    try:
                        import json, numpy as np, cv2
                        zone_pts = json.loads(self.display_zone)
                        if len(zone_pts) >= 3:
                            h, w = frame.shape[:2]
                            contour = np.array([[[int(p[0]*w), int(p[1]*h)]] for p in zone_pts], dtype=np.int32)
                            
                            is_inside = False
                            for box in bboxes:
                                cx = (box[0] + box[2]) / 2.0
                                cy = (box[1] + box[3]) / 2.0
                                if cv2.pointPolygonTest(contour, (float(cx), float(cy)), False) >= 0:
                                    is_inside = True
                                    break
                                    
                            if not is_inside:
                                return # Skip detection if out of display zone!
                    except Exception as e:
                        print(f"Error evaluating display zone ROI: {e}")

                if now - self.action_det.last_alerts.get(action_class, 0) > self.action_det.cooldowns.get(action_class, 30):
                    self.action_det.last_alerts[action_class] = now
                    
                    event_types = {1: "fight_suspected", 2: "bullying_suspected", 3: "theft_suspected", 4: "shoplifting_suspected"}
                    event_type = event_types[action_class]
                    self._trigger_event(event_type, float(action_prob), res, frame)
            
        # Update camera status periodically
        if now - self.last_sync_time > 10:
            self.last_sync_time = now
            self._sync_and_status()
            
        # Save counts to DB periodically (every 60 seconds or on exit)
        if now - self.last_db_save > 60:
            self.last_db_save = now
            self._save_passenger_stats()

    def _save_passenger_stats(self):
        from libs.models import PassengerCount
        from datetime import datetime, date
        db = SessionLocal()
        try:
            today = date.today()
            for label, stats in self.passenger_counter.counts.items():
                # Find existing record for today or create new
                # For simplicity, we use start of day as the 'date' field or just aggregate
                # In a real app, we might want hourly bins
                record = db.query(PassengerCount).filter(
                    PassengerCount.camera_id == self.camera_id,
                    PassengerCount.door_label == label
                    # Filter by date... (simplified here)
                ).order_by(PassengerCount.date.desc()).first()
                
                # If record is from today, update it, else create new
                if record and record.date.date() == today:
                    record.count_in = stats['in']
                    record.count_out = stats['out']
                else:
                    new_record = PassengerCount(
                        camera_id=self.camera_id,
                        door_label=label,
                        count_in=stats['in'],
                        count_out=stats['out'],
                        date=datetime.now()
                    )
                    db.add(new_record)
            db.commit()
        except Exception as e:
            print(f"Error saving passenger stats: {e}")
        finally:
            db.close()

    def _sync_and_status(self):
        from libs.models import GlobalSetting
        db = SessionLocal()
        try:
            # Status update
            cam = db.query(Camera).filter(Camera.id == self.camera_id).first()
            if cam:
                cam.status = "online"
                cam.last_seen = datetime.utcnow()
                self.theft_zone = cam.theft_zone
                self.display_zone = cam.display_zone
                self.counting_config = cam.counting_config
                self.detect_fights = cam.detect_fights
                self.detect_bullying = cam.detect_bullying
                self.detect_theft = cam.detect_theft
                self.detect_passengers = cam.detect_passengers
                self.detect_shoplifting = cam.detect_shoplifting
            
            # Settings sync
            settings = {s.key: s.value for s in db.query(GlobalSetting).all()}
            if 'fight_sensitivity' in settings:
                s = settings['fight_sensitivity']
                mapping = {'low': 0.8, 'medium': 0.6, 'high': 0.4}
                self.action_det.thresholds[1] = mapping.get(s, 0.6)
            
            db.commit()
        except Exception as e:
            print(f"Error in sync: {e}")
        finally:
            db.close()

    def _trigger_event(self, event_type, conf, res, frame):
        import cv2
        import os
        event_id = str(uuid.uuid4())
        
        # Snapshot
        snap_name = f"{event_id}.jpg"
        snap_path = os.path.join(settings.SNAPSHOTS_DIR, snap_name)
        
        # Draw skeletons and boxes using YOLO's plot()
        draw_frame = res.plot()
        
        # Draw Russian event type label on frame (using Pillow)
        try:
            from PIL import Image, ImageDraw, ImageFont
            pil_img = Image.fromarray(cv2.cvtColor(draw_frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)
            
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            try:
                font = ImageFont.truetype(font_path, 40)
            except:
                font = ImageFont.load_default()
                
            label_map = {
                'person_detected': 'ОБНАРУЖЕН ЧЕЛОВЕК',
                'fight_suspected': 'ПОДОЗРЕНИЕ НА ДРАКУ',
                'bullying_suspected': 'ПОДОЗРЕНИЕ НА БУЛЛИНГ',
                'theft_suspected': 'ПОДОЗРЕНИЕ НА КРАЖУ',
                'shoplifting_suspected': 'ПОДОЗРЕНИЕ НА КРАЖУ ИЗ ВИТРИНЫ'
            }
            label = label_map.get(event_type, event_type).upper()
            
            draw.text((52, 52), f"СОБЫТИЕ: {label}", font=font, fill=(0,0,0))
            draw.text((50, 50), f"СОБЫТИЕ: {label}", font=font, fill=(255,0,0))
            
            draw_frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"Failed to draw Russian text on pose-frame: {e}")
            cv2.putText(draw_frame, f"EVENT: {event_type}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

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
