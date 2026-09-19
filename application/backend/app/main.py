"""FastAPI service: the only thing between the browser and ROS."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Coroutine, Sequence

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .hub import Hub, Source, parse_command, ticks
from .mock import MockSource
from .ros_client import RosClient

STATE_PERIOD_S = 0.033
META_PERIOD_S = 1.0

LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        hub.bind(asyncio.get_running_loop())
        depth_worker = asyncio.create_task(hub.run_depth_worker())
        source.start()
        yield
        await source.stop()
        depth_worker.cancel()
        await asyncio.gather(depth_worker, return_exceptions=True)

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

    async def send_camera(ws: WebSocket, kind: str) -> None:
        channel = hub.frames[kind]
        seen = 0
        sent_meta: dict | None = None
        sent_at = 0.0
        while True:
            meta = hub.camera_meta(kind)
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

    @app.websocket("/ws/camera/color")
    async def ws_color(ws: WebSocket) -> None:
        await serve_socket(ws, settings.cors_origins, lambda: send_camera(ws, "color"))

    @app.websocket("/ws/camera/depth")
    async def ws_depth(ws: WebSocket) -> None:
        await serve_socket(ws, settings.cors_origins, lambda: send_camera(ws, "depth"))

    return app


app = create_app(Settings.from_env())
