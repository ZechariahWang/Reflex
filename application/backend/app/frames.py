"""Latest-frame-only fan-out for image streams."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


@dataclass(frozen=True)
class Frame:
    data: bytes
    width: int
    height: int


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) read from the JPEG start-of-frame header, (0, 0) if absent."""
    i = 2
    while i + 9 <= len(data) and data[i] == 0xFF:
        if data[i + 1] in _SOF_MARKERS:
            return int.from_bytes(data[i + 7 : i + 9], "big"), int.from_bytes(data[i + 5 : i + 7], "big")
        i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
    return 0, 0


class LatestChannel(Generic[T]):
    """Holds only the newest item; every consumer awaits 'something newer than I saw'.

    A slow consumer simply skips items. Nothing is queued, and consumers never
    affect each other. Event-loop thread only.
    """

    def __init__(self) -> None:
        self.latest: T | None = None
        self.viewers = 0  # open sockets on this stream; producers skip work nobody sees
        self._seq = 0
        self._waiters: set[asyncio.Future[None]] = set()

    def publish(self, item: T) -> None:
        self.latest = item
        self._seq += 1
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()

    @property
    def version(self) -> int:
        """Goes up with every publish: whoever polls `latest` sees whether it is a new item."""
        return self._seq

    async def next(self, seen: int) -> tuple[int, T]:
        """Wait for an item newer than sequence number `seen` (0 = any)."""
        while self._seq == seen or self.latest is None:
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.add(waiter)
            try:
                await waiter
            finally:
                self._waiters.discard(waiter)
        return self._seq, self.latest
