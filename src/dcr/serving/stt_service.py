"""Streaming speech recognition for every call in the process, decoded in dynamic batches.

The event loop that runs a call must never block. If decoding happened there, inbound audio
would queue up, turn decisions would be made on stale audio, and the echo canceller would
lose its alignment (all three happened before this existed). So calls only hand audio over,
and one decoder thread does the work.

Each pass, the thread moves every call's pending audio into its stream. It then decodes all
streams that have a full chunk ready in one `decode_streams` call, up to `max_batch` at a
time, so the encoder runs once per batch rather than once per call. That is where the
throughput comes from (docs/MEASUREMENTS.md, "Serving").

A call reads its latest transcript whenever it likes (`text`). Before a turn decision it can
wait for the decoder to catch up with everything it has fed (`await sync()`)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..speech import engines


@dataclass
class _Stream:
    stream: Any
    pending: deque[np.ndarray] = field(default_factory=deque)
    fed: int = 0  # samples handed over since the last reset (event-loop side)
    consumed: int = 0  # samples moved into the recogniser since the last reset (decoder side)
    decoded: int = 0  # `consumed` when `text` was last updated
    text: str = ""
    want_reset: bool = False
    waiters: list[tuple[int, asyncio.AbstractEventLoop, asyncio.Future[str]]] = field(default_factory=list)


@dataclass
class Stats:
    passes: int = 0
    decode_calls: int = 0
    streams_decoded: int = 0
    busy_s: float = 0.0
    batch_sizes: dict[int, int] = field(default_factory=dict)


class STTService:
    def __init__(self, model: str = "stt_en_nemo", max_batch: int = 8, max_wait_ms: float = 8.0) -> None:
        self.rec = engines._en_recognizer(model)
        self.max_batch = max_batch
        self.max_wait = max_wait_ms / 1000
        self.streams: dict[int, _Stream] = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stats = Stats()
        self._next = 0
        self._stop = False
        self.thread = threading.Thread(target=self._loop, name="dcr-stt", daemon=True)
        self.thread.start()

    def open(self) -> Handle:
        with self.lock:
            sid = self._next
            self._next += 1
            self.streams[sid] = _Stream(self.rec.create_stream())
        return Handle(self, sid)

    def close(self) -> None:
        self._stop = True
        self.wake.set()
        self.thread.join(5)

    def _loop(self) -> None:
        while not self._stop:
            self.wake.wait(self.max_wait)
            self.wake.clear()
            t0 = time.perf_counter()
            with self.lock:
                live = list(self.streams.values())
                for s in live:
                    if s.want_reset:
                        self.rec.reset(s.stream)
                        s.want_reset = False
                        s.consumed = s.decoded = 0
                        s.text = ""
                    while s.pending:
                        x = s.pending.popleft()
                        s.stream.accept_waveform(16000, x)
                        s.consumed += len(x)
            worked = False
            while True:
                ready = [s for s in live if self.rec.is_ready(s.stream)]
                if not ready:
                    break
                worked = True
                for i in range(0, len(ready), self.max_batch):
                    batch = ready[i : i + self.max_batch]
                    self.rec.decode_streams([s.stream for s in batch])
                    self.stats.decode_calls += 1
                    self.stats.streams_decoded += len(batch)
                    self.stats.batch_sizes[len(batch)] = self.stats.batch_sizes.get(len(batch), 0) + 1
            with self.lock:
                for s in live:
                    if s.want_reset:
                        continue  # a reset arrived while decoding: this text is stale
                    if s.consumed != s.decoded:
                        s.text = str(self.rec.get_result(s.stream)).strip().lower()
                        s.decoded = s.consumed
                    keep = []
                    for want, loop, fut in s.waiters:
                        if s.decoded >= want:
                            loop.call_soon_threadsafe(_resolve, fut, s.text)
                        else:
                            keep.append((want, loop, fut))
                    s.waiters = keep
            if worked:
                self.stats.passes += 1
                self.stats.busy_s += time.perf_counter() - t0


def _resolve(fut: asyncio.Future[str], text: str) -> None:
    if not fut.done():
        fut.set_result(text)


class Handle:
    """One call's view of the service: the same interface as `engines.StreamingSTT`, plus `sync`."""

    lang = "en"

    def __init__(self, svc: STTService, sid: int, flush_seconds: float = 0.4) -> None:
        self.svc = svc
        self.sid = sid
        self.flush_seconds = flush_seconds

    @property
    def text(self) -> str:
        s = self.svc.streams.get(self.sid)
        return s.text if s else ""

    def feed(self, x16: np.ndarray) -> str:
        with self.svc.lock:
            s = self.svc.streams[self.sid]
            s.pending.append(np.asarray(x16, dtype=np.float32))
            s.fed += len(x16)
        self.svc.wake.set()
        return self.text

    def flush(self, seconds: float | None = None) -> str:
        return self.feed(np.zeros(int(16000 * (seconds or self.flush_seconds)), dtype=np.float32))

    async def sync(self, wait_s: float = 1.0) -> str:
        """The transcript once everything fed so far has been decoded (or the latest after
        `wait_s`, so a slow decoder can delay a turn but never hang it)."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        with self.svc.lock:
            s = self.svc.streams[self.sid]
            if s.decoded >= s.fed and not s.pending and not s.want_reset:
                return s.text
            s.waiters.append((s.fed, loop, fut))
        self.svc.wake.set()
        try:
            return await asyncio.wait_for(fut, wait_s)
        except TimeoutError:
            return self.text

    def reset(self) -> None:
        with self.svc.lock:
            s = self.svc.streams[self.sid]
            s.pending.clear()
            s.want_reset = True
            s.fed = 0
            s.text = ""
            for _, loop, fut in s.waiters:
                loop.call_soon_threadsafe(_resolve, fut, "")
            s.waiters = []
        self.svc.wake.set()

    def close(self) -> None:
        with self.svc.lock:
            self.svc.streams.pop(self.sid, None)
