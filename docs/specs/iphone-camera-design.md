# iPhone head camera: from the backend into ROS

How the forehead iPhone becomes a ROS camera, so that the recorder and the policy
read it the same way as the RealSense. Status: built on 2026-09-19 (the node, `ExoHand`,
the backend and the frontend), tested on a fake phone and run with no phone; NOT yet run
with a real phone - the done checks of the work order are open. Date: 2026-09-19. It closes the TODO "the forehead iPhone as a ROS topic" of
`mirror-teleop-design.md`.

Scope: a ROS node that owns the phone, the contract topics, the second image key
in `ExoHand`, and the removal of the Record3D client from the web backend. Not in
scope: iPhone depth, the recording console, training.

## Decisions

- **A ROS node owns the phone**, not the web backend. The policy cameras then do
  not depend on a running web console, and the backend is again a pure consumer
  of ROS.
- **USB only.** The phone is on the wearer, and the wearable machine is too. The
  Wi-Fi / WebRTC transport of Record3D is deleted, not moved.
- **Colour only for the policy.** The policy does not use iPhone depth, and the console has no
  iPhone depth view. The depth became necessary the same day, for the console's object map on a
  bench with only the phone: the node publishes it as 16UC1 millimetres `compressedDepth` on
  `/head_camera/aligned_depth_to_color/image_raw/compressedDepth`, turned and sized as the colour
  picture (node parameter `depth`, default true). The backend's detector takes the head camera
  while the wrist camera is silent; the objects are then where the HEAD sees them, drawn around
  the hand all the same (nothing knows where the head is).
- **Only `/compressed` and `camera_info`.** All consumers are on rosbridge, where
  a raw image is base64 JSON. No `image_raw`.
- **The node fixes the rotation and the size.** They are part of the dataset: a
  change after the first recording makes the old episodes wrong. They are node
  parameters, not a console button.
- **Image key `camera1`.** `smolvla_base` has the image slots `camera1..3`, and
  async inference has no `rename_map` (`policy-link-design.md`, The camera key).
  The wrist RealSense stays `camera2`. Datasets recorded with one camera do not
  mix with datasets of two.

## Contract (add to the root `CLAUDE.md`)

The head camera is `/head_camera/color/image_raw/compressed`
(`sensor_msgs/CompressedImage`, `jpeg`, 640 x 480, landscape, max 15 fps) with
`/head_camera/color/camera_info` next to it. `header.stamp` is the ROS time at
which the frame arrived; `frame_id` is `head_camera_color_optical_frame` (no TF:
the head is not attached to the hand). Nothing outside the camera launch file
knows it is an iPhone.

## Flow

```
iPhone (Record3D app, USB Streaming mode)
   | USB, usbmuxd
wearable ROS machine
   child process: record3d library  --pipe: rgb-->  iphone_camera_node
                                                       | rotate, shrink, JPEG
                                          /head_camera/color/image_raw/compressed
                                          /head_camera/color/camera_info
                                                       |
                                                   rosbridge :9090
                                     +-----------------+------------------+
                              web backend                         ExoHand (GPU laptop)
                        WS /ws/camera/iphone/color          observation.images.camera1
```

## The node

`htn_control/iphone_camera_node.py` + `htn_control/iphone_worker.py`, entry point
`iphone_camera_node`. `camera.launch.py` starts it with
`head_camera:=iphone` (default `none`: a launch with no phone must not print
errors without end).

- **The worker** is `application/backend/app/usb_worker.py`, moved: the library
  runs in a child process, and a stop kills that process. The reason does not
  change: the library's `disconnect()` never closes its socket, and the phone then
  refuses the next client. The worker sends only `rgb` (no depth copy), drops
  frames above the rate cap before the copy, and exits when its parent dies.
- **The node** reads the pipe in a thread and, for each frame: rotates, shrinks
  to `width x height`, encodes JPEG, stamps, publishes. Latest frame only, never
  a queue.
- **Reconnect:** when the worker ends ("no phone", "not serving", stream
  stopped), the node starts a new worker after a backoff of 1 .. 8 s. It logs the
  reason once per change of reason, not once per try. The texts that say what to
  do on the phone (`NO_PHONE`, `NOT_ACCEPTING`, `USB_STUCK`) move with the worker.
- **`camera_info`:** K from the intrinsics that the library gives
  (`get_intrinsic_mat()`), transformed for the rotation and scaled for the shrink.
  No distortion (`D` = zeros). Published with each frame, same stamp.

Parameters:

| Parameter | Default | |
|---|---|---|
| `rotation` | `270` | clockwise degrees, `0 / 90 / 180 / 270`. The sensor is portrait; 270 = landscape with the phone's charge port to the left, which is how it sits on the forehead mount (90 came out upside down). |
| `width`, `height` | `640`, `480` | the output size. The phone's 4:3 picture fits with no crop. |
| `max_fps` | `15` | the phone sends 60. 15 = the RealSense colour profile and the rate of the policy link. |
| `jpeg_quality` | `80` | |

## Set-up of the wearable machine (verify FIRST)

This is the risk of the design. Do it before any other work; if it fails, stop
and go back to the fallback below.

1. In the ROS environment (container or native):
   `python3 -m pip install --user --no-deps record3d==1.4.1` (`--no-deps`: it must not
   pull numpy 2 over the numpy that ROS and `cv2` use). Confirmed on x86-64, Python 3.10
   (Humble), native: it is a wheel, nothing compiles, and it imports next to numpy 1.26.
   Not confirmed on ARM (Pi 5): there it may build native code (`cmake`, a C++ compiler).
2. The library talks to the host's `usbmuxd` through `/var/run/usbmuxd`. In a
   distrobox that socket must be visible in the container. Not confirmed.
3. Check: a 10-line script in that environment prints the shape of one frame.

Fallback if 1 .. 3 fail: the backend keeps the phone and publishes the same
topic through rosbridge (`roslibpy`), and must then run where the phone is. The
contract, `ExoHand` and the console stay as in this spec.

## `ExoHand` (`policy/`)

- Config: `head_topic: str = "/head_camera/color/image_raw/compressed"`,
  `head_width = 640`, `head_height = 480`. An empty `head_topic` = one camera,
  the behaviour of today (for the old datasets and for a bench with no phone).
- `convert.py`: `HEAD_CAMERA = "camera1"`; `to_observation` takes the head image
  as an optional argument.
- A second subscription with its own arrival stamp. `is_fresh` already takes a
  collection of stamps: the head stamp goes into it, so a dead phone stops the
  client the same way as a dead RealSense ("the hand holds").
- The two images of one observation are the latest of each, not synchronized.
  At 15 fps the skew is at most ~70 ms. Accepted.

## Web backend and frontend

Delete:

- `app/record3d.py`, `app/usb_worker.py`, `tests/test_record3d.py`,
  `tests/fake_record3d.py`; `record3d` and `aiortc` from `requirements.txt`
  (keep `av` only if something else imports it after the change).
- `GET / POST /api/iphone`, `PhoneSettings`, `RECORD3D_HOST`,
  `RECORD3D_ROTATION`, `hub.iphone_rotation`, `run_iphone_worker`,
  `on_iphone_frame`.
- Frontend: `phone-connect.tsx`, `use-phone.ts`, the rotate button, the RGB /
  DEPTH toggle of the iPhone panel, the phone types.

Change:

- `ros_client.py` subscribes `/head_camera/color/image_raw/compressed` with the
  same throttle as the RealSense colour; `hub.on_head_color` passes the JPEG
  bytes through untouched to `frames["iphone"]["color"]`.
- `WS /ws/camera/iphone/depth` is removed; `WS /ws/camera/iphone/color` stays
  (the source keeps the name `iphone` in the API: a rename gives nothing).
- The iPhone panel with no frames shows "no frames: start `head_camera:=iphone`,
  see the node log". The phone instructions are in the node log only.
- Mock mode: the mock phone publishes its colour image directly; the Record3D
  side-by-side packing in `mock.py` goes.
- `application/CONTRACT.md`: the section "iPhone side (Record3D, not ROS)" goes;
  the API list and the file list follow the changes above.

## Tests (TDD, no phone, no ROS where possible)

Pure functions in `htn_control`, tested with `pytest` as the other HAL parts:

- `prepare(rgb, rotation, width, height)`: a portrait frame with one marked
  corner comes out `480 x 640 x 3` with that corner where the rotation puts it,
  for all four rotations.
- `camera_matrix(K, shape, rotation, width, height)`: the principal point of a
  frame follows the same marked corner; `fx / fy` swap at 90 and 270.
- The rate cap: a fake clock, 60 fps in, no two accepted frames closer than
  `0.9 / max_fps`.
- The worker with a fake stream (the `make_stream` argument that `usb_worker.run`
  has today): "no device" and "connect refused" give the error messages; a frame
  gives `("frame", rgb)`.
- The node's reconnect: a worker that ends is started again after the backoff,
  and the reason is logged once.

`policy/`:

- `to_observation` with a head image has `camera1` and `camera2`; without, only
  `camera2`.
- `ExoHand` with a fresh state and a fresh wrist frame but an old head frame
  raises `ConnectionError`; with `head_topic = ""` it does not.
- `observation_features` has the two image keys with their shapes.

Backend: `test_hub` - a head JPEG goes to the `iphone / color` channel
untouched; `test_mock_api` follows the removed endpoints.

## Work order

1. The set-up check above, on the machine that will be worn.
2. The node: pure parts with tests, the worker (moved), the node, the launch
   argument, `physical_layer/CLAUDE.md`. Done check: `ros2 topic hz` shows
   ~15 Hz, Foxglove shows the image the right way up.
3. `ExoHand`: second key, with tests. Done check: the `__main__` smoke print
   shows the two shapes.
4. Backend and frontend: the subscription, then the deletions. Done check: the
   iPhone panel shows the image with no `/api/iphone` call.
5. The root `CLAUDE.md` contract, `application/CONTRACT.md`,
   `policy-link-design.md` (one camera -> two), `next-work.md`.

## Not verified

- Steps 1 .. 3 of the set-up (the `record3d` build, the usbmuxd socket in the
  container, ARM).
- rosbridge CPU load with two JPEG streams and two clients each, on a Pi
  (already open in `policy-link-design.md` for one stream).
- The rotation value for the forehead mount.
- That `get_intrinsic_mat()` is valid before the first frame: not needed any more, the
  worker reads it in each frame callback and sends it with the frame.
- The node with a real phone: the picture size it sends over USB, ~15 Hz on
  `camera_info`, the image the right way up in Foxglove.
