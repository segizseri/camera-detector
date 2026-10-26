import torch
import torch.nn as nn
import torch.optim as opt
import numpy as np
import os
import sys
import json
import argparse

# PyTorch 2.6+ defaults torch.load(weights_only=True), while Ultralytics
# YOLO checkpoints need the older behavior.
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from libs.ai_models import ActionLSTM, PersonPoseTracker, load_pose_model
from libs.config import settings
from libs.rules import normalize_keypoints

DATASET_DIR = "data/dataset"
CLASSES = {"0_normal": 0, "1_fight": 1, "2_bullying": 2, "3_theft": 3, "4_shoplifting": 4, "5_eating": 5}


def holdout_split_path(weights_path):
    """Sidecar listing the videos a model was NOT trained on (read by evaluate_action_lstm.py)."""
    return f"{weights_path}.holdout.json"


def split_by_video(y, groups, holdout_frac=0.2, seed=42):
    """Hold out whole videos, per class, so no window of a held-out video is trained on.

    Windows of one video overlap by 50%, so splitting by window would leak.
    Returns (train_mask, holdout_videos).
    """
    y = np.asarray(y)
    groups = np.asarray(groups)
    rng = np.random.default_rng(seed)
    holdout = []
    for cls in np.unique(y):
        videos = np.unique(groups[y == cls])
        if len(videos) < 2:
            print(f"Class {int(cls)} has {len(videos)} video(s); keeping it in training only.")
            continue
        count = min(len(videos) - 1, max(1, round(len(videos) * holdout_frac)))
        holdout.extend(str(v) for v in rng.choice(videos, size=count, replace=False))
    return ~np.isin(groups, holdout), sorted(holdout)


def extract_from_videos(seq_len=30, sample_fps=None, pose_imgsz=None):
    import cv2

    sample_fps = sample_fps or settings.ACTION_SAMPLE_FPS
    pose_imgsz = pose_imgsz or settings.POSE_IMGSZ
    if sample_fps <= 0:
        raise ValueError("sample_fps must be greater than zero")
    if pose_imgsz <= 0:
        raise ValueError("pose_imgsz must be greater than zero")
    if sample_fps != settings.ACTION_SAMPLE_FPS or pose_imgsz != settings.POSE_IMGSZ:
        print(f"WARNING: extracting at {sample_fps:g} FPS / imgsz {pose_imgsz}, but live cameras run "
              f"ACTION_SAMPLE_FPS={settings.ACTION_SAMPLE_FPS:g} / POSE_IMGSZ={settings.POSE_IMGSZ}. "
              f"Set the same values in the worker environment.")
    
    print("Initializing YOLO-pose...")
    model = load_pose_model()
    
    os.makedirs(DATASET_DIR, exist_ok=True)
    for c in CLASSES.keys():
        os.makedirs(os.path.join(DATASET_DIR, c), exist_ok=True)
        
    X_list = []
    y_list = []
    # Source video of every window, so evaluation can hold out whole videos.
    groups_list = []
    
    print(f"Reading videos from {DATASET_DIR}...")
    for class_folder, class_idx in CLASSES.items():
        folder_path = os.path.join(DATASET_DIR, class_folder)
        if not os.path.exists(folder_path):
            continue
            
        for file in os.listdir(folder_path):
            if not file.endswith(".mp4"):
                continue
                
            video_path = os.path.join(folder_path, file)
            print(f"Processing {video_path}...")
            
            video_id = f"{class_folder}/{file}"
            cap = cv2.VideoCapture(video_path)
            source_fps = cap.get(cv2.CAP_PROP_FPS)
            sample_stride = max(1, round(source_fps / sample_fps)) if source_fps > 0 else 1
            frame_index = 0
            track_histories = {}
            # Fresh tracker per video so ids do not leak across clips (same tracker as live).
            pose_tracker = PersonPoseTracker(model, imgsz=pose_imgsz)
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                should_process = frame_index % sample_stride == 0
                frame_index += 1
                if not should_process:
                    continue
                    
                res = pose_tracker.track(frame)
                
                # Like live inference, only tracked people feed the LSTM; detection indices
                # used as fake ids would merge different people into one sequence.
                if hasattr(res, 'keypoints') and res.keypoints is not None and res.boxes is not None and res.boxes.id is not None:
                    boxes = res.boxes.data.cpu().numpy()
                    keypoints = res.keypoints.data.cpu().numpy()
                    ids = res.boxes.id.cpu().numpy().tolist()

                    for det_idx, track_id in enumerate(ids):
                        if det_idx >= len(boxes) or det_idx >= len(keypoints):
                            continue
                        box = boxes[det_idx]
                        kp = keypoints[det_idx]
                        if kp.shape[0] < 17:
                            continue

                        processed = normalize_keypoints(box, kp)
                        
                        track_id = int(track_id)
                        history = track_histories.setdefault(track_id, [])
                        history.append(processed.flatten())

                        # Slice overlapping sequences per tracked person.
                        if len(history) == seq_len:
                            X_list.append(history.copy())
                            y_list.append(class_idx)
                            groups_list.append(video_id)
                            track_histories[track_id] = history[seq_len // 2:]
            
            cap.release()
            
    if len(X_list) == 0:
        print("No video sequences found! Please put .mp4 files into the class folders.")
        return False
        
    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.int64)
    
    np.save(os.path.join(DATASET_DIR, "X.npy"), X)
    np.save(os.path.join(DATASET_DIR, "y.npy"), y)
    np.save(os.path.join(DATASET_DIR, "groups.npy"), np.array(groups_list))
    print(f"Saved dataset with {len(X)} sequences from {len(set(groups_list))} videos to {DATASET_DIR}/X.npy")
    return True

def create_synthetic_data(num_samples=1000, seq_len=30):
    print("Generating fallback synthetic data...")
    X = np.zeros((num_samples, seq_len, 34), dtype=np.float32)
    y = np.zeros((num_samples,), dtype=np.int64)
    for i in range(num_samples):
        cls = np.random.randint(0, 6)
        y[i] = cls
        for t in range(seq_len):
            kps = np.random.randn(17, 2) * 0.05
            kps[5, 1] -= 0.2; kps[6, 1] -= 0.2
            kps[9, 1] += 0.3; kps[10, 1] += 0.3
            if cls == 1:
                kps[9] = np.random.randn(2) * 0.5
                kps[10] = np.random.randn(2) * 0.5
            elif cls == 2:
                kps[:, 0] += 0.1
                kps[5, 1] -= 0.1
            elif cls == 3:
                kps[9, 0] += 0.4
                kps[9, 1] -= 0.2
            elif cls == 4:
                # Shoplifting: arm extends out then retracts to hip
                phase = t / seq_len
                if phase < 0.4:
                    # Reach out to display
                    kps[9, 0] += 0.4 * (phase / 0.4)
                    kps[10, 0] += 0.3 * (phase / 0.4)
                else:
                    # Conceal: hand returns to hip area quickly
                    retract = (phase - 0.4) / 0.6
                    kps[9, 0] += 0.4 * (1 - retract)
                    kps[9, 1] += 0.25 * retract  # move toward hip
                    kps[10, 0] += 0.3 * (1 - retract)
                    kps[10, 1] += 0.25 * retract
            elif cls == 5:
                # Eating/Drinking: Hand moves from lower position to face (nose)
                phase = t / seq_len
                # Hand 9 moves to nose 0
                kps[9, 1] -= 0.5 * phase  # Move up towards face
                kps[9, 0] += 0.1 * phase  # Slight horizontal adjustment
            X[i, t, :] = kps.flatten()
    return torch.tensor(X), torch.tensor(y)

def train_model(
    epochs=15,
    batch_size=16,
    save_path=None,
    allow_synthetic=False,
    focus_class=None,
    min_near_face_frac=None,
    extra_dataset_dirs=None,
    seed=42,
    holdout_frac=0.0,
):
    save_path = save_path or settings.ACTION_MODEL_PATH
    torch.manual_seed(seed)
    np.random.seed(seed)
    print("Initializing ActionLSTM Model (6 Classes)...")
    model = ActionLSTM(num_keypoints=17, hidden_dim=64, num_layers=2, num_classes=6)
    criterion = nn.CrossEntropyLoss()
    optimizer = opt.Adam(model.parameters(), lr=0.001)
    
    x_path = os.path.join(DATASET_DIR, "X.npy")
    y_path = os.path.join(DATASET_DIR, "y.npy")
    
    if os.path.exists(x_path) and os.path.exists(y_path):
        print("Loading real dataset from .npy files...")
        X = torch.tensor(np.load(x_path))
        y = torch.tensor(np.load(y_path))
    else:
        if not allow_synthetic:
            print("Real dataset not found. Run with --extract after adding .mp4 files to data/dataset/<class>/")
            print("Refusing to train on synthetic fallback data. Use --synthetic only for developer smoke tests.")
            return False
        print("Real dataset not found. Using artificial synthetic data...")
        X, y = create_synthetic_data(num_samples=400)

    holdout_videos = []
    if holdout_frac > 0:
        groups_path = os.path.join(DATASET_DIR, "groups.npy")
        groups = np.load(groups_path) if os.path.exists(groups_path) and os.path.exists(x_path) else None
        if groups is None or len(groups) != len(y):
            raise ValueError("--holdout-frac needs data/dataset/groups.npy matching X.npy; re-run with --extract")
        train_mask, holdout_videos = split_by_video(y.numpy(), groups, holdout_frac, seed)
        X = X[torch.from_numpy(train_mask)]
        y = y[torch.from_numpy(train_mask)]
        print(f"Held out {len(holdout_videos)} videos ({int((~train_mask).sum())} windows) "
              f"for scripts/evaluate_action_lstm.py")

    for extra_dir in extra_dataset_dirs or []:
        extra_x_path = os.path.join(extra_dir, "X.npy")
        extra_y_path = os.path.join(extra_dir, "y.npy")
        if not os.path.exists(extra_x_path) or not os.path.exists(extra_y_path):
            raise ValueError(f"Missing X.npy or y.npy in extra dataset: {extra_dir}")
        extra_X = torch.tensor(np.load(extra_x_path))
        extra_y = torch.tensor(np.load(extra_y_path))
        if extra_X.shape[1:] != X.shape[1:]:
            raise ValueError(
                f"Incompatible sequence shape in {extra_dir}: "
                f"expected {tuple(X.shape[1:])}, got {tuple(extra_X.shape[1:])}"
            )
        X = torch.cat((X, extra_X), dim=0)
        y = torch.cat((y, extra_y), dim=0)
        print(f"Added {len(extra_y)} samples from {extra_dir}")

    sampler = None
    if focus_class is not None:
        if focus_class <= 0 or focus_class >= 6:
            raise ValueError("focus_class must be one of the action classes 1..5")

        normal_indices = torch.where(y == 0)[0]
        action_indices = torch.where(y == focus_class)[0]
        if min_near_face_frac is not None:
            if focus_class != 5:
                raise ValueError("min_near_face_frac is only supported for eating class 5")
            if not 0.0 <= min_near_face_frac <= 1.0:
                raise ValueError("min_near_face_frac must be between 0 and 1")

            poses = X[action_indices].reshape(-1, X.shape[1], 17, 2)
            nose = poses[:, :, 0, :]
            wrists = poses[:, :, [9, 10], :]
            wrist_to_face = torch.linalg.vector_norm(
                wrists - nose.unsqueeze(2), dim=-1
            ).min(dim=2).values
            near_face_fraction = (wrist_to_face < 0.25).float().mean(dim=1)
            action_indices = action_indices[near_face_fraction >= min_near_face_frac]
            print(
                f"Eating pose filter min_near_face_frac={min_near_face_frac}: "
                f"kept {len(action_indices)} target samples"
            )
        if len(normal_indices) == 0 or len(action_indices) == 0:
            raise ValueError(
                f"focus_class={focus_class} requires both normal and target samples; "
                f"found normal={len(normal_indices)}, target={len(action_indices)}"
            )

        normal_count = len(normal_indices)
        action_count = len(action_indices)
        generator = torch.Generator().manual_seed(seed)
        selected = torch.cat((normal_indices, action_indices))
        X = X[selected]
        y = y[selected]
        sample_weights = torch.where(
            y == 0,
            torch.tensor(1.0 / normal_count, dtype=torch.double),
            torch.tensor(1.0 / action_count, dtype=torch.double),
        )
        sampler = torch.utils.data.WeightedRandomSampler(
            sample_weights,
            num_samples=2 * max(normal_count, action_count),
            replacement=True,
            generator=generator,
        )
        print(
            f"Focused training for classes 0 and {focus_class}: "
            f"normal={normal_count}, target={action_count}; balanced sampling enabled"
        )
        
    dataset = torch.utils.data.TensorDataset(X, y)
    dataloader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        sampler=sampler,
        shuffle=sampler is None,
    )
    
    model.train()
    for epoch in range(epochs):
        epoch_loss = 0
        correct = 0
        total = 0
        for batch_x, batch_y in dataloader:
            optimizer.zero_grad()
            logits = model(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            predicted = torch.argmax(logits, dim=1)
            correct += (predicted == batch_y).sum().item()
            total += batch_y.size(0)
            
        print(f"Epoch {epoch+1}/{epochs} | Loss: {epoch_loss/len(dataloader):.4f} | Accuracy: {correct/total:.4f}")
        
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    torch.save(model.state_dict(), save_path)
    split_path = holdout_split_path(save_path)
    if holdout_videos:
        with open(split_path, "w", encoding="utf-8") as fh:
            json.dump({"holdout_videos": holdout_videos, "holdout_frac": holdout_frac, "seed": seed}, fh, ensure_ascii=False, indent=2)
    elif os.path.exists(split_path):
        os.remove(split_path)  # These weights saw every video
    print(f"Done! Saved to {save_path}. Restart your `worker` container.")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ActionLSTM Trainer")
    parser.add_argument("--extract", action="store_true", help="Extract skeletons from mp4 videos in data/dataset/")
    parser.add_argument("--train", action="store_true", help="Train the model using the extracted data")
    parser.add_argument("--synthetic", action="store_true", help="Allow synthetic fallback data if X.npy/y.npy do not exist")
    parser.add_argument("--sample-fps", type=float, default=settings.ACTION_SAMPLE_FPS, help="Video sampling rate used during pose extraction (default: ACTION_SAMPLE_FPS from libs/config.py)")
    parser.add_argument("--pose-imgsz", type=int, default=settings.POSE_IMGSZ, help="YOLO-Pose inference size used during extraction (default: POSE_IMGSZ from libs/config.py)")
    parser.add_argument("--focus-class", type=int, help="Train a balanced normal-vs-action candidate for class 1..5")
    parser.add_argument("--min-near-face-frac", type=float, help="For eating class 5, retain windows with this minimum hand-near-face fraction")
    parser.add_argument("--extra-dataset-dir", action="append", default=[], help="Append extracted X.npy/y.npy from another directory")
    parser.add_argument("--save-path", help="Override the output model path")
    parser.add_argument("--epochs", type=int, default=15, help="Training epochs (default: 15)")
    parser.add_argument("--batch-size", type=int, default=16, help="Training batch size (default: 16)")
    parser.add_argument("--holdout-frac", type=float, default=0.0, help="Share of videos per class to keep out of training for evaluate_action_lstm.py (e.g. 0.2)")
    args = parser.parse_args()
    
    if args.extract:
        extract_from_videos(sample_fps=args.sample_fps, pose_imgsz=args.pose_imgsz)
    if args.train:
        train_model(
            epochs=args.epochs,
            batch_size=args.batch_size,
            save_path=args.save_path,
            allow_synthetic=args.synthetic,
            focus_class=args.focus_class,
            min_near_face_frac=args.min_near_face_frac,
            extra_dataset_dirs=args.extra_dataset_dir,
            holdout_frac=args.holdout_frac,
        )
    if not args.extract and not args.train:
        print("Please provide --extract and/or --train")
