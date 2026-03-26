import threading
import queue
import time
from ultralytics import YOLO

class AIWorker:
    def __init__(self):
        self.model = YOLO("yolov8n.pt") # download on first run
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
        print("AI Worker Started.")
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
                
                # Inference
                results = self.model(frame, verbose=False)
                
                # Results parsing
                # results[0].boxes.data -> [x1, y1, x2, y2, confidence, class]
                bboxes = results[0].boxes.data.cpu().numpy().tolist()
                
                # Dispatch back to pipeline to trigger events
                p.handle_ai_results(bboxes, frame, ts)
                processed_any = True
                
            if not processed_any:
                time.sleep(0.01) # Avoid CPU spin
    
    def stop(self):
        self.running = False
