import threading
import queue
import time

# A recognised track is dropped from the visitor cache once it has not been seen for this long.
# ByteTrack gives up on a lost track much sooner and track ids are never reused, so an entry
# this old belongs to a person who has left.
VISITOR_CACHE_TTL_SECONDS = 120


class AIWorker:
    def __init__(self, tracker_factory=None):
        if tracker_factory is None:
            from libs.ai_models import PersonPoseTracker, load_pose_model
            # One YOLO model for all cameras (memory), but ByteTrack state per camera.
            self.model = load_pose_model()
            tracker_factory = lambda: PersonPoseTracker(self.model)
        self._new_tracker = tracker_factory
        self.running = True
        self.pipelines = {}
        # camera_id -> PersonPoseTracker; never shared, so track ids and LSTM sequences
        # cannot mix frames from different cameras.
        self.trackers = {}
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
            
        # (camera_id, track_id) -> visitor_id mapping (cache); track ids are per camera
        self.track_to_visitor = {}
        # (camera_id, track_id) -> last time a track in track_to_visitor was seen
        self._visitor_last_seen = {}
        self._last_visitor_prune = 0
        # (camera_id, track_id) -> frame counter (retry face detection periodically)
        self._face_attempt_count = {}
        # Stats for logging
        self._face_stats = {"attempts": 0, "detections": 0, "new": 0, "recognized": 0}
        self._last_stats_log = 0
        self._last_scanning_enabled_check = 0
        self._visitor_scanning_enabled = True

        
    def add_pipeline(self, pipeline):
        tracker = self._new_tracker()
        with self.lock:
            self.pipelines[pipeline.camera_id] = pipeline
            self.trackers[pipeline.camera_id] = tracker
            self._forget_camera(pipeline.camera_id)
            
    def remove_pipeline(self, camera_id):
        with self.lock:
            self.pipelines.pop(camera_id, None)
            self.trackers.pop(camera_id, None)
            self._forget_camera(camera_id)

    def _forget_camera(self, camera_id):
        # Caller holds self.lock. The AI thread writes single keys without it, so iterate a copy.
        for cache in (self.track_to_visitor, self._visitor_last_seen, self._face_attempt_count):
            for key in [k for k in list(cache) if k[0] == camera_id]:
                cache.pop(key, None)

    def visitors_for_camera(self, camera_id):
        """track_id -> visitor_id for one camera only."""
        with self.lock:
            return {tid: vid for (cam, tid), vid in self.track_to_visitor.items() if cam == camera_id}
                
    def loop(self):
        # AI Processing thread - iterates over pipelines continuously
        print("AI Worker Started with Pose Model.")
        if self.face_enabled:
            print("[Re-ID] Face recognition active - will process faces from camera feeds.")
        while self.running:
            processed_any = False
            
            with self.lock:
                cams = [(p, self.trackers[p.camera_id]) for p in self.pipelines.values()]
                
            for p, tracker in cams:
                if not getattr(p, 'ai_enabled', True):
                    continue
                    
                # Fetch frame
                try:
                    ts, frame = p.frame_queue.get_nowait()
                except queue.Empty:
                    continue
                
                self.process_frame(p, tracker, ts, frame)
                processed_any = True
                
            if not processed_any:
                time.sleep(0.01) # Avoid CPU spin

    def process_frame(self, p, tracker, ts, frame):
        # Inference with this camera's own tracker
        res = tracker.track(frame)
        
        # Results parsing
        # res.boxes.data -> [x1, y1, x2, y2, (track_id,) confidence, class]
        bboxes = res.boxes.data.cpu().numpy().tolist()
        keypoints = None
        if hasattr(res, 'keypoints') and res.keypoints is not None:
            # keypoints.data -> [N, 17, 3] (x, y, conf)
            keypoints = res.keypoints.data.cpu().numpy()
        
        # Dispatch back to pipeline to trigger events
        # Pass 'res' as well if needed for plot() or other YOLO tools
        
        ids = res.boxes.id.cpu().numpy().tolist() if res.boxes.id is not None else []
        self._expire_visitor_tracks(p.camera_id, ids, time.time())
        if self.face_enabled and len(ids) > 0:
            self._process_faces(p.camera_id, frame, bboxes, ids, res)
            
        p.handle_ai_results(bboxes, keypoints, res, frame, ts, self.visitors_for_camera(p.camera_id))
    
    def stop(self):
        self.running = False

    def _expire_visitor_tracks(self, camera_id, ids, now):
        for tid in ids:
            key = (camera_id, int(tid))
            if key in self.track_to_visitor:
                self._visitor_last_seen[key] = now
        if now - self._last_visitor_prune < 30:
            return
        self._last_visitor_prune = now
        with self.lock:
            stale = [k for k, seen in list(self._visitor_last_seen.items()) if now - seen > VISITOR_CACHE_TTL_SECONDS]
            for key in stale:
                self._visitor_last_seen.pop(key, None)
                self.track_to_visitor.pop(key, None)

    def _process_faces(self, camera_id, frame, bboxes, ids, res):
        from libs.database import SessionLocal
        from libs.models import Visitor, GlobalSetting
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

        # Check if scanning is globally enabled (every 10 seconds)
        if now - self._last_scanning_enabled_check > 10:
            db_check = SessionLocal()
            try:
                setting = db_check.query(GlobalSetting).filter_by(key="visitor_scanning_enabled").first()
                self._visitor_scanning_enabled = (setting.value.lower() == 'true') if setting else True
            except Exception as e:
                print(f"[Re-ID] Warning: Could not read scanning setting from DB: {e}")
                self._visitor_scanning_enabled = True # Fail-safe default
            finally:
                db_check.close()
            self._last_scanning_enabled_check = now
        
        if not self._visitor_scanning_enabled:
            return

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
                key = (camera_id, tid)
                
                # Already identified this track
                if key in self.track_to_visitor:
                    continue
                
                # Retry cooldown: try every 15 frames, give up after 150 attempts
                attempt_num = self._face_attempt_count.get(key, 0)
                if attempt_num > 150:
                    continue  # Give up on this track
                if attempt_num > 0 and attempt_num % 15 != 0:
                    self._face_attempt_count[key] = attempt_num + 1
                    continue  # Skip this frame, retry later
                self._face_attempt_count[key] = attempt_num + 1
                
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
                
                if best_match and best_score > 0.60:
                    # Match found
                    self.track_to_visitor[key] = best_match.id
                    self._visitor_last_seen[key] = now
                    # Remove from retry tracking
                    self._face_attempt_count.pop(key, None)
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
                    self.track_to_visitor[key] = v_id
                    self._visitor_last_seen[key] = now
                    # Remove from retry tracking
                    self._face_attempt_count.pop(key, None)
                    self._face_stats["new"] += 1
                    print(f"[Re-ID] 🆕 New visitor created: {v_id[:8]}...")
        except Exception as e:
            import traceback
            print(f"[Re-ID] ❌ Face processing error: {e}")
            traceback.print_exc()
        finally:
            db.close()
        
        # Cleanup this camera's old track_ids from cache (prevent memory leak)
        active_tids = set(int(t) for t in ids)
        with self.lock:
            stale = [k for k in self._face_attempt_count if k[0] == camera_id and k[1] not in active_tids]
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
