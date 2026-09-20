# QNX track: a learned contact detector on a Raspberry Pi

Status: proposal from the discussion of 2026-09-20. Nothing is built and nothing here is tested
on QNX. The open questions at the end are not decided.

## The track

Hard requirements: the project uses QNX OS, and it includes one of the open-source AI modules
of https://oss.qnx.com. Judging: is it a "cannot-fail" embedded application, does it need
real time or reliability, is the AI use interesting, and does it run on the embedded hardware
or a QNX VM (not in the cloud).

The SmolVLA policy runs on the GPU laptop, so it does not count. Something with AI has to run
on the QNX machine itself.

## The idea

A Raspberry Pi 4 with QNX 8.0 runs a small model that says, per finger, "this finger meets
resistance". It is a learned version of the contact stop in `hal/contact.py`.

Why this and not a vision model: the contact stop IS the safety decision of the hand (it
protects the linkage and the wearer's fingers, and it sets the grip force), it needs the 50 Hz
loop, and it must keep working when the laptop or the policy dies. That is the story the judges
ask for.

### What the model can do better than the threshold

The detector of today sums the motor current above `blocked_current` (100 mA) and blocks at
`blocked_excess` (100). One threshold for every position and speed:

- a free start of the middle finger already summed to 34;
- near a linkage bind the leverage changes, so the current for the same force depends on where
  the finger is (ring and pinky are within a few degrees of a bind, `next-work.md`);
- it cannot be early: it waits for the sum.

A model that sees position and velocity next to the current can learn both.

### Model

- Input: the last ~10 HAL cycles (0.2 s) of one finger: current (mA), position, velocity, push
  direction. One model for all five fingers, run once per finger.
- Output: probability of contact.
- A small 1D-CNN or MLP: far below 1 ms on a Pi 4.
- Trained on the laptop (Keras), converted to `.tflite`, run on QNX with
  `python3-tflite-runtime`.

### Safety rule

`blocked = threshold detector OR model`. The model can only stop a finger earlier; it can never
cancel a stop of the threshold. Torque limits, clamps and the threshold stay hard-coded below
it ("Safety limits ... belong in the HAL and the servo registers, below any learned policy").

## Two ways to build it

1. **Advisory (no hardware risk).** The HAL stays on the laptop. A relay node (~30 lines) sends
   `/hand/current`, `/hand/state` and `/hand/command` to the Pi on UDP, the Pi sends the model's
   verdict back, the console shows it next to `/hand/blocked`. The verdict does NOT stop the
   hand: a network link in the safety path is worse than what there is now. Qualifies, but the
   Pi is a side process and a judge can see that.
2. **The HAL on the Pi (the full story).** The Pi owns the servo bus and runs the 50 Hz loop,
   the threshold, the model and a watchdog that holds the pose when the laptop goes silent. The
   laptop only sends `/hand/command`. `hal/` is ~430 lines and needs only `rclpy`, `std_msgs`,
   `std_srvs`, `sensor_msgs` and `pyserial`.

Recommended order: 1 first, then 2 if the USB adapter test below passes.

## What is on oss.qnx.com

From the dashboard's API (`/packages?package_name=...&arch_id=aarch64&latest_only=1` on the
`API_URL` in the page source), 2026-09-20. Prebuilt `apk` packages unless noted; targets are
Raspberry Pi 4 and 5.

| Module | Packages | QNX | Python |
|---|---|---|---|
| TensorFlow Lite | `tflite-runtime`, `python3-tflite-runtime` 2.21.0 | 8.0.3 | yes |
| MediaPipe | `mediapipe`, `python3-mediapipe-cpu` 0.10.26 | 8.0.3 | yes |
| OpenCV (with `dnn`) | `opencv`, `python3-opencv` 4.12.0 | 8.0.3 | yes |
| ncnn | `ncnn`, `python3-ncnn` | 8.0.5 | yes |
| ONNX (format only, no `onnxruntime` found) | `onnx`, `python3-onnx` 1.20.1 | 8.0.5 | yes |
| llama.cpp | `llama.cpp`, `llama-server` | 8.0.3 | no (HTTP server) |
| whisper.cpp | `whisper.cpp` | 8.0.5 | no |
| mlpack, XNNPACK | | 8.0.3 | no |
| PyTorch 2.3.1, TensorFlow 2.16.1 | cross-build only | 8.0.0 / 7.1 | - |

Also there: `python3-numpy`, `python3-scipy`, and `ros2-jazzy` (+ `-control`, `-nav2`,
`-moveit2`) as `apk`. The source port of ROS 2 (`qnx-ports/build-files`, `ports/ros2`) is
Humble, needs a Linux host with Docker and recommends 32 GB of RAM.

Fallback AI module if the contact model has no data in time: MediaPipe. The mirror teleop
already uses it (`application/backend/app/mirror/tracker.py`), so the hand tracker could move
to the Pi with no new model.

## Risks, highest first

1. **The USB servo adapter on QNX** (way 2 only). QNX uses `devc-serusb`, the port is
   `/dev/serusb1`, and the docs list no chips. First thing on a booted Pi:
   `devc-serusb -d query_modules`. If the adapter's chip is not there, way 2 is dead.
2. **Data.** Free sweeps and blocked sweeps on the real hand. Only the thumb is calibrated, so
   a thumb-only model is the realistic first result.
3. **Labels.** Simplest: an object at a known position, label = contact once the finger is at
   it. Bad labels give a model worse than the threshold.
4. **ROS 2 on the Pi** (way 2 only). The prebuilt one is Jazzy, the workspace is Humble: DDS
   across distros is not supported, often works for `std_msgs`, not tested. The Humble source
   build takes hours. A way around both: no ROS on the Pi, the HAL as plain Python behind a
   small UDP bridge, the ROS node on the laptop as the relay.
5. **Honest value.** The threshold already works. Show a plot of both detectors on the same
   recording (the model earlier, and quiet on a free start), or it reads as a threshold with
   extra steps.
6. `pyserial` on QNX: pure Python on termios, should work, not tested.

## Not verified

- The `apk` repository URL for the Pi image (the QNX Quick Start docs should say).
- What `hosted` in the dashboard API means (false for `python3-tflite-runtime`).
- That the `apk` packages of 8.0.3 install on the Quick Start image's QNX version.

## Open questions

- Way 1 only, or way 2 as well? (Depends on the `devc-serusb` test.)
- Contact / no contact, or also the kind of contact (soft object, hard stop, jam)? Proposal:
  contact only; the kinds need about three times the data.
- Which Pi is there? Pi 4 is the tested target of the ROS 2 port; the dashboard has Pi 5 too.
