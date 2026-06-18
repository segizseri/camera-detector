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
            self.mtcnn = MTCNN(keep_all=False, device='cpu')
            self.resnet = InceptionResnetV1(pretrained='vggface2').eval().to('cpu')
            self.face_enabled = True
        except ImportError:
            print("facenet-pytorch not installed. Face recognition disabled.")
            self.face_enabled = False
            
        # track_id -> visitor_id mapping (cache)
        self.track_to_visitor = {}

        
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
                    self._process_faces(frame, bboxes, ids)
                    
                p.handle_ai_results(bboxes, keypoints, res, frame, ts, self.track_to_visitor)
                processed_any = True
                
            if not processed_any:
                time.sleep(0.01) # Avoid CPU spin
    
    def stop(self):
        self.running = False

    def _process_faces(self, frame, bboxes, ids):
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

        db = SessionLocal()
        try:
            for i, track_id in enumerate(ids):
                tid = int(track_id)
                if tid in self.track_to_visitor:
                    continue
                
                # Try to crop and detect face
                box = bboxes[i]
                x1, y1, x2, y2 = map(int, box[:4])
                # Expand box slightly for face crop (top portion)
                h = y2 - y1
                # YOLO box is whole body. Face is usually top 20-30%
                y2_face = min(y2, y1 + int(h * 0.3))
                
                crop = frame[max(0, y1):y2_face, max(0, x1):x2]
                if crop.size == 0: continue
                
                # Convert BGR to RGB for MTCNN
                crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(crop_rgb)
                
                # Detect face
                face = self.mtcnn(img)
                if face is not None:
                    # Get embedding
                    emb = self.resnet(face.unsqueeze(0)).detach().numpy()[0]
                    
                    # Compare with DB
                    visitors = db.query(Visitor).all()
                    best_match = None
                    best_score = -1
                    
                    for v in visitors:
                        if v.face_embedding:
                            v_emb = np.array(json.loads(v.face_embedding))
                            # Cosine similarity
                            score = np.dot(emb, v_emb) / (np.linalg.norm(emb) * np.linalg.norm(v_emb))
                            if score > best_score:
                                best_score = score
                                best_match = v
                    
                    if best_match and best_score > 0.75:
                        # Match found
                        self.track_to_visitor[tid] = best_match.id
                        # Update last seen
                        if (datetime.utcnow() - best_match.last_seen).total_seconds() > 3600:
                            best_match.visit_count += 1
                        best_match.last_seen = datetime.utcnow()
                        db.commit()
                        print(f"Recognized visitor {best_match.id} (Score {best_score:.2f})")
                    else:
                        # New visitor
                        v_id = str(uuid.uuid4())
                        
                        # Save face snapshot
                        snap_name = f"visitor_{v_id}.jpg"
                        snap_path = os.path.join(settings.SNAPSHOTS_DIR, snap_name)
                        cv2.imwrite(snap_path, crop)
                        
                        new_v = Visitor(
                            id=v_id,
                            face_embedding=json.dumps(emb.tolist()),
                            face_snapshot=snap_name
                        )
                        db.add(new_v)
                        db.commit()
                        self.track_to_visitor[tid] = v_id
                        print(f"New visitor created: {v_id}")
        except Exception as e:
            print(f"Face processing error: {e}")
        finally:
            db.close()
