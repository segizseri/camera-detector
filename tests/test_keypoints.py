import numpy as np
import pytest

from libs.rules import KEYPOINT_CONF_THRESHOLD, normalize_keypoints


def _keypoints(conf):
    # 17 keypoints spread over the box (100..200, 50..250), all with the given confidence.
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[:, 0] = np.linspace(100, 200, 17)
    kp[:, 1] = np.linspace(50, 250, 17)
    kp[:, 2] = conf
    return kp


def test_confident_keypoints_are_centered_and_scaled_by_bbox():
    box = [100, 50, 200, 250, 0.9, 0]  # center (150, 150), longer side 200
    kp = _keypoints(0.9)

    out = normalize_keypoints(box, kp)

    assert out.shape == (17, 2)
    np.testing.assert_allclose(out[:, 0], (kp[:, 0] - 150) / 200, atol=1e-5)
    np.testing.assert_allclose(out[:, 1], (kp[:, 1] - 150) / 200, atol=1e-5)


def test_low_confidence_keypoints_are_masked_to_zero():
    box = [100, 50, 200, 250, 0.9, 0]
    kp = _keypoints(0.9)
    # YOLO reports invisible joints as (0, 0) with low confidence.
    kp[[3, 4, 15, 16]] = [0.0, 0.0, KEYPOINT_CONF_THRESHOLD - 0.01]

    out = normalize_keypoints(box, kp)

    np.testing.assert_array_equal(out[[3, 4, 15, 16]], 0.0)
    # Without the mask (0, 0) would become a large bogus offset to the frame corner.
    assert out[0, 0] == pytest.approx((100 - 150) / 200, abs=1e-5)
    assert np.all(out[[0, 1, 2, 5, 14]] != 0.0)


def test_keypoint_at_threshold_is_kept():
    box = [0, 0, 100, 100]
    kp = _keypoints(KEYPOINT_CONF_THRESHOLD)

    out = normalize_keypoints(box, kp)

    assert np.count_nonzero(out) > 0
