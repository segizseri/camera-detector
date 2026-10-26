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
from libs.camera_streams import camera_rtsp_url
from libs.config import settings
from libs.database import SessionLocal
from libs.models import Camera
from libs.retention import cleanup_retention
from apps.worker.pipeline import CameraPipeline
from apps.worker.ai import AIWorker
from apps.worker.detection_test_runner import DetectionTestRunner
import threading

def worker_main():
    print("Starting Laptop AI Box Worker...")
    ai_engine = AIWorker()
    ai_thread = threading.Thread(target=ai_engine.loop, daemon=True)
    ai_thread.start()

    detection_test_runner = DetectionTestRunner()
    detection_test_thread = threading.Thread(target=detection_test_runner.loop, daemon=True)
    detection_test_thread.start()
    
    active_pipelines = {}
    last_retention_sweep = 0
    
    try:
        while True:
            # Query db for current camera states
            db = SessionLocal()
            try:
                cameras = db.query(Camera).all()
                now = time.time()

                if now - last_retention_sweep > settings.RETENTION_SWEEP_INTERVAL_SECONDS:
                    last_retention_sweep = now
                    try:
                        result = cleanup_retention(db)
                        if any(result[key] for key in (
                            "deleted_events",
                            "deleted_snapshots",
                            "deleted_clips",
                            "deleted_hls_files",
                            "deleted_detection_jobs",
                        )):
                            print(f"Retention cleanup: {result}")
                    except Exception as e:
                        print(f"Retention cleanup failed: {e}")
            except Exception as e:
                print(f"DB Error: {e}")
                db.close()
                time.sleep(5)
                continue
            
            import os
            import subprocess
            if os.path.exists("data/.trigger_train_lstm"):
                print("Found training trigger! Starting scripts/train_lstm.py in background...")
                try:
                    os.remove("data/.trigger_train_lstm")
                    subprocess.Popen(["python", "scripts/train_lstm.py", "--extract", "--train"])
                except Exception as e:
                    print(f"Failed to start training: {e}")
            
            # Start/Stop logic
            current_cam_ids = set()
            for cam in cameras:
                if cam.enabled:
                    current_cam_ids.add(cam.id)
                    rtsp_url = camera_rtsp_url(cam)
                    if cam.id not in active_pipelines:
                        print(f"Starting pipeline for camera {cam.name}")
                        p = CameraPipeline(cam.id, rtsp_url, cam.fps_limit)
                        p.apply_camera_config(cam)
                        active_pipelines[cam.id] = p
                        ai_engine.add_pipeline(p)
                    else:
                        # Update config
                        p = active_pipelines[cam.id]
                        if p.rtsp_url != rtsp_url:
                            print(f"Restarting pipeline for camera {cam.name}: RTSP URL changed")
                            ai_engine.remove_pipeline(cam.id)
                            p.stop()
                            p = CameraPipeline(cam.id, rtsp_url, cam.fps_limit)
                            active_pipelines[cam.id] = p
                            ai_engine.add_pipeline(p)
                        p.apply_camera_config(cam)
                        
                else:
                    if cam.id in active_pipelines:
                        print(f"Stopping pipeline for disabled camera {cam.name}")
                        ai_engine.remove_pipeline(cam.id)
                        active_pipelines[cam.id].stop()
                        del active_pipelines[cam.id]

            # Cleanup deleted cameras
            to_remove = []
            for cam_id in active_pipelines:
                if cam_id not in current_cam_ids:
                    print(f"Stopping pipeline for deleted camera {cam_id}")
                    to_remove.append(cam_id)
            for c in to_remove:
                ai_engine.remove_pipeline(c)
                active_pipelines[c].stop()
                del active_pipelines[c]
                
            db.close()
            time.sleep(10)
    except KeyboardInterrupt:
        print("Worker shutting down...")
        detection_test_runner.stop()
        ai_engine.stop()
        for p in active_pipelines.values():
            p.stop()

if __name__ == "__main__":
    worker_main()
