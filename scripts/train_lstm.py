import torch
import torch.nn as nn
import torch.optim as opt
import numpy as np
import os
import sys
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from libs.ai_models import ActionLSTM

DATASET_DIR = "data/dataset"
CLASSES = {"0_normal": 0, "1_fight": 1, "2_bullying": 2, "3_theft": 3, "4_shoplifting": 4, "5_eating": 5}

def extract_from_videos(seq_len=30):
    import cv2
    from ultralytics import YOLO
    
    print("Initializing YOLO-pose...")
    model = YOLO("yolov8n-pose.pt")
    
    os.makedirs(DATASET_DIR, exist_ok=True)
    for c in CLASSES.keys():
        os.makedirs(os.path.join(DATASET_DIR, c), exist_ok=True)
        
    X_list = []
    y_list = []
    
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
            
            cap = cv2.VideoCapture(video_path)
            history = []
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                    
                results = model(frame, verbose=False)
                res = results[0]
                
                if hasattr(res, 'keypoints') and res.keypoints is not None and res.boxes is not None and len(res.boxes.data) > 0:
                    # Get largest box (simplification for dataset)
                    boxes = res.boxes.data.cpu().numpy()
                    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                    if len(areas) == 0:
                        continue
                    best_idx = np.argmax(areas)
                    
                    box = boxes[best_idx]
                    kp = res.keypoints.data.cpu().numpy()[best_idx]
                    
                    if kp.shape[0] >= 17:
                        # Normalize
                        x_min, y_min, x_max, y_max = box[:4]
                        w = x_max - x_min
                        h = y_max - y_min
                        cx = x_min + w / 2
                        cy = y_min + h / 2
                        scale = max(w, h) + 1e-6
                        
                        processed = np.zeros((17, 2), dtype=np.float32)
                        processed[:, 0] = (kp[:, 0] - cx) / scale
                        processed[:, 1] = (kp[:, 1] - cy) / scale
                        
                        history.append(processed.flatten())
                
                # Slice overlapping sequences
                if len(history) == seq_len:
                    X_list.append(history.copy())
                    y_list.append(class_idx)
                    history = history[15:]
            
            cap.release()
            
    if len(X_list) == 0:
        print("No video sequences found! Please put .mp4 files into the class folders.")
        return False
        
    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.int64)
    
    np.save(os.path.join(DATASET_DIR, "X.npy"), X)
    np.save(os.path.join(DATASET_DIR, "y.npy"), y)
    print(f"Saved dataset with {len(X)} sequences to {DATASET_DIR}/X.npy")
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

def train_model(epochs=15, batch_size=16, save_path="action_lstm.pt"):
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
        print("Real dataset not found. Using artificial synthetic data...")
        X, y = create_synthetic_data(num_samples=400)
        
    dataset = torch.utils.data.TensorDataset(X, y)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)
    
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
        
    torch.save(model.state_dict(), save_path)
    print(f"Done! Saved to {save_path}. Restart your `worker` container.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ActionLSTM Trainer")
    parser.add_argument("--extract", action="store_true", help="Extract skeletons from mp4 videos in data/dataset/")
    parser.add_argument("--train", action="store_true", help="Train the model using the extracted data")
    args = parser.parse_args()
    
    if args.extract:
        extract_from_videos()
    if args.train:
        train_model()
    if not args.extract and not args.train:
        print("Please provide --extract and/or --train")
