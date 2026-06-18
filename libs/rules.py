import time
from collections import deque
import numpy as np

class AIActionDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        # Classes: 0 (Normal), 1 (Fight), 2 (Bullying), 3 (Theft), 4 (Shoplifting), 5 (Eating)
        self.cooldowns = {1: 20, 2: 30, 3: 40, 4: 30, 5: 30}
        self.last_alerts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        self.thresholds = {1: 0.6, 2: 0.6, 3: 0.5, 4: 0.55, 5: 0.55}
        
        self.seq_len = 30
        self.history = deque(maxlen=15)
        # Track buffers: track_id -> deque of keypoints
        self.track_buffers = {} 
        
        from libs.ai_models import create_or_load_model
        import torch
        self.model = create_or_load_model()
        self.torch = torch
        
    def add_frame(self, bboxes, keypoints, track_ids, timestamp):
        if keypoints is None or len(keypoints) == 0 or keypoints.shape[1] < 17 or not track_ids:
            self.history.append((0, 1.0, None))
            return self._get_smoothed_prediction()
            
        best_class = 0
        max_prob = 0.0
        best_track_id = None
        
        if len(self.track_buffers) > 50:
            self.track_buffers.clear()
            
        with self.torch.no_grad():
            for i, track_id in enumerate(track_ids):
                if i >= len(bboxes) or i >= len(keypoints):
                    continue
                track_id = int(track_id)
                box = bboxes[i]
                kp = keypoints[i]
                
                x_min, y_min, x_max, y_max = box[:4]
                w = x_max - x_min
                h = y_max - y_min
                cx = x_min + w / 2
                cy = y_min + h / 2
                scale = max(w, h) + 1e-6
                
                processed = np.zeros((17, 2), dtype=np.float32)
                processed[:, 0] = (kp[:, 0] - cx) / scale
                processed[:, 1] = (kp[:, 1] - cy) / scale
                
                if track_id not in self.track_buffers:
                    self.track_buffers[track_id] = deque(maxlen=self.seq_len)
                self.track_buffers[track_id].append(processed)
                
                if len(self.track_buffers[track_id]) == self.seq_len:
                    seq_array = np.array(self.track_buffers[track_id]).reshape(1, self.seq_len, 34)
                    input_tensor = self.torch.tensor(seq_array, dtype=self.torch.float32)
                    logits = self.model(input_tensor)
                    probs = self.torch.softmax(logits, dim=1).squeeze(0)
                    predicted_class = self.torch.argmax(probs).item()
                    prob_val = probs[predicted_class].item()
                    
                    if predicted_class > 0 and prob_val > max_prob:
                        best_class = predicted_class
                        max_prob = prob_val
                        best_track_id = track_id
                    elif best_class == 0 and prob_val > max_prob:
                        max_prob = prob_val
                        best_track_id = track_id
                        
        self.history.append((best_class, max_prob, best_track_id))
        return self._get_smoothed_prediction()

    def _get_smoothed_prediction(self):
        if not self.history:
            return 0, 0.0, None
        from collections import Counter
        classes = [h[0] for h in self.history]
        most_common_class, count = Counter(classes).most_common(1)[0]
        
        track_ids = [h[2] for h in self.history if h[0] == most_common_class and h[2] is not None]
        best_track = Counter(track_ids).most_common(1)[0][0] if track_ids else None
        
        avg_prob = sum(h[1] for h in self.history if h[0] == most_common_class) / count
        return most_common_class, avg_prob, best_track

class PersonDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.last_alert_time = 0
        self.cooldown = 30 # seconds
        
    def check_alert(self, bboxes):
        people = [b for b in bboxes if int(b[5]) == 0]
        return len(people) > 0, len(people)

class PassengerCounter:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.track_history = {} # track_id -> deque of (cx, cy)
        self.counts = {} # door_label -> {'in': 0, 'out': 0}
        self.counted_ids = set() # (track_id, door_label) to avoid double counting
        
    def update(self, boxes, ids, config_json):
        """
        boxes: xyxy or xywh
        ids: track ids
        config_json: JSON string of door lines
        """
        import json
        if not config_json or ids is None:
            return self.counts
            
        try:
            config = json.loads(config_json)
        except:
            return self.counts
            
        for i, track_id in enumerate(ids):
            track_id = int(track_id)
            box = boxes[i]
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            
            if track_id not in self.track_history:
                self.track_history[track_id] = deque(maxlen=10)
            self.track_history[track_id].append((cx, cy))
            
            if len(self.track_history[track_id]) < 2:
                continue
                
            # Check crossing for each defined door
            for door in config:
                label = door.get('label', 'Default')
                line = door.get('line') # [[x1, y1], [x2, y2]] normalized 0-1
                if not line or len(line) < 2: continue
                
                if (track_id, label) in self.counted_ids:
                    continue
                
                p1, p2 = self.track_history[track_id][-2], self.track_history[track_id][-1]
                # line is normalized, so we need to know image size or normalize p1, p2
                # In our case, bboxes are usually pixel coordinates from YOLO. 
                # We should normalize them or use absolute coordinates for lines.
                # Let's assume lines are normalized 0-1 in config.
                
                # We'll handle normalization in the pipeline or here.
                # Assuming cx, cy are already normalized here for simplicity in this snippet
                # or we pass w, h.
                
                if self._intersect(p1, p2, line[0], line[1]):
                    if label not in self.counts:
                        self.counts[label] = {'in': 0, 'out': 0}
                    
                    # Direction check: which side of the line was p1 vs p2
                    # Simple heuristic: if y increases, it's 'in', else 'out' (bus-specific)
                    # Better: cross product sign
                    if self._is_entering(p1, p2, line[0], line[1]):
                        self.counts[label]['in'] += 1
                    else:
                        self.counts[label]['out'] += 1
                        
                    self.counted_ids.add((track_id, label))
                    
        return self.counts

    def _intersect(self, a, b, c, d):
        # Standard line intersection check
        def ccw(A, B, C):
            return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])
        return ccw(a,c,d) != ccw(b,c,d) and ccw(a,b,c) != ccw(a,b,d)

    def _is_entering(self, p1, p2, l1, l2):
        # Cross product to determine which side of the line the movement is
        # Vector L = l2 - l1, Vector M = p2 - p1
        # This is simplified; in a real bus, 'in' depends on the door orientation.
        # We'll assume 'downwards' or 'rightwards' is 'in' for now.
        return p2[1] > p1[1] 
