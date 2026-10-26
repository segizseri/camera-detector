import functools
import itertools
import torch
import torch.nn as nn
import os
from libs.config import settings

class ActionLSTM(nn.Module):
    def __init__(self, num_keypoints=17, hidden_dim=64, num_layers=2, num_classes=6):
        super(ActionLSTM, self).__init__()
        # Input shape: (batch_size, seq_len, num_keypoints * 2)
        # 17 keypoints each with (x, y) coordinates
        self.input_dim = num_keypoints * 2
        
        self.lstm = nn.LSTM(
            input_size=self.input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2 if num_layers > 1 else 0
        )
        
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, num_classes)
            # PyTorch CrossEntropyLoss takes raw logits, so no Softmax here.
        )
        
    def forward(self, x):
        lstm_out, (hidden, cell) = self.lstm(x)
        last_hidden = hidden[-1]
        logits = self.fc(last_hidden)
        return logits

def create_or_load_model(weights_path=None):
    """Load trained ActionLSTM weights, or return None when the file does not exist.

    Never falls back to randomly initialised weights: their predictions are noise.
    """
    weights_path = weights_path or settings.ACTION_MODEL_PATH
    if not os.path.exists(weights_path):
        print(f"Weights {weights_path} not found, ActionLSTM is not loaded.")
        return None
    model = ActionLSTM(num_keypoints=17, hidden_dim=64, num_layers=2, num_classes=6)
    model.load_state_dict(torch.load(weights_path, map_location="cpu"))
    print(f"Loaded AI Action Detector weights from {weights_path}")
    model.eval()
    return model


POSE_MODEL_NAME = "yolov8n-pose.pt"
TRACKER_CONFIG = "bytetrack.yaml"
# model.track() lowers conf to 0.1 so ByteTrack also gets low-score boxes for its second
# association step; PersonPoseTracker keeps that behaviour.
TRACK_CONF = 0.1
# Track ids come from one process-wide counter that is never reset (see _byte_tracker_class).
_next_track_id = itertools.count(1).__next__


def load_pose_model():
    from ultralytics import YOLO
    import ultralytics.nn.tasks

    # Fix for PyTorch 2.6+ safe globals (WeightsUnpickler error)
    try:
        torch.serialization.add_safe_globals([ultralytics.nn.tasks.DetectionModel])
    except (AttributeError, NameError):
        pass
    local_path = os.path.join(settings.MODELS_DIR, POSE_MODEL_NAME)
    return YOLO(local_path if os.path.isfile(local_path) else POSE_MODEL_NAME)


@functools.lru_cache(maxsize=None)
def _byte_tracker_class():
    from ultralytics.trackers.byte_tracker import BYTETracker

    class SourceByteTracker(BYTETracker):
        """BYTETracker whose ids never collide with other trackers in the process.

        Stock ultralytics numbers tracks with a class-level counter that every new
        BYTETracker resets, so adding a camera or starting a detection-test job would make a
        running camera hand out ids it already uses.
        """

        def reset_id(self):
            pass

        def init_track(self, dets, scores, cls, img=None):
            tracks = super().init_track(dets, scores, cls, img)
            for track in tracks:
                track.next_id = _next_track_id
            return tracks

    return SourceByteTracker


class PersonPoseTracker:
    """YOLO-Pose detection plus ByteTrack state owned by one video source.

    Same results as model.track(persist=True), but one YOLO model can serve many cameras
    without their tracks (and the LSTM sequences built from them) getting mixed up.
    """

    def __init__(self, model, imgsz=None):
        from ultralytics.utils import IterableSimpleNamespace, yaml_load
        from ultralytics.utils.checks import check_yaml

        self.model = model
        self.imgsz = imgsz or settings.POSE_IMGSZ
        cfg = IterableSimpleNamespace(**yaml_load(check_yaml(TRACKER_CONFIG)))
        # frame_rate=30 is what model.track() passes as well.
        self.tracker = _byte_tracker_class()(args=cfg, frame_rate=30)

    def track(self, frame):
        res = self.model.predict(frame, imgsz=self.imgsz, conf=TRACK_CONF, verbose=False)[0]
        det = res.boxes.cpu().numpy()
        if len(det) == 0:
            return res
        tracks = self.tracker.update(det, frame)
        if len(tracks) == 0:
            return res
        # Same post-processing as ultralytics.trackers.track.on_predict_postprocess_end.
        res = res[tracks[:, -1].astype(int)]
        res.update(boxes=torch.as_tensor(tracks[:, :-1]))
        return res
