"""Run an ASGI app on a local port in a background thread (simulated providers, tests, benchmarks)."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Background:
    def __init__(self, app: Any, port: int | None = None) -> None:
        self.port = port or free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on", ws="websockets-sansio")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> Background:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(5)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
