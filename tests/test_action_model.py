import numpy as np
import pytest


def test_action_detector_without_weights_is_disabled(tmp_path):
    pytest.importorskip("torch")
    from libs.rules import AIActionDetector

    detector = AIActionDetector("cam-1", weights_path=str(tmp_path / "missing.pt"))

    assert detector.model is None
    keypoints = np.ones((1, 17, 3), dtype=np.float32)
    for _ in range(40):
        assert detector.add_frame([[0, 0, 10, 10, 1, 0.9, 0]], keypoints, [1], 0.0) == (0, 0.0, None)


def test_split_by_video_never_splits_one_video():
    pytest.importorskip("torch")
    from scripts.train_lstm import split_by_video

    groups = np.array(["0_normal/a.mp4"] * 4 + ["0_normal/b.mp4"] * 3 + ["1_fight/c.mp4"] * 5 + ["1_fight/d.mp4"] * 2)
    y = np.array([0] * 7 + [1] * 7)

    train_mask, holdout = split_by_video(y, groups, holdout_frac=0.5, seed=1)

    assert len(holdout) == 2
    assert {video.split("/")[0] for video in holdout} == {"0_normal", "1_fight"}
    for video in set(groups):
        in_train = train_mask[groups == video]
        assert in_train.all() or not in_train.any()
        assert in_train.any() == (video not in holdout)
