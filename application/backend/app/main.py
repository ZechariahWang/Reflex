"""FastAPI service: the only thing between the browser and ROS."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Coroutine, Sequence

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import Settings
from .hub import CAMERA_KINDS, CAMERA_SOURCES, Hub, Source, parse_command, ticks
from .mock import MockSource
from .record3d import ROTATIONS, Record3DClient, normalize_host
from .ros_client import RosClient

STATE_PERIOD_S = 0.033
META_PERIOD_S = 1.0

MOCK_PHONE = {"host": "mock", "state": "streaming", "detail": ""}

LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


class PhoneSettings(BaseModel):
    """Either field may be left out: the address form sends `host`, the rotate button `rotation`."""

    host: str | None = None
    rotation: int | None = None


async def serve_socket(
    ws: WebSocket,
    allowed_origins: Sequence[str],
    sender: Callable[[], Coroutine[None, None, None]],
    on_text: Callable[[str], None] | None = None,
) -> None:
    """Run `sender` until the client goes away or it fails; incoming text goes to `on_text`.

    Browsers always send Origin, and CORS does not cover websockets, so a page from
    anywhere else is turned away here. Clients without one (CLI tools, tests) pass.
    """
    origin = ws.headers.get("origin")
    if origin is not None and origin not in allowed_origins:
        LOGGER.warning("refusing websocket from origin %s", origin)
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()

    async def send() -> None:
        try:
            await sender()
        except WebSocketDisconnect:
            pass
        except Exception:
            # Closing wakes the receive loop below, and the browser reconnects instead of
            # watching an open but silent stream.
            LOGGER.exception("websocket %s sender failed", ws.url.path)
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)

    task = asyncio.create_task(send())
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if on_text is not None and message.get("text") is not None:
                on_text(message["text"])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def create_app(settings: Settings) -> FastAPI:
    hub = Hub(settings)
    source: Source = MockSource(hub) if settings.mock else RosClient(settings, hub)
    phone = Record3DClient(hub.on_iphone_frame, normalize_host(settings.record3d_host) or "")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        hub.bind(asyncio.get_running_loop())
        workers = [asyncio.create_task(hub.run_depth_worker()), asyncio.create_task(hub.run_iphone_worker())]
        source.start()
        if not settings.mock:
            phone.start()
        yield
        await phone.stop()
        await source.stop()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    app = FastAPI(title="htn simulator backend", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/health")
    def health() -> dict:
        return hub.health(source.connected)

    @app.get("/api/urdf")
    def urdf() -> Response:
        xml = hub.urdf
        if xml is None:
            return Response("robot_description has not arrived yet", status_code=503, media_type="text/plain")
        return Response(xml, media_type="text/xml")

    def phone_status() -> dict:
        return {**(MOCK_PHONE if settings.mock else phone.status()), "rotation": hub.iphone_rotation}

    @app.get("/api/iphone")
    def iphone() -> dict:
        return phone_status()

    @app.post("/api/iphone")
    async def set_iphone(update: PhoneSettings) -> dict:
        """Point the Record3D client at a phone (an empty host disconnects) and / or turn its image."""
        if update.rotation is not None:
            if update.rotation not in ROTATIONS:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "rotation must be 0, 90, 180 or 270")
            hub.iphone_rotation = update.rotation
        if update.host is not None and not settings.mock:
            host = normalize_host(update.host) if update.host.strip() else ""
            if host is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "expected an address like 192.168.1.23")
            if host != phone.host:
                await phone.set_host(host)
        return phone_status()

    @app.websocket("/ws/state")
    async def ws_state(ws: WebSocket) -> None:
        async def send_state() -> None:
            async for _ in ticks(STATE_PERIOD_S):
                await ws.send_text(json.dumps(hub.snapshot(source.connected)))

        def on_text(text: str) -> None:
            values = parse_command(text)
            if values is not None:
                source.send_command(values)

        await serve_socket(ws, settings.cors_origins, send_state, on_text)

    async def send_camera(ws: WebSocket, source: str, kind: str) -> None:
        channel = hub.frames[source][kind]
        channel.viewers += 1  # producers only render streams somebody has open
        try:
            await stream_camera(ws, source, kind)
        finally:
            channel.viewers -= 1

    async def stream_camera(ws: WebSocket, source: str, kind: str) -> None:
        channel = hub.frames[source][kind]
        seen = 0
        sent_meta: dict | None = None
        sent_at = 0.0
        while True:
            meta = hub.camera_meta(source, kind)
            # Shape changes go out at once; a merely drifting hz at most once per period.
            reshaped = sent_meta is None or {**meta, "hz": sent_meta["hz"]} != sent_meta
            if reshaped or (meta != sent_meta and time.monotonic() - sent_at >= META_PERIOD_S):
                await ws.send_text(json.dumps(meta))
                sent_meta, sent_at = meta, time.monotonic()
            try:
                seen, frame = await asyncio.wait_for(channel.next(seen), META_PERIOD_S)
            except asyncio.TimeoutError:
                continue
            await ws.send_bytes(frame.data)

    @app.websocket("/ws/camera/{camera}/{kind}")
    async def ws_camera(ws: WebSocket, camera: str, kind: str) -> None:
        if camera not in CAMERA_SOURCES or kind not in CAMERA_KINDS:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await serve_socket(ws, settings.cors_origins, lambda: send_camera(ws, camera, kind))

    return app


app = create_app(Settings.from_env())
