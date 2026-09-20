"""FastAPI service: the only thing between the browser and ROS."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Coroutine, Sequence

import yaml
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from .config import Settings
from .episodes import EpisodeError, Episodes
from .movements import MovementError, Movements
from .omni import make_router as make_omni_router
from .hub import CAMERA_STREAMS, Hub, Source, parse_command, parse_passive, ticks
from .frames import LatestChannel
from .mirror.session import MirrorSession, Tracker, parse_calibrate
from .mirror.synthetic import MockTracker
from .mock import MockSource, run_mock_objects
from .ros_client import RosClient

STATE_PERIOD_S = 1 / 60  # one /ws/state message per display frame
META_PERIOD_S = 1.0
MAX_MIRROR_FRAME_BYTES = 1_000_000  # a 320x240 JPEG is ~15 kB
# A client that has said "ready" once gets the next frame only after its next "ready"; a lost
# one is forgiven after this long so the stream can never wedge.
READY_TIMEOUT_S = 3.0

MESH_NAME = re.compile(r"^[a-z0-9_]+\.stl$")

LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def admit(ws: WebSocket, allowed_origins: Sequence[str]) -> bool:
    """Accept the socket unless its page comes from somewhere else.

    Browsers always send Origin, and CORS does not cover websockets, so a page from
    anywhere else is turned away here. Clients without one (CLI tools, tests) pass.
    """
    origin = ws.headers.get("origin")
    if origin is not None and origin not in allowed_origins:
        LOGGER.warning("refusing websocket from origin %s", origin)
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return False
    await ws.accept()
    return True


async def serve_socket(
    ws: WebSocket,
    allowed_origins: Sequence[str],
    sender: Callable[[], Coroutine[None, None, None]],
    on_text: Callable[[str], None] | None = None,
    on_bytes: Callable[[bytes], None] | None = None,
) -> None:
    """Run `sender` until the client goes away or it fails; incoming messages go to `on_text` / `on_bytes`."""
    if not await admit(ws, allowed_origins):
        return
    await run_socket(ws, sender, on_text, on_bytes)


async def run_socket(
    ws: WebSocket,
    sender: Callable[[], Coroutine[None, None, None]],
    on_text: Callable[[str], None] | None = None,
    on_bytes: Callable[[bytes], None] | None = None,
) -> None:

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
            if on_bytes is not None and message.get("bytes") is not None:
                on_bytes(message["bytes"])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class Readiness:
    """Backpressure for one camera socket. The socket's send buffer is unbounded, so a browser
    that paints slower than the camera runs would otherwise watch a growing backlog of old
    frames (minutes, on a busy laptop). Once the client has sent "ready", every frame waits
    for the next "ready"; a client that never sends one is served as before."""

    def __init__(self, timeout_s: float = READY_TIMEOUT_S) -> None:
        self.acknowledges = False
        self._timeout_s = timeout_s
        self._ready = asyncio.Event()

    def on_text(self, text: str) -> None:
        if text.strip() == "ready":
            self.acknowledges = True
            self._ready.set()

    async def wait(self) -> None:
        """Returns at once for a client that never acknowledges; otherwise once per "ready" (or timeout)."""
        if not self.acknowledges:
            return
        try:
            await asyncio.wait_for(self._ready.wait(), self._timeout_s)
        except asyncio.TimeoutError:
            pass
        self._ready.clear()


class RecordRequest(BaseModel):
    dataset: str
    task: str = ""


class ReplayRequest(BaseModel):
    dataset: str
    episode: int
    what: str = "action"
    speed: float = 1.0


class MovementRequest(BaseModel):
    name: str


class StepModel(BaseModel):
    pose: list[float]
    seconds: float


class TeachRequest(BaseModel):
    title: str = ""
    description: str = ""
    steps: list[StepModel]


class CommandRequest(BaseModel):
    values: list[float]


class StopRequest(BaseModel):
    keep: bool = True


def create_app(settings: Settings) -> FastAPI:
    hub = Hub(settings)
    source: Source = MockSource(hub) if settings.mock else RosClient(settings, hub)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        hub.bind(asyncio.get_running_loop())
        workers = [asyncio.create_task(hub.run_depth_worker())]
        if not settings.mock:
            workers.append(
                asyncio.create_task(
                    hub.run_object_worker(settings.detect_model, settings.detect_hz, settings.detect_threads)
                )
            )
            if settings.mock_objects:
                workers.append(asyncio.create_task(run_mock_objects(hub)))
        source.start()
        yield
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

    # Episodes: record what the console sees and play it back (app/episodes.py). The status of a
    # running recording or replay is `session` in /ws/state.
    episodes = Episodes(settings.recordings_dir, hub, source.send_command)

    movements = Movements(settings.movements_dir, source.send_command, lambda: hub.hand_state)

    def refuse(error: ValueError) -> HTTPException:
        return HTTPException(status.HTTP_409_CONFLICT, str(error))

    @app.get("/api/episodes")
    def list_episodes() -> dict:
        return {"session": episodes.status(), "datasets": episodes.datasets()}

    @app.post("/api/episodes/record")
    async def record_episode(request: RecordRequest) -> dict:
        try:
            episodes.start_recording(request.dataset, request.task)
        except EpisodeError as error:
            raise refuse(error) from error
        return episodes.status()

    @app.post("/api/episodes/replay")
    async def replay_episode(request: ReplayRequest) -> dict:
        try:
            if movements.playing:
                raise EpisodeError("a movement is playing: stop it first")
            episodes.start_replay(request.dataset, request.episode, request.what, request.speed)
        except EpisodeError as error:
            raise refuse(error) from error
        return episodes.status()

    # Movements: the scripts of the repo's movements/ folder, played on /hand/command. One may play
    # while an episode is recorded (a way to record demonstrations), not during a replay.
    @app.get("/api/movements")
    def list_movements() -> list[dict]:
        return movements.listing()

    @app.get("/api/movements/{name}")
    def read_movement(name: str) -> dict:
        try:
            return movements.read(name)
        except MovementError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    @app.put("/api/movements/{name}")
    def teach_movement(name: str, request: TeachRequest) -> dict:
        """A hard-coded path from whoever teaches (the MCP server, a script): saved as movements/<name>.py."""
        try:
            return movements.teach(name, request.title, request.description, [s.model_dump() for s in request.steps])
        except MovementError as error:
            raise refuse(error) from error

    @app.delete("/api/movements/{name}")
    def forget_movement(name: str) -> dict:
        try:
            movements.forget(name)
        except MovementError as error:
            raise refuse(error) from error
        return {}

    # The same over plain HTTP as /ws/state gives and takes: for clients that are not a page
    @app.get("/api/state")
    def state() -> dict:
        return {**hub.snapshot(source.connected), "session": episodes.status(), "movement": movements.status()}

    @app.post("/api/command")
    def command(request: CommandRequest) -> dict:
        values = parse_command(json.dumps({"type": "command", "data": request.values}))
        if values is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "values: 5 numbers, thumb .. pinky, 0 = open .. 1 = closed")
        source.send_command(values)
        return {"sent": values}

    @app.post("/api/movements/play")
    async def play_movement(request: MovementRequest) -> dict:
        try:
            if episodes.status()["mode"] == "replaying":
                raise MovementError("a replay is running: stop it first")
            movements.play(request.name)
        except MovementError as error:
            raise refuse(error) from error
        return movements.status() or {}

    @app.post("/api/movements/stop")
    async def stop_movement() -> dict:
        await movements.stop()
        return {}

    @app.post("/api/episodes/stop")
    async def stop_episode(request: StopRequest) -> dict:
        await episodes.stop(request.keep)
        return {"session": episodes.status(), "datasets": episodes.datasets()}

    @app.get("/api/urdf")
    def urdf() -> Response:
        xml = hub.urdf
        if xml is None:
            return Response("robot_description has not arrived yet", status_code=503, media_type="text/plain")
        return Response(xml, media_type="text/xml")

    @app.get("/api/meshes/{name}")
    def mesh(name: str) -> FileResponse:
        """A visual of the URDF: `package://htn_description/meshes/<name>` (STL, millimetres)."""
        path = settings.description_dir / "meshes" / name
        if not MESH_NAME.fullmatch(name) or not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such mesh")
        return FileResponse(path, media_type="model/stl", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/linkage")
    def linkage() -> dict:
        """Pivots of every finger's linkage (config/linkage.yaml). The URDF is a tree and cannot
        say where its loops close, and the viewer has to pose a commanded hand ROS never publishes."""
        path = settings.description_dir / "config" / "linkage.yaml"
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no linkage.yaml in the description package")
        return yaml.safe_load(path.read_text())["fingers"]

    @app.websocket("/ws/state")
    async def ws_state(ws: WebSocket) -> None:
        async def send_state() -> None:
            async for _ in ticks(STATE_PERIOD_S):
                await ws.send_text(json.dumps({**hub.snapshot(source.connected), "session": episodes.status(), "movement": movements.status()}))

        def on_text(text: str) -> None:
            values = parse_command(text)
            if values is not None:
                source.send_command(values)
            passive = parse_passive(text)
            if passive is not None:
                source.set_passive(passive)

        await serve_socket(ws, settings.cors_origins, send_state, on_text)

    async def send_camera(ws: WebSocket, source: str, kind: str, readiness: Readiness) -> None:
        channel = hub.frames[source][kind]
        channel.viewers += 1  # producers only render streams somebody has open
        try:
            await stream_camera(ws, source, kind, readiness)
        finally:
            channel.viewers -= 1

    async def stream_camera(ws: WebSocket, source: str, kind: str, readiness: Readiness) -> None:
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
            await readiness.wait()
            # Newest frame at the moment the client is ready, not the one that woke us
            if channel.latest is not None:
                frame = channel.latest
            await ws.send_bytes(frame.data)

    @app.websocket("/ws/camera/{camera}/{kind}")
    async def ws_camera(ws: WebSocket, camera: str, kind: str) -> None:
        if kind not in CAMERA_STREAMS.get(camera, ()):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        readiness = Readiness()
        await serve_socket(ws, settings.cors_origins, lambda: send_camera(ws, camera, kind, readiness), readiness.on_text)

    mirror_busy = False
    app.include_router(make_omni_router(hub, source, movements, episodes, settings, lambda: mirror_busy))

    def make_tracker() -> Tracker:
        if settings.mock:
            return MockTracker()
        from .mirror.tracker import MediaPipeTracker  # mediapipe is slow to import and the mock needs none of it

        return MediaPipeTracker()

    @app.websocket("/ws/mirror")
    async def ws_mirror(ws: WebSocket) -> None:
        """The controller's webcam frames in, the mirror's status out; it commands the hand."""
        nonlocal mirror_busy
        if not await admit(ws, settings.cors_origins):
            return
        if mirror_busy:
            await ws.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="another controller is connected")
            return
        mirror_busy = True
        tracker: Tracker | None = None
        try:
            tracker = await asyncio.to_thread(make_tracker)
            session = MirrorSession(settings, lambda: hub.hand_state, source.send_command)
            frames: LatestChannel[bytes] = LatestChannel()

            async def send_status() -> None:
                seen = 0
                while True:
                    seen, jpeg = await frames.next(seen)
                    hand = await asyncio.to_thread(tracker.detect, jpeg)
                    await ws.send_text(json.dumps(session.on_hand(hand, time.monotonic())))

            def on_text(text: str) -> None:
                pose = parse_calibrate(text)
                if pose is not None:
                    session.calibrate(pose, time.monotonic())
                    if isinstance(tracker, MockTracker):
                        tracker.hold(pose)

            def on_bytes(jpeg: bytes) -> None:
                if len(jpeg) <= MAX_MIRROR_FRAME_BYTES:
                    frames.publish(jpeg)

            await run_socket(ws, send_status, on_text, on_bytes)
        finally:
            mirror_busy = False
            if tracker is not None:
                tracker.close()

    return app


app = create_app(Settings.from_env())
