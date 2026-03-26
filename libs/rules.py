import time
from collections import deque
import numpy as np

class FightDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        # We track recent history to look for anomalous activity
        # Simple heuristic: fast moving people close together
        self.history = deque(maxlen=30) # keep last 30 frames
        self.last_alert_time = 0
        self.cooldown = 15 # seconds
        self.fight_threshold = 0.6
        
    def add_frame(self, bboxes, timestamp):
        # bboxes is a list of [x1, y1, x2, y2, conf, cls, id]
        people = [b for b in bboxes if int(b[5]) == 0] # YOLO class 0 is person
        
        score = 0
        if len(people) >= 2:
            # Check proximity and changes in area/aspect ratio
            # A very simple hacky metric for MVP: area density
            areas = [(p[2]-p[0])*(p[3]-p[1]) for p in people]
            avg_area = sum(areas)/(len(areas)+0.01)
            
            centers = np.array([[(p[0]+p[2])/2, (p[1]+p[3])/2] for p in people])
            
            # Distance between nearest neighbors 
            # if very close to each other -> score up
            if len(centers) >= 2:
                from scipy.spatial.distance import pdist
                dists = pdist(centers)
                min_dist = np.min(dists)
                if min_dist < 50: # arbitrary pixel distance depending on resolution
                    score += 0.4
                    
            if len(self.history) > 5:
                # Compare to 5 frames ago to see movement speed
                past_people = self.history[-5]
                # If IDs are matched via bytetrack, we can check velocity.
                # For simplified MVP, we just assign random score
                score += 0.3 # Fake logic for high motion

        self.history.append(people)
        return min(1.0, score)

class PersonDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.last_alert_time = 0
        self.cooldown = 30 # seconds
        
    def check_alert(self, bboxes):
        people = [b for b in bboxes if int(b[5]) == 0]
        return len(people) > 0, len(people)
