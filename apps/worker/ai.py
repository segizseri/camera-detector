import threading
import queue
import time
import torch
from ultralytics import YOLO
import ultralytics.nn.tasks

class AIWorker:
    def __init__(self):
        # Fix for PyTorch 2.6+ safe globals (WeightsUnpickler error)
        try:
            torch.serialization.add_safe_globals([ultralytics.nn.tasks.DetectionModel])
        except (AttributeError, NameError):
            pass

        self.model = YOLO("yolov8n-pose.pt")
        self.running = True
        self.pipelines = {}
        self.lock = threading.Lock()
        
        # Face recognition setup
        try:
            from facenet_pytorch import MTCNN, InceptionResnetV1
            self.mtcnn = MTCNN(keep_all=False, device='cpu', min_face_size=40)
            self.resnet = InceptionResnetV1(pretrained='vggface2').eval().to('cpu')
            self.face_enabled = True
            print("[Re-ID] ✅ Face recognition ENABLED (MTCNN + InceptionResnetV1)")
        except ImportError:
            print("[Re-ID] ❌ facenet-pytorch not installed. Face recognition disabled.")
            self.face_enabled = False
        except Exception as e:
            print(f"[Re-ID] ❌ Face recognition init error: {e}")
            self.face_enabled = False
            
        # track_id -> visitor_id mapping (cache)
        self.track_to_visitor = {}
        # track_id -> frame counter (retry face detection periodically)
        self._face_attempt_count = {}
        # Stats for logging
        self._face_stats = {"attempts": 0, "detections": 0, "new": 0, "recognized": 0}
        self._last_stats_log = 0

        
    def add_pipeline(self, pipeline):
        with self.lock:
            self.pipelines[pipeline.camera_id] = pipeline
            
    def remove_pipeline(self, camera_id):
        with self.lock:
            if camera_id in self.pipelines:
                del self.pipelines[camera_id]
                
    def loop(self):
        # AI Processing thread - iterates over pipelines continuously
        print("AI Worker Started with Pose Model.")
        if self.face_enabled:
            print("[Re-ID] Face recognition active - will process faces from camera feeds.")
        while self.running:
            processed_any = False
            
            with self.lock:
                cams = list(self.pipelines.values())
                
            for p in cams:
                if not getattr(p, 'ai_enabled', True):
                    continue
                    
                # Fetch frame
                try:
                    ts, frame = p.frame_queue.get_nowait()
                except queue.Empty:
                    continue
                
                # Inference with Tracking
                results = self.model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)
                res = results[0]
                
                # Results parsing
                # res.boxes.data -> [x1, y1, x2, y2, confidence, class]
                bboxes = res.boxes.data.cpu().numpy().tolist()
                keypoints = None
                if hasattr(res, 'keypoints') and res.keypoints is not None:
                    # keypoints.data -> [N, 17, 3] (x, y, conf)
                    keypoints = res.keypoints.data.cpu().numpy()
                
                # Dispatch back to pipeline to trigger events
                # Pass 'res' as well if needed for plot() or other YOLO tools
                
                ids = res.boxes.id.cpu().numpy().tolist() if res.boxes.id is not None else []
                if self.face_enabled and len(ids) > 0:
                    self._process_faces(frame, bboxes, ids, res)
                    
                p.handle_ai_results(bboxes, keypoints, res, frame, ts, self.track_to_visitor)
                processed_any = True
                
            if not processed_any:
                time.sleep(0.01) # Avoid CPU spin
    
    def stop(self):
        self.running = False

    def _process_faces(self, frame, bboxes, ids, res):
        from libs.database import SessionLocal
        from libs.models import Visitor
        import uuid
        import os
        from datetime import datetime
        from libs.config import settings
        import numpy as np
        import cv2
        import json
        from PIL import Image

        now = time.time()
        
        # Periodic stats logging (every 60 seconds)
        if now - self._last_stats_log > 60:
            self._last_stats_log = now
            s = self._face_stats
            print(f"[Re-ID] Stats: {s['attempts']} attempts, {s['detections']} faces detected, "
                  f"{s['new']} new visitors, {s['recognized']} recognized | "
                  f"Cache: {len(self.track_to_visitor)} tracked, "
                  f"{len(self._face_attempt_count)} pending")

        # Build a map of track_id -> bbox from the result
        # This avoids index mismatch issues between bboxes and ids
        track_to_box = {}
        if res.boxes.id is not None:
            box_ids = res.boxes.id.cpu().numpy().tolist()
            box_xyxy = res.boxes.xyxy.cpu().numpy().tolist()
            for idx, tid in enumerate(box_ids):
                track_to_box[int(tid)] = box_xyxy[idx]

        db = SessionLocal()
        try:
            for track_id in ids:
                tid = int(track_id)
                
                # Already identified this track
                if tid in self.track_to_visitor:
                    continue
                
                # Retry cooldown: try every 15 frames, give up after 150 attempts
                attempt_num = self._face_attempt_count.get(tid, 0)
                if attempt_num > 150:
                    continue  # Give up on this track
                if attempt_num > 0 and attempt_num % 15 != 0:
                    self._face_attempt_count[tid] = attempt_num + 1
                    continue  # Skip this frame, retry later
                self._face_attempt_count[tid] = attempt_num + 1
                
                # Get bbox for this track_id
                box = track_to_box.get(tid)
                if box is None:
                    continue
                
                x1, y1, x2, y2 = map(int, box[:4])
                body_h = y2 - y1
                body_w = x2 - x1
                
                if body_h < 40 or body_w < 20:
                    continue  # Person too small
                
                self._face_stats["attempts"] += 1
                
                # Strategy 1: Take top 50% of body (more generous than 30%)
                y2_face = min(y2, y1 + int(body_h * 0.5))
                crop = frame[max(0, y1):y2_face, max(0, x1):x2]
                
                face = self._try_detect_face(crop, cv2, Image)
                
                # Strategy 2: If failed, try wider crop with padding
                if face is None:
                    pad = int(body_w * 0.2)
                    fh, fw = frame.shape[:2]
                    cx1 = max(0, x1 - pad)
                    cy1 = max(0, y1 - int(body_h * 0.05))
                    cx2 = min(fw, x2 + pad)
                    cy2 = min(fh, y1 + int(body_h * 0.55))
                    crop = frame[cy1:cy2, cx1:cx2]
                    face = self._try_detect_face(crop, cv2, Image)
                
                if face is None:
                    continue
                
                self._face_stats["detections"] += 1
                
                # Get embedding
                emb = self.resnet(face.unsqueeze(0)).detach().numpy()[0]
                
                # Compare with DB
                visitors = db.query(Visitor).all()
                best_match = None
                best_score = -1
                
                for v in visitors:
                    if v.face_embedding:
                        try:
                            v_emb = np.array(json.loads(v.face_embedding))
                            # Cosine similarity
                            score = np.dot(emb, v_emb) / (np.linalg.norm(emb) * np.linalg.norm(v_emb) + 1e-8)
                            if score > best_score:
                                best_score = score
                                best_match = v
                        except Exception:
                            continue
                
                if best_match and best_score > 0.70:
                    # Match found
                    self.track_to_visitor[tid] = best_match.id
                    # Remove from retry tracking
                    self._face_attempt_count.pop(tid, None)
                    # Update last seen
                    if (datetime.utcnow() - best_match.last_seen).total_seconds() > 3600:
                        best_match.visit_count += 1
                    best_match.last_seen = datetime.utcnow()
                    db.commit()
                    self._face_stats["recognized"] += 1
                    print(f"[Re-ID] ✅ Recognized visitor {best_match.id[:8]}... (Score {best_score:.2f}, visits: {best_match.visit_count})")
                else:
                    # New visitor
                    v_id = str(uuid.uuid4())
                    
                    # Save face snapshot (save the better crop)
                    snap_name = f"visitor_{v_id}.jpg"
                    snap_path = os.path.join(settings.SNAPSHOTS_DIR, snap_name)
                    # Save larger crop for better snapshot quality
                    save_crop = frame[max(0, y1):min(y2, y1 + int(body_h * 0.5)), max(0, x1):x2]
                    if save_crop.size > 0:
                        cv2.imwrite(snap_path, save_crop)
                    
                    new_v = Visitor(
                        id=v_id,
                        face_embedding=json.dumps(emb.tolist()),
                        face_snapshot=snap_name
                    )
                    db.add(new_v)
                    db.commit()
                    self.track_to_visitor[tid] = v_id
                    # Remove from retry tracking
                    self._face_attempt_count.pop(tid, None)
                    self._face_stats["new"] += 1
                    print(f"[Re-ID] 🆕 New visitor created: {v_id[:8]}...")
        except Exception as e:
            import traceback
            print(f"[Re-ID] ❌ Face processing error: {e}")
            traceback.print_exc()
        finally:
            db.close()
        
        # Cleanup old track_ids from cache (prevent memory leak)
        active_tids = set(int(t) for t in ids)
        stale = [k for k in self._face_attempt_count if k not in active_tids]
        for k in stale:
            self._face_attempt_count.pop(k, None)

    def _try_detect_face(self, crop, cv2, Image):
        """Try to detect a face in a crop. Returns face tensor or None."""
        if crop.size == 0:
            return None
        
        h, w = crop.shape[:2]
        
        # Upscale small crops - MTCNN needs at least ~80px to detect faces
        min_dim = 160
        if h < min_dim or w < min_dim:
            scale = max(min_dim / h, min_dim / w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # Convert BGR to RGB for MTCNN
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(crop_rgb)
        
        try:
            face = self.mtcnn(img)
            return face
        except Exception:
            return None
