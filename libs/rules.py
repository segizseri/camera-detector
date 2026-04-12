import time
from collections import deque
import numpy as np

class AIActionDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        # Classes: 0 (Normal), 1 (Fight), 2 (Bullying), 3 (Theft)
        self.cooldowns = {1: 20, 2: 30, 3: 40}
        self.last_alerts = {1: 0, 2: 0, 3: 0}
        self.thresholds = {1: 0.6, 2: 0.6, 3: 0.5}
        
        self.seq_len = 30
        self.history = deque(maxlen=15)
        # Track up to 4 people independently
        self.keypoint_buffers = [deque(maxlen=self.seq_len) for _ in range(4)] 
        
        from libs.ai_models import create_or_load_model
        import torch
        self.model = create_or_load_model()
        self.torch = torch
        
    def add_frame(self, bboxes, keypoints, timestamp):
        if keypoints is None or len(keypoints) == 0 or keypoints.shape[1] < 17:
            self.history.append((0, 1.0))
            return self._get_smoothed_prediction()
            
        best_class = 0
        max_prob = 0.0
        n = min(len(bboxes), 4) # process max 4 people
        
        with self.torch.no_grad():
            for i in range(n):
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
                
                self.keypoint_buffers[i].append(processed)
                
                if len(self.keypoint_buffers[i]) == self.seq_len:
                    seq_array = np.array(self.keypoint_buffers[i]).reshape(1, self.seq_len, 34)
                    input_tensor = self.torch.tensor(seq_array, dtype=self.torch.float32)
                    logits = self.model(input_tensor)
                    probs = self.torch.softmax(logits, dim=1).squeeze(0)
                    predicted_class = self.torch.argmax(probs).item()
                    prob_val = probs[predicted_class].item()
                    
                    if predicted_class > 0 and prob_val > max_prob:
                        best_class = predicted_class
                        max_prob = prob_val
                    elif best_class == 0 and prob_val > max_prob:
                        max_prob = prob_val
                        
        self.history.append((best_class, max_prob))
        return self._get_smoothed_prediction()

    def _get_smoothed_prediction(self):
        if not self.history:
            return 0, 0.0
        from collections import Counter
        classes = [h[0] for h in self.history]
        most_common_class, count = Counter(classes).most_common(1)[0]
        avg_prob = sum(h[1] for h in self.history if h[0] == most_common_class) / count
        return most_common_class, avg_prob

class PersonDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.last_alert_time = 0
        self.cooldown = 30 # seconds
        
    def check_alert(self, bboxes):
        people = [b for b in bboxes if int(b[5]) == 0]
        return len(people) > 0, len(people)
