"""Child process that owns the USB connection to the iPhone (Record3D, usbmuxd).

Why a process and not a thread - all three bit us for real:
- record3d's disconnect() never closes its socket, so the phone keeps serving a
  ghost connection and refuses the next one (it allows a single client) until
  someone stops the stream on the phone. Only process exit closes that socket.
- disconnect() holds the library's lock while it calls back into Python; if the
  stream ends at the same moment, the two threads deadlock on that lock and the
  GIL, and the whole backend freezes for good.
- get_connected_devices() blocks forever when usbmuxd is wedged.
A process can always be killed, and the kernel then closes the socket properly.

Keep this module light: it is imported by a freshly spawned interpreter on every
connection attempt.
"""

from __future__ import annotations

import os
import threading
import time
from multiprocessing.connection import Connection
from typing import Callable

import cv2
import numpy as np

MAX_SIDE_PX = 640  # the panel is ~450 px wide; bigger frames only cost the browser decode time
MAX_FPS = 30.0  # the phone sends 60; the page cannot show more and pays for every frame

NO_PHONE = "no iPhone on USB: plug it in, unlock it and tap Trust"
# Measured on a real phone (usbmux port 1337): the port is closed while the app is idle and
# opens when the red record button is pressed; the app then streams to whoever connected last.
NOT_ACCEPTING = (
    "Record3D is not streaming yet: open the app (Settings > USB Streaming mode on) and press "
    "the red record button. This connects by itself within 2 s."
)


def record3d_stream():
    from record3d import Record3DStream

    return Record3DStream()


def shrink(image: np.ndarray, interpolation: int = cv2.INTER_AREA) -> np.ndarray:
    scale = MAX_SIDE_PX / max(image.shape[:2])
    if scale >= 1.0:
        return np.ascontiguousarray(image)
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=interpolation)


def run(conn: Connection, make_stream: Callable[[], object] = record3d_stream) -> None:
    """Messages to the parent: ("error", text) | ("connected",) | ("frame", rgb, depth_m) | ("stopped",)."""
    parent = os.getppid()

    def exit_with_parent() -> None:  # a SIGKILLed backend must not leave us holding the phone
        while os.getppid() == parent:
            time.sleep(1.0)
        os._exit(0)

    threading.Thread(target=exit_with_parent, daemon=True).start()

    stream = make_stream()
    devices = stream.get_connected_devices()
    if not devices:
        conn.send(("error", NO_PHONE))
        return

    pipe = threading.Lock()
    accepted = [0.0]

    def on_new_frame() -> None:  # the library's thread; its buffers are reused, so copy
        now = time.monotonic()
        # Over the cap, or the parent is still taking the previous frame: drop before the copy.
        if now - accepted[0] < 0.9 / MAX_FPS or not pipe.acquire(blocking=False):
            return
        try:
            accepted[0] = now
            rgb = shrink(np.asarray(stream.get_rgb_frame()))
            depth = np.array(stream.get_depth_frame(), dtype=np.float32)
            conn.send(("frame", rgb, depth))
        except OSError:
            os._exit(0)  # the parent is gone
        finally:
            pipe.release()

    def on_stream_stopped() -> None:
        with pipe:
            try:
                conn.send(("stopped",))
            except OSError:
                pass
        os._exit(0)  # never tear the library down politely: see the module docstring

    stream.on_new_frame = on_new_frame
    stream.on_stream_stopped = on_stream_stopped
    if stream.connect(devices[0]) is False:
        conn.send(("error", NOT_ACCEPTING))
        return
    with pipe:
        conn.send(("connected",))
    threading.Event().wait()  # until the stream stops or the parent kills us
