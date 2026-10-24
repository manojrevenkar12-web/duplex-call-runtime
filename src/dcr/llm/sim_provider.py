"""A simulated LLM provider that speaks the OpenAI chat-completions streaming protocol.

The runtime's client cannot tell it from vLLM or OpenAI: same endpoint, same server-sent
events, same tool-call deltas. What it adds is control over the things a voice agent has to
survive: time to first token (log-normal, with a slow tail), token rate, HTTP errors, and
streams that stall halfway. The receptionist policy in `brain.py` writes the content.

Faults can be changed while it runs (POST /control), so an evaluation can take a provider
down in the middle of a call and check that the caller never notices."""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import brain


@dataclass
class Profile:
    ttft_median_ms: float = 380.0
    ttft_sigma: float = 0.35  # log-normal spread: p95 is about 1.8x the median
    slow_rate: float = 0.0  # share of requests that take slow_ms extra before the first token
    slow_ms: float = 1500.0
    tokens_per_s: float = 70.0
    error_rate: float = 0.0  # share of requests answered with HTTP 503
    stall_rate: float = 0.0  # share of streams that stop sending after a few tokens
    seed: int = 7


def make_app(profile: Profile | None = None, name: str = "sim") -> FastAPI:
    app = FastAPI(title=f"simulated LLM provider ({name})")
    state: dict[str, Any] = {"profile": profile or Profile(), "requests": 0}
    rng = random.Random(state["profile"].seed)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "name": name, "requests": state["requests"], "profile": asdict(state["profile"])}

    @app.post("/control")
    async def control(body: dict[str, Any]) -> dict[str, Any]:
        p = state["profile"]
        for k, v in body.items():
            if hasattr(p, k):
                setattr(p, k, type(getattr(p, k))(v))
        return asdict(p)

    @app.post("/v1/chat/completions", response_model=None)
    async def completions(request: Request) -> Any:
        body = await request.json()
        state["requests"] += 1
        p: Profile = state["profile"]
        if rng.random() < p.error_rate:
            return JSONResponse({"error": {"message": "simulated overload", "type": "server_error"}}, status_code=503)
        turn = brain.next_turn(body.get("messages", []))
        ttft = rng.lognormvariate(0, p.ttft_sigma) * p.ttft_median_ms
        if rng.random() < p.slow_rate:
            ttft += p.slow_ms
        stall = rng.random() < p.stall_rate
        rid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = body.get("model", "sim")

        def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
            doc = {
                "id": rid,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return f"data: {json.dumps(doc)}\n\n"

        async def stream() -> Any:
            await asyncio.sleep(ttft / 1000)
            yield chunk({"role": "assistant", "content": ""})
            if "tool_call" in turn:
                tc = turn["tool_call"]
                call = {
                    "index": 0,
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": ""},
                }
                yield chunk({"tool_calls": [call]})
                args = json.dumps(tc["arguments"])
                for i in range(0, len(args), 24):
                    await asyncio.sleep(1 / p.tokens_per_s)
                    yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[i : i + 24]}}]})
                yield chunk({}, "tool_calls")
            else:
                pieces = _tokens(turn["content"])
                for n, piece in enumerate(pieces):
                    if stall and n == max(2, len(pieces) // 3):
                        await asyncio.sleep(3600)  # the connection stays open and nothing more comes
                    await asyncio.sleep(1 / p.tokens_per_s)
                    yield chunk({"content": piece})
                yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _tokens(text: str) -> list[str]:
    """Roughly what a tokenizer does to English or German: words with their leading space."""
    out, word = [], ""
    for ch in text:
        if ch == " " and word:
            out.append(word)
            word = " "
        else:
            word += ch
    if word:
        out.append(word)
    return out
