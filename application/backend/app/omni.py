"""Camera-grounded Qwen turns and short-lived, single-use movement proposals."""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .movements import MovementError
from .omni_core import OmniError, QwenClient, validate_audio


class TurnRequest(BaseModel):
    text: str = Field(default="", max_length=2000)
    audio: str | None = Field(default=None, max_length=2_600_000)
    camera: str = Field(default="realsense", pattern="^(realsense|iphone)$")


class ExecuteRequest(BaseModel):
    proposal_id: str


def make_router(hub, source, movements, episodes, settings, mirror_active):
    router = APIRouter(prefix="/api/omni")
    client = QwenClient()
    busy = asyncio.Lock()
    history: list[dict] = []
    proposal = None
    generation = 0

    @router.get("/status")
    def status():
        return {"configured": client.configured, "model": client.model, "mock": settings.mock}

    @router.post("/turn")
    async def turn(request: TurnRequest):
        nonlocal proposal
        if not client.configured:
            raise HTTPException(503, "Set QWEN_API_KEY and QWEN_BASE_URL on the backend.")
        if busy.locked():
            raise HTTPException(409, "Qwen is already processing a turn.")
        if not request.text.strip() and not request.audio:
            raise HTTPException(422, "Say something or enter a request.")
        async with busy:
            proposal = None
            turn_generation = generation
            started = time.monotonic()
            channel = hub.frames[request.camera]["color"]
            channel.viewers += 1
            try:
                # Demand a NEW frame, including when nobody has the RGB panel open.
                _, frame = await asyncio.wait_for(channel.next(channel.version), 3)
            except asyncio.TimeoutError as error:
                raise HTTPException(409, "No fresh camera frame. Connect the selected camera.") from error
            finally:
                channel.viewers -= 1
            catalog = [m for m in movements.listing() if not m["error"]]
            snapshot = hub.snapshot(source.connected)
            context = {k: snapshot.get(k) for k in ("state", "blocked", "current", "objects", "passive", "ros_connected")}
            context.update(mock=settings.mock, camera=request.camera,
                           rotation_clockwise=hub.camera_meta(request.camera, "color").get("rotation", 0))
            content = [{"type": "text", "text": "Request: " + request.text + "\nCurrent context: " + json.dumps(context)},
                       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame.data).decode()}}]
            try:
                if request.audio:
                    content.append({"type": "input_audio", "input_audio": {
                        "data": "data:audio/wav;base64," + validate_audio(request.audio), "format": "wav"}})
                result = await asyncio.to_thread(client.complete, content, catalog, history.copy())
            except OmniError as error:
                raise HTTPException(502, str(error)) from error
            if generation != turn_generation:
                raise HTTPException(409, "Turn cancelled.")
            proposal_id = str(uuid.uuid4()) if result["movement"] else None
            if proposal_id:
                proposal = {"id": proposal_id, "name": result["movement"], "expires": time.monotonic() + 30,
                            "camera": request.camera}
            history.extend([{"role": "user", "content": request.text or result["heard"]},
                            {"role": "assistant", "content": json.dumps(result)}])
            del history[:-8]
            return {**result, "proposal_id": proposal_id, "expires_in": 30 if proposal_id else 0,
                    "elapsed_ms": round((time.monotonic() - started) * 1000), "model": client.model,
                    "camera": request.camera, "mock": settings.mock, "audio_received": bool(request.audio)}

    @router.post("/execute")
    async def execute(request: ExecuteRequest):
        nonlocal proposal
        if proposal is None or proposal["id"] != request.proposal_id or time.monotonic() > proposal["expires"]:
            proposal = None
            raise HTTPException(409, "Proposal expired or already used. Ask again.")
        if not source.connected or not hub.camera_meta(proposal["camera"], "color")["available"]:
            raise HTTPException(409, "Hand or camera disconnected.")
        age = hub.health(source.connected)["topics"]["hand_state"]["age_ms"]
        if age is None or age > 2000:
            raise HTTPException(409, "Hand telemetry is stale.")
        if hub.snapshot(source.connected)["passive"] or mirror_active() or episodes.status()["mode"] == "replaying":
            raise HTTPException(409, "Disable backdrive, mirror and episode replay before execution.")
        try:
            movements.play(proposal["name"])
        except MovementError as error:
            raise HTTPException(409, str(error)) from error
        proposal = None
        return movements.status()

    @router.post("/stop")
    async def stop():
        nonlocal proposal, generation
        generation += 1
        proposal = None
        await movements.stop()
        return {"stopped": True}

    @router.post("/reset")
    async def reset():
        await stop()
        history.clear()
        return {"reset": True}

    return router
