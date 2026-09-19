"""A stand-in for an iPhone running Record3D in Wi-Fi streaming mode.

Speaks the same protocol (GET /getOffer, POST /answer, GET /metadata) and streams
the mock scene as a real WebRTC track: hue-encoded depth on the left, RGB on the
right. Also a dev tool when no phone is around:

    .venv/bin/python -m tests.fake_record3d --port 8099      # then connect to localhost:8099
"""

from __future__ import annotations

import argparse
import time

import uvicorn
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from fastapi import FastAPI, Request

from app.mock import Scene


class SceneTrack(VideoStreamTrack):
    def __init__(self) -> None:
        super().__init__()
        self._scene = Scene()

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()
        frame = VideoFrame.from_ndarray(self._scene.record3d_frame(time.monotonic()), format="bgr24")
        frame.pts, frame.time_base = pts, time_base
        return frame


def create_phone() -> FastAPI:
    phone = FastAPI()
    peers: list[RTCPeerConnection] = []

    @phone.get("/getOffer")
    async def get_offer() -> dict:
        for old in peers:  # one viewer at a time, like the real app
            await old.close()
        peers.clear()
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        peers.append(peer)
        peer.addTrack(SceneTrack())
        await peer.setLocalDescription(await peer.createOffer())
        return {"type": "offer", "sdp": peer.localDescription.sdp}

    @phone.post("/answer")
    async def answer(request: Request) -> str:
        body = await request.json()
        await peers[-1].setRemoteDescription(RTCSessionDescription(sdp=body["data"], type=body["type"]))
        return "ok"

    @phone.get("/metadata")
    def metadata() -> dict:
        return {"K": [500.0, 0.0, 0.0, 0.0, 500.0, 0.0, 320.0, 240.0, 1.0], "originalSize": [640, 480]}

    return phone


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    uvicorn.run(create_phone(), host="0.0.0.0", port=parser.parse_args().port, log_level="warning")
