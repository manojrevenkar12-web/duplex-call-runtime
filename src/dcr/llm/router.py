"""Streaming LLM calls that a caller on the phone never has to wait for twice.

Any OpenAI-compatible endpoint works (vLLM, OpenAI, gateways in front of other vendors). The
router adds three things on top of a plain client:

- **Hedging.** If the first provider has not produced a token after `hedge_after_ms`, the same
  request goes to the next provider too, and whichever answers first wins; the loser is
  cancelled. A slow tail on one provider stops being the caller's problem.
- **Timeouts that mean something in a call.** No first token within `first_token_timeout_ms`,
  or a stream that goes quiet for `stall_timeout_ms`, counts as a failure.
- **Circuit breaking.** A provider that failed `failures` times in `window_s` is skipped for
  `open_s`, so a dead provider does not cost every turn a hedge delay.

Every request reports which provider won, its time to first token, and whether it was hedged,
so the call timeline shows where each millisecond went."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Text:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Done:
    provider: str
    ttft_ms: float
    hedged: bool
    attempts: list[str]


class LLMUnavailable(RuntimeError):
    """No provider produced a first token in time."""


class StreamBroken(RuntimeError):
    """The winning stream failed after it had started speaking."""

    def __init__(self, emitted: str, provider: str) -> None:
        super().__init__(f"{provider} stream broke after {len(emitted)} chars")
        self.emitted = emitted
        self.provider = provider


@dataclass
class Breaker:
    failures: int
    window_s: float
    open_s: float
    times: deque[float] = field(default_factory=deque)
    open_until: float = 0.0

    def allows(self, now: float) -> bool:
        return now >= self.open_until

    def fail(self, now: float) -> None:
        self.times.append(now)
        while self.times and now - self.times[0] > self.window_s:
            self.times.popleft()
        if len(self.times) >= self.failures:
            self.open_until = now + self.open_s
            self.times.clear()

    def succeed(self) -> None:
        self.times.clear()


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str = ""
    model: str | None = None  # this provider's name for the model; `llm.model` if unset


@dataclass
class _Attempt:
    provider: Provider
    task: asyncio.Task[None]
    queue: asyncio.Queue[tuple[str, Any]]
    started: float


class Router:
    def __init__(self, settings: dict[str, Any], client: httpx.AsyncClient | None = None) -> None:
        llm = settings["llm"]
        self.cfg = llm
        self.providers = [
            Provider(p["name"], p["base_url"].rstrip("/"), os.environ.get(p.get("api_key_env", ""), ""), p.get("model"))
            for p in llm["providers"]
        ]
        c = llm["circuit"]
        self.breakers = {p.name: Breaker(int(c["failures"]), float(c["window_s"]), float(c["open_s"])) for p in self.providers}
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None), limits=httpx.Limits(max_keepalive_connections=20))

    async def aclose(self) -> None:
        await self.client.aclose()

    def _order(self) -> list[Provider]:
        now = time.monotonic()
        open_ = [p for p in self.providers if self.breakers[p.name].allows(now)]
        return open_ or list(self.providers)  # all open: try anyway rather than fail the caller

    def _start(self, p: Provider, body: dict[str, Any]) -> _Attempt:
        q: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        task = asyncio.create_task(self._pump(p, {**body, "model": p.model or body["model"]}, q))
        return _Attempt(p, task, q, time.monotonic())

    async def _pump(self, p: Provider, body: dict[str, Any], q: asyncio.Queue[tuple[str, Any]]) -> None:
        headers = {"Authorization": f"Bearer {p.api_key}"} if p.api_key else {}
        tool: dict[str, Any] | None = None
        try:
            async with self.client.stream("POST", f"{p.base_url}/chat/completions", json=body, headers=headers) as r:
                if r.status_code != 200:
                    await q.put(("error", f"HTTP {r.status_code}"))
                    return
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    doc = json.loads(data)
                    choice = (doc.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        await q.put(("text", delta["content"]))
                    for tc in delta.get("tool_calls") or []:
                        if tool is None:
                            tool = {"id": tc.get("id", ""), "name": "", "arguments": ""}
                            await q.put(("first", None))
                        fn = tc.get("function") or {}
                        tool["name"] += fn.get("name") or ""
                        tool["arguments"] += fn.get("arguments") or ""
                    if choice.get("finish_reason"):
                        break
            if tool is not None:
                await q.put(("tool", ToolCall(tool["id"], tool["name"], json.loads(tool["arguments"] or "{}"))))
            await q.put(("done", None))
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            await q.put(("error", f"{type(e).__name__}: {e}"))

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[Text | ToolCall | Done]:
        body: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": messages,
            "stream": True,
            "temperature": self.cfg["temperature"],
            "max_tokens": self.cfg["max_tokens"],
        }
        if tools:
            body["tools"] = tools
        hedge_after = float(self.cfg["hedge_after_ms"]) / 1000
        first_timeout = float(self.cfg["first_token_timeout_ms"]) / 1000
        stall = float(self.cfg["stall_timeout_ms"]) / 1000
        order = self._order()
        attempts: list[_Attempt] = []
        tried: list[str] = []
        t0 = time.monotonic()
        winner: _Attempt | None = None
        first: tuple[str, Any] | None = None
        hedged = False
        try:
            # race for the first token: start the next provider when the current ones are slow or fail
            while winner is None:
                if not attempts or (time.monotonic() - attempts[-1].started >= hedge_after and len(attempts) < len(order)):
                    if len(attempts) >= len(order):
                        break
                    if attempts:
                        hedged = True
                    a = self._start(order[len(attempts)], body)
                    attempts.append(a)
                    tried.append(a.provider.name)
                live = [a for a in attempts if not a.task.done() or not a.queue.empty()]
                if not live and len(attempts) >= len(order):
                    break
                if time.monotonic() - t0 > first_timeout * len(order):
                    break
                getters = {asyncio.ensure_future(a.queue.get()): a for a in live}
                wait = hedge_after - (time.monotonic() - attempts[-1].started) if len(attempts) < len(order) else first_timeout
                done, pending = await asyncio.wait(getters, timeout=max(0.01, wait), return_when=asyncio.FIRST_COMPLETED)
                for g in pending:
                    g.cancel()
                for g in done:
                    a = getters[g]
                    kind, val = g.result()
                    if kind == "error":
                        self.breakers[a.provider.name].fail(time.monotonic())
                        a.task.cancel()
                        attempts_left = len(attempts) < len(order)
                        if attempts_left:
                            # fail over at once, do not wait for the hedge timer
                            nxt = self._start(order[len(attempts)], body)
                            attempts.append(nxt)
                            tried.append(nxt.provider.name)
                    elif winner is None:
                        winner, first = a, (kind, val)
                    else:
                        a.queue.put_nowait((kind, val))
                # a provider that is too slow even for the first token is a failure
                for a in attempts:
                    if a is not winner and not a.task.done() and time.monotonic() - a.started > first_timeout:
                        self.breakers[a.provider.name].fail(time.monotonic())
                        a.task.cancel()
            if winner is None or first is None:
                raise LLMUnavailable(f"no first token from {tried}")
            for a in attempts:
                if a is not winner:
                    a.task.cancel()
            ttft = (time.monotonic() - t0) * 1000
            emitted = ""
            kind, val = first
            while True:
                if kind == "text":
                    emitted += val
                    yield Text(val)
                elif kind == "tool":
                    yield val
                elif kind == "done":
                    self.breakers[winner.provider.name].succeed()
                    yield Done(winner.provider.name, ttft, hedged, tried)
                    return
                elif kind == "error":
                    self.breakers[winner.provider.name].fail(time.monotonic())
                    raise StreamBroken(emitted, winner.provider.name)
                try:
                    kind, val = await asyncio.wait_for(winner.queue.get(), timeout=stall)
                except TimeoutError:
                    self.breakers[winner.provider.name].fail(time.monotonic())
                    raise StreamBroken(emitted, winner.provider.name) from None
        finally:
            for a in attempts:
                a.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await a.task
