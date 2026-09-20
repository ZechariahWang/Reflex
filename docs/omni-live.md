# OMNI Piano: a hand that sees, hears and plays

Branch: `feat/qwen-omni-copilot`.

The demo extends the existing robotic left hand, CAD digital twin, wrist/head cameras,
motor telemetry, rehearsed piano movements and episode recorder. Qwen receives a fresh
camera image, microphone audio and measured hand context in one multimodal request.
It can interpret a spoken song request or attempt to recognize a hummed melody,
explain the scene, and propose one of the existing routines. Recognition is model
dependent: rehearse with the actual provider before presenting it to judges.

## Run with Huawei's sponsored yibuapi credits

Obtain the key through the challenge's sponsor-credit application. In the backend's
environment set the following; never put the API key in a `NEXT_PUBLIC_` variable:

```bash
export QWEN_API_KEY='<sponsored key>'
export QWEN_BASE_URL='https://yibuapi.com/v1'
export QWEN_MODEL='qwen3.5-omni-plus'
cd application
./dev.sh
```

`https://yibuapi.com/v1` is the conventional OpenAI-compatible endpoint candidate.
Confirm the endpoint and exact model ID in the sponsored account before use; the
public challenge README does not specify either. The model must accept image and
audio together via `input_audio` and `image_url`, plus streaming text output. Configure
the provider's actual ID if different. The backend appends `/chat/completions`.

PowerShell, when launching the services separately:

```powershell
$env:QWEN_API_KEY = '<sponsored key>'
$env:QWEN_BASE_URL = 'https://yibuapi.com/v1'
$env:QWEN_MODEL = 'qwen3.5-omni-plus'
# From application/backend, with requirements.txt installed:
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Separate terminal, application/frontend:
npm run dev
```

Open http://localhost:3000. Use localhost or HTTPS for microphone access. Check
`/api/omni/status`: `configured` only means environment variables are present, not
that credentials/model access have been verified. Restart the backend after changing them.

`MOCK=1` exercises the digital twin and synthetic camera pipeline without ROS. The
UI labels this SIMULATED; Qwen is still a real API call. Synthetic camera imagery
is not a piano scene and should not be presented as a successful hardware demo.

## Ninety-second live demo

1. Position the real left hand over the three rehearsed piano keys. Confirm the
   existing movement manually with the operator and start the cameras/ROS bridge.
2. Keep the digital twin, camera views and Qwen panel visible. Select the camera
   that clearly sees the keyboard and hand.
3. Click the microphone, say "What do you see? Can you play Hot Cross Buns on this?",
   then click it again. Capture ends automatically after 15 seconds.
4. Qwen's heard request, scene evidence and spoken reply appear. Press Execute
   within 30 seconds. The existing controller plays the routine; measured finger
   motion and movement progress remain visible. Record an episode with the existing bar.
5. Stop the routine, then ask a follow-up or hum a short recognizable tune from the
   two-song library. Qwen may ask for clarification when uncertain.
6. Ask about the scene or record a short sample of the piano and request feedback.
   This sends new audio and a fresh image. Feedback is observational, not a calibrated
   assessment of musical accuracy or mechanical safety.

The library currently contains Hot Cross Buns and Mary Had a Little Lamb. Additional
rehearsed movements use the existing `movements/` format; Qwen discovers them each turn.

## Implementation and limits

- Browser recording is decoded and converted to mono 16 kHz PCM WAV. Actual audio,
  not browser speech-recognition text, goes to Qwen with a fresh camera JPEG.
- Language covers intent, short conversation history, scene explanation and catalog
  selection. Spoken output uses browser speech synthesis; Qwen supplies the text.
- Requests are bounded, turn-based HTTP with provider SSE collected on the backend.
  This is not a continuous duplex/realtime audio session. UI reports measured turn latency.
- Camera frames and audio leave the device for the configured cloud provider only on
  submission. The app retains up to four text turns in memory; it does not save audio.
- Qwen cannot send raw joint targets or write executable movement code. Proposals are
  catalog names, single-use and expire after 30 seconds. Execution rechecks camera and
  hand telemetry freshness, ROS connectivity, backdrive, mirror and replay conflicts.
- Execute is an explicit operator action, separate from the manual-slider ARM switch.
  Existing HAL limits/contact handling remain responsible for motor behavior. Visual
  scene reasoning is not a safety certificate or a verified collision detector.
- Stop cancels movement scheduling and invalidates pending Qwen proposals. It does not
  disable torque or retract fingers, and it is not a hardware emergency stop. The last
  commanded pose may remain held. Other manual clients retain their existing controls.
- One console operator is assumed. Conversation/proposals are shared by this backend.
- No API key is bundled. Provider compatibility, microphone capture in the target browser,
  physical actuation, and melody recognition require a live rehearsal.

## API and verification

`GET /api/omni/status`; `POST /api/omni/turn` with `{text, audio?, camera}` (raw base64
WAV, camera `realsense` or `iphone`); `POST /api/omni/execute` with `{proposal_id}`;
`POST /api/omni/stop`; `POST /api/omni/reset` (also stops movements).

```bash
cd application/backend
python -m pytest tests/test_omni_core.py tests/test_omni_routes.py
cd ../frontend
npm run build
```

Challenge: https://github.com/cari-waterloo-rc/OMNI-Live-Build-the-Next-Generation-of-Real-Time-Multimodal-AI

Qwen protocol: https://www.alibabacloud.com/help/en/model-studio/qwen-omni
