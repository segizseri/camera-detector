import torch
import torch.serialization
# Monkeypatch torch.load for PyTorch 2.6 compatibility with Ultralytics/YOLO
_original_load = torch.load
def _patched_load(*args, **kwargs):
    kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)
torch.load = _patched_load
torch.serialization.load = _patched_load

import time
from libs.database import SessionLocal
from libs.models import Camera
from apps.worker.pipeline import CameraPipeline
from apps.worker.ai import AIWorker
import threading

def worker_main():
    print("Starting Laptop AI Box Worker...")
    ai_engine = AIWorker()
    ai_thread = threading.Thread(target=ai_engine.loop, daemon=True)
    ai_thread.start()
    
    active_pipelines = {}
    
    try:
        while True:
            # Query db for current camera states
            db = SessionLocal()
            try:
                cameras = db.query(Camera).all()
            except Exception as e:
                print(f"DB Error: {e}")
                time.sleep(5)
                continue
            
            import os
            import subprocess
            if os.path.exists("data/.trigger_train_lstm"):
                print("Found training trigger! Starting scripts/train_lstm.py in background...")
                try:
                    os.remove("data/.trigger_train_lstm")
                    subprocess.Popen(["python", "scripts/train_lstm.py"])
                except Exception as e:
                    print(f"Failed to start training: {e}")
            
            # Start/Stop logic
            current_cam_ids = set()
            for cam in cameras:
                if cam.enabled:
                    current_cam_ids.add(cam.id)
                    if cam.id not in active_pipelines:
                        print(f"Starting pipeline for camera {cam.name}")
                        p = CameraPipeline(cam.id, cam.rtsp_url, cam.fps_limit)
                        p.ai_enabled = cam.ai_enabled
                        active_pipelines[cam.id] = p
                        ai_engine.add_pipeline(p)
                    else:
                        # Update config
                        active_pipelines[cam.id].fps_limit = cam.fps_limit
                        active_pipelines[cam.id].ai_enabled = cam.ai_enabled
                        # Note: changing RTSP url requires restart of pipeline. For MVP, we ignore.
                        
                else:
                    if cam.id in active_pipelines:
                        print(f"Stopping pipeline for disabled camera {cam.name}")
                        ai_engine.remove_pipeline(cam.id)
                        active_pipelines[cam.id].running = False
                        del active_pipelines[cam.id]

            # Cleanup deleted cameras
            to_remove = []
            for cam_id in active_pipelines:
                if cam_id not in current_cam_ids:
                    print(f"Stopping pipeline for deleted camera {cam_id}")
                    to_remove.append(cam_id)
            for c in to_remove:
                ai_engine.remove_pipeline(c)
                active_pipelines[c].running = False
                del active_pipelines[c]
                
            db.close()
            time.sleep(10)
    except KeyboardInterrupt:
        print("Worker shutting down...")
        ai_engine.stop()
        for p in active_pipelines.values():
            p.running = False

if __name__ == "__main__":
    worker_main()
