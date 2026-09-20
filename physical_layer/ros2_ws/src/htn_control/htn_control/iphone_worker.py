"""Child process that owns the USB connection to the iPhone (Record3D, usbmuxd).

Why a process and not a thread - all three bit us for real:
- record3d's disconnect() never closes its socket, so the phone keeps serving a
  ghost connection and refuses the next one (it allows a single client) until
  someone stops the stream on the phone. Only process exit closes that socket.
- disconnect() holds the library's lock while it calls back into Python; if the
  stream ends at the same moment, the two threads deadlock on that lock and the
  GIL, and the whole node freezes for good.
- get_connected_devices() blocks forever when usbmuxd is wedged.
A process can always be killed, and the kernel then closes the socket properly.

Keep this module light (no rclpy, no cv2): it is imported by a freshly spawned
interpreter on every connection attempt.
"""
import os
import threading
import time

import numpy as np

NO_PHONE = 'no iPhone on USB: plug it in, unlock it and tap Trust'
# Confirmed on a real phone: Record3D serves USB (usbmux port 1337) only while it is NOT
# recording - the red record button pauses the USB stream - and it streams to whoever
# connected last.
NOT_ACCEPTING = ('Record3D is not serving USB: open the app (Settings > USB Streaming mode on) and make sure '
                 'it is NOT recording - if the red button is active, press it to stop')
USB_STUCK = ('usbmuxd is not answering: replug the iPhone while it is unlocked; if that does not help, '
             'run: sudo systemctl restart usbmuxd')
USB_SILENT = ('connected over USB but Record3D sends no frames: it only streams while NOT recording - '
              'if the red button is active on the phone, press it to stop')
STOPPED = 'the stream stopped (stopped on the phone, or unplugged)'


def record3d_stream():
    from record3d import Record3DStream

    return Record3DStream()


class RateCap:
    """The phone sends 60 fps: accept() is True for at most ~max_fps of them."""

    def __init__(self, max_fps, clock=time.monotonic):
        self.interval = 0.9 / max_fps  # 0.9: a frame that is a little early must not halve the rate
        self.clock = clock
        self.accepted = None

    def accept(self):
        now = self.clock()
        if self.accepted is not None and now - self.accepted < self.interval:
            return False
        self.accepted = now
        return True


def run(conn, max_fps, make_stream=record3d_stream):
    """Messages to the parent: ("error", text) | ("connected",) | ("stopped",) |
    ("frame", rgb, (fx, fy, cx, cy)) - the picture as the sensor gives it, with its intrinsics."""
    parent = os.getppid()

    def exit_with_parent():  # a SIGKILLed node must not leave us holding the phone
        while os.getppid() == parent:
            time.sleep(1.0)
        os._exit(0)

    threading.Thread(target=exit_with_parent, daemon=True).start()

    stream = make_stream()
    devices = stream.get_connected_devices()
    if not devices:
        conn.send(('error', NO_PHONE))
        return

    pipe = threading.Lock()
    cap = RateCap(max_fps)

    def on_new_frame():  # the library's thread; its buffers are reused, so copy
        # The parent is still taking the previous frame, or over the cap: drop before the copy.
        if not pipe.acquire(blocking=False):
            return
        try:
            if cap.accept():
                k = stream.get_intrinsic_mat()  # here and not before connect(): valid with a frame for sure
                conn.send(('frame', np.array(stream.get_rgb_frame()), (k.fx, k.fy, k.tx, k.ty)))
        except OSError:
            os._exit(0)  # the parent is gone
        finally:
            pipe.release()

    def on_stream_stopped():
        with pipe:
            try:
                conn.send(('stopped',))
            except OSError:
                pass
        os._exit(0)  # never tear the library down politely: see the module docstring

    stream.on_new_frame = on_new_frame
    stream.on_stream_stopped = on_stream_stopped
    if stream.connect(devices[0]) is False:
        conn.send(('error', NOT_ACCEPTING))
        return
    with pipe:
        conn.send(('connected',))
    threading.Event().wait()  # until the stream stops or the parent kills us
