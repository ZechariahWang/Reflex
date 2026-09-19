import cv2
import numpy as np

from app.mirror.tracker import MediaPipeTracker


def test_tracker_sees_no_hand_in_an_empty_frame_or_in_garbage():
    tracker = MediaPipeTracker()
    try:
        ok, jpeg = cv2.imencode(".jpg", np.zeros((240, 320, 3), np.uint8))
        assert ok and tracker.detect(jpeg.tobytes()) is None
        assert tracker.detect(b"not a jpeg") is None
    finally:
        tracker.close()
