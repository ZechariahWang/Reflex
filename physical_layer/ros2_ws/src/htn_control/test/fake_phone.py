"""A fake record3d stream. Its own module: the worker's child process has to import it."""
import threading
import time
from types import SimpleNamespace

import numpy as np

ROWS, COLUMNS = 960, 720  # portrait, as the phone's sensor


def portrait_frame():
    """Black, with the top left corner red."""
    rgb = np.zeros((ROWS, COLUMNS, 3), np.uint8)
    rgb[:100, :100] = (255, 0, 0)
    return rgb


class FakeStream:
    devices = [SimpleNamespace(product_id=1, udid='fake')]
    accepts = True
    frames = 1  # how many frames connect() sends before it returns

    def get_connected_devices(self):
        return self.devices

    def connect(self, device):
        if not self.accepts:
            return False
        for _ in range(self.frames):
            self.on_new_frame()
        return True

    def get_rgb_frame(self):
        return portrait_frame()

    def get_depth_frame(self):
        """1.5 m everywhere, 0.5 m under the red corner, as the LiDAR: a quarter of the pixels."""
        depth = np.full((ROWS // 4, COLUMNS // 4), 1.5, np.float32)
        depth[:25, :25] = 0.5
        return depth

    def get_intrinsic_mat(self):
        return SimpleNamespace(fx=700.0, fy=710.0, tx=359.5, ty=479.5)


class NoPhone(FakeStream):
    devices = []


class Refuses(FakeStream):
    accepts = False


class Streams(FakeStream):
    """Keeps sending at 60 fps from its own thread, as the library does."""

    def connect(self, device):
        def send():
            while True:
                self.on_new_frame()
                time.sleep(1 / 60)
        threading.Thread(target=send, daemon=True).start()
        return True
