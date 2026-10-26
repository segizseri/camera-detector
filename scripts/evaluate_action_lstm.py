import argparse
import json
import os
import sys

import numpy as np
import torch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from libs.ai_models import ActionLSTM
from libs.config import settings
from train_lstm import DATASET_DIR, holdout_split_path  # same directory as this script


CLASSES = {
    0: "normal",
    1: "fight",
    2: "bullying",
    3: "theft",
    4: "shoplifting",
    5: "eating",
}


def predict(model, X):
    with torch.no_grad():
        probs = torch.softmax(model(X), dim=1)
    return probs, torch.argmax(probs, dim=1)


def print_report(title, y, probs, pred):
    accuracy = (pred == y).float().mean().item() if len(y) else 0.0
    print(f"\n{title}")
    print(f"Samples: {len(y)}")
    print(f"Accuracy: {accuracy:.4f}")
    print("Confusion matrix rows=true cols=pred")
    matrix = torch.zeros((6, 6), dtype=torch.int64)
    for true, guessed in zip(y, pred):
        matrix[int(true), int(guessed)] += 1

    header = "          " + " ".join(f"{CLASSES[i][:6]:>7}" for i in range(6))
    print(header)
    for idx in range(6):
        row = " ".join(f"{int(v):7d}" for v in matrix[idx])
        print(f"{CLASSES[idx][:8]:>8} {row}")

    print(f"{'class':>12} {'precision':>9} {'recall':>7} {'f1':>7} {'avg_conf':>8} {'support':>7}")
    for cls_id in range(6):
        tp = int(matrix[cls_id, cls_id])
        predicted = int(matrix[:, cls_id].sum())
        support = int(matrix[cls_id, :].sum())
        if support == 0 and predicted == 0:
            continue
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        mask = y == cls_id
        avg_conf = probs[mask, cls_id].mean().item() if support else 0.0
        print(f"{CLASSES[cls_id]:>12} {precision:9.4f} {recall:7.4f} {f1:7.4f} {avg_conf:8.4f} {support:7d}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate ActionLSTM on videos held out from its training")
    parser.add_argument("--weights", default=settings.ACTION_MODEL_PATH, help="Model to evaluate (default: ACTION_MODEL_PATH)")
    args = parser.parse_args()

    x_path = os.path.join(DATASET_DIR, "X.npy")
    y_path = os.path.join(DATASET_DIR, "y.npy")
    groups_path = os.path.join(DATASET_DIR, "groups.npy")
    if not all(os.path.exists(p) for p in (x_path, y_path, groups_path)):
        raise SystemExit(f"Missing {DATASET_DIR}/X.npy, y.npy or groups.npy. Run train_lstm.py --extract first.")
    if not os.path.exists(args.weights):
        raise SystemExit(f"Missing model weights: {args.weights}")

    # Windows of one video overlap by 50%, so only videos the model never saw give honest numbers.
    split_path = holdout_split_path(args.weights)
    if not os.path.exists(split_path):
        raise SystemExit(
            f"{args.weights} was trained on every video (no {split_path}), so metrics on {DATASET_DIR} "
            "would be measured on training data. Train an evaluation model with held-out videos:\n"
            "  python scripts/train_lstm.py --train --holdout-frac 0.2 --save-path data/models/action_lstm_eval.pt\n"
            "  python scripts/evaluate_action_lstm.py --weights data/models/action_lstm_eval.pt"
        )
    with open(split_path, encoding="utf-8") as fh:
        holdout_videos = json.load(fh)["holdout_videos"]

    X = torch.tensor(np.load(x_path), dtype=torch.float32)
    y = torch.tensor(np.load(y_path), dtype=torch.long)
    groups = np.load(groups_path)
    if len(groups) != len(y):
        raise SystemExit("groups.npy does not match X.npy/y.npy. Re-run train_lstm.py --extract.")
    test_mask = torch.from_numpy(np.isin(groups, holdout_videos))
    if not test_mask.any():
        raise SystemExit(f"None of the held-out videos from {split_path} are in {DATASET_DIR}. Re-train with --holdout-frac.")

    model = ActionLSTM(num_keypoints=17, hidden_dim=64, num_layers=2, num_classes=6)
    model.load_state_dict(torch.load(args.weights, map_location="cpu"))
    model.eval()

    print(f"Held-out videos: {len(holdout_videos)}")
    for video in holdout_videos:
        print(f"  {video}")

    probs, pred = predict(model, X[test_mask])
    print_report("Held-out videos (not used for training)", y[test_mask], probs, pred)

    train_mask = ~test_mask
    if train_mask.any():
        probs, pred = predict(model, X[train_mask])
        accuracy = (pred == y[train_mask]).float().mean().item()
        print(f"\nFor comparison, accuracy on training videos: {accuracy:.4f} ({int(train_mask.sum())} windows)")


if __name__ == "__main__":
    main()
