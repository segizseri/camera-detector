import json

from libs.rules import PassengerCounter, PersonDetector


def test_person_detector_reads_class_from_last_column():
    detector = PersonDetector("test-cam-01")
    # With tracking a row is [x1, y1, x2, y2, id, conf, cls]: conf must not be read as the class.
    tracked = [[0, 0, 10, 10, 7, 1.0, 0], [0, 0, 10, 10, 8, 1.0, 0], [0, 0, 10, 10, 9, 0.4, 2]]
    untracked = [[0, 0, 10, 10, 0.9, 0], [0, 0, 10, 10, 0.9, 2]]

    assert detector.check_alert(tracked) == (True, 2)
    assert detector.check_alert(untracked) == (True, 1)
    assert detector.check_alert([]) == (False, 0)


def test_passenger_counter_counts_single_line_crossing():
    counter = PassengerCounter("test-cam-01")
    config = json.dumps([
        {"label": "Front Door", "line": [[0.5, 0.0], [0.5, 1.0]]}
    ])

    counter.update([[0.10, 0.40, 0.20, 0.60]], [1], config)
    counts = counter.update([[0.70, 0.40, 0.80, 0.60]], [1], config)

    assert counts["Front Door"]["out"] == 1
    assert counts["Front Door"]["in"] == 0


def test_passenger_counter_does_not_double_count_same_track():
    counter = PassengerCounter("test-cam-01")
    config = json.dumps([
        {"label": "Front Door", "line": [[0.5, 0.0], [0.5, 1.0]]}
    ])

    counter.update([[0.10, 0.40, 0.20, 0.60]], [1], config)
    counter.update([[0.70, 0.40, 0.80, 0.60]], [1], config)
    counts = counter.update([[0.10, 0.40, 0.20, 0.60]], [1], config)

    assert counts["Front Door"]["out"] == 1
