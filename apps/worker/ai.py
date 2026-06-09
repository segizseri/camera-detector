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
                p.handle_ai_results(bboxes, keypoints, res, frame, ts)
                processed_any = True
                
            if not processed_any:
                time.sleep(0.01) # Avoid CPU spin
    
    def stop(self):
        self.running = False
