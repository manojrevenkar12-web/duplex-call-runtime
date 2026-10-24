"""The runtime as a service: Twilio Media Streams over WebSocket, TwiML to connect a number,
the call inspector API, and Prometheus metrics.

A real phone number is connected by pointing its voice webhook at `POST /twilio/voice`, which
answers with TwiML that streams the call to `/media`. The simulated callers in `dcr.sim` speak
exactly the same protocol, so every test call exercises the production path."""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from . import config
from .agent.report import summarise
from .agent.session import CallSession, Options
from .llm.router import Router
from .serving.stt_service import STTService
from .store import Store


class WsTransport:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.stream_sid = ""

    async def _send(self, msg: dict[str, Any]) -> None:
        # the caller may have hung up; the session closes on the receive side
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await self.ws.send_text(json.dumps(msg))

    async def send_media(self, ulaw: bytes) -> None:
        await self._send({"event": "media", "streamSid": self.stream_sid, "media": {"payload": base64.b64encode(ulaw).decode()}})

    async def send_mark(self, name: str) -> None:
        await self._send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})

    async def send_clear(self) -> None:
        await self._send({"event": "clear", "streamSid": self.stream_sid})


def create_app(settings: dict[str, Any] | None = None, store: Store | None = None) -> FastAPI:
    cfg = settings or config.settings()
    db = store or Store(Path(os.environ.get("DCR_DB", config.DATA_DIR / "calls.sqlite")))
    # one streaming recogniser for every English call in the process, decoded in batches off the
    # event loop (src/dcr/serving/stt_service.py); created at startup, after the models load
    stt: dict[str, STTService] = {}
    router = Router(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        import asyncio

        from .speech import engines

        await asyncio.get_running_loop().run_in_executor(
            None, engines.warm, list(cfg["tts"]["voices"].values()), cfg["stt"]["en"], cfg["stt"].get("de", "stt_whisper_base")
        )
        sv = cfg["serving"]
        stt["en"] = STTService(cfg["stt"]["en"], max_batch=int(sv["max_batch"]), max_wait_ms=float(sv["max_wait_ms"]))
        try:
            yield
        finally:
            await router.aclose()
            for svc in stt.values():
                svc.close()

    app = FastAPI(title="duplex-call-runtime", version="0.1.0", lifespan=lifespan)
    reports = Path(os.environ.get("DCR_REPORTS", config.ROOT / "reports"))
    reg = CollectorRegistry()
    m_response = Histogram(
        "dcr_response_seconds",
        "Caller stops speaking to agent audio starts",
        registry=reg,
        buckets=(0.3, 0.5, 0.7, 0.9, 1.1, 1.4, 1.8, 2.5, 4),
    )
    m_endpoint = Histogram(
        "dcr_endpoint_seconds",
        "Caller stops speaking to end-of-turn decision",
        registry=reg,
        buckets=(0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 1.6, 2.6),
    )
    m_events = Counter("dcr_events_total", "Turn-taking and provider events", ["kind"], registry=reg)
    m_calls = Counter("dcr_calls_total", "Calls", ["lang"], registry=reg)
    live: dict[str, CallSession] = {}

    async def finished(s: CallSession) -> None:
        live.pop(s.id, None)
        summary = summarise(s.log.events)
        for t in summary["turns"]:
            m_endpoint.observe(t["endpoint_ms"] / 1000)
            if "response_ms" in t:
                m_response.observe(t["response_ms"] / 1000)
        for k, v in summary["counts"].items():
            if v:
                m_events.labels(k).inc(v)
        m_events.labels("hedged").inc(summary["hedged"])
        db.save(
            {
                "id": s.id,
                "started_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "lang": s.lang,
                "scenario": getattr(s, "scenario", None),
                "options": s.opt.__dict__,
                "events": s.log.events,
                "summary": summary,
                "outcome": json.loads(s.tools.dump()),
            }
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "live_calls": len(live)}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)

    @app.post("/twilio/voice")
    async def twiml(request: Request, lang: str = "en") -> Response:
        """The webhook a Twilio number calls: connect the call's audio to /media.

        With TWILIO_AUTH_TOKEN set, the request must carry a valid X-Twilio-Signature (anyone
        else could otherwise start calls on the runtime). DCR_PUBLIC_URL is the URL Twilio was
        given; without it the Host header is used (local runs only)."""
        public = os.environ.get("DCR_PUBLIC_URL", "").rstrip("/")
        token = os.environ.get("TWILIO_AUTH_TOKEN")
        body = (await request.body()).decode()
        if token:
            url = (public + request.url.path + (f"?{request.url.query}" if request.url.query else "")) if public else str(request.url)
            if not twilio_signature_ok(token, url, dict(parse_qsl(body)), request.headers.get("x-twilio-signature", "")):
                raise HTTPException(403, "bad Twilio signature")
        host = public.split("://", 1)[-1] if public else request.headers.get("host", "localhost")
        if lang not in ("en", "de"):
            lang = "en"
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
            f'<Stream url="wss://{escape(host)}/media"><Parameter name="lang" value="{lang}"/></Stream>'
            "</Connect></Response>"
        )
        return Response(xml, media_type="application/xml")

    @app.websocket("/media")
    async def media(ws: WebSocket) -> None:
        await ws.accept()
        tx = WsTransport(ws)
        session: CallSession | None = None
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                ev = msg.get("event")
                if ev == "start":
                    start = msg["start"]
                    tx.stream_sid = start.get("streamSid") or msg.get("streamSid", "")
                    p = start.get("customParameters") or {}
                    opts = Options(**json.loads(p["options"])) if p.get("options") else Options()
                    today = dt.date.fromisoformat(p["today"]) if p.get("today") else None
                    session = CallSession(
                        p.get("call_id") or start.get("callSid") or uuid.uuid4().hex[:12],
                        tx,
                        cfg,
                        router,
                        lang=p.get("lang", "en"),
                        today=today,
                        options=opts,
                        on_end=finished,
                        stt_service=stt.get("en"),
                        taken=json.loads(p["taken"]) if p.get("taken") else None,
                    )
                    session.scenario = p.get("scenario")  # type: ignore[attr-defined]
                    live[session.id] = session
                    m_calls.labels(session.lang).inc()
                    await session.start()
                elif ev == "media" and session is not None:
                    await session.on_media(base64.b64decode(msg["media"]["payload"]))
                elif ev == "mark" and session is not None:
                    await session.on_mark(msg["mark"]["name"])
                elif ev == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            if session is not None:
                await session.close()

    # ---------------------------------------------------------------- call inspector API

    @app.get("/api/calls")
    async def calls(limit: int = Query(100, ge=1, le=500), scenario: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "started_at": c["started_at"],
                "lang": c["lang"],
                "scenario": c["scenario"],
                "options": c["options"],
                "turns": len(c["summary"]["turns"]),
                "response_ms": c["summary"]["response_ms"],
                "counts": c["summary"]["counts"],
                "outcome": c["outcome"],
            }
            for c in db.list(limit, scenario)
        ]

    @app.get("/api/calls/{call_id}")
    async def call(call_id: str) -> dict[str, Any]:
        c = db.get(call_id)
        if c is None:
            raise HTTPException(404, "no such call")
        return c

    @app.get("/api/evals")
    def evals() -> list[dict[str, Any]]:  # sync: FastAPI runs it in a thread (file reads)
        """Every evaluation report (`reports/eval_*.json`), summaries only: one document per
        call set, configurations x metrics. Held-out first runs are marked."""
        out = []
        for p in [*sorted(reports.glob("eval_*.json")), *sorted(reports.glob("heldout/*/first_run.json"))]:
            try:
                d = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            out.append(
                {
                    "set": d.get("set", p.stem.removeprefix("eval_")),
                    "scenarios": d.get("scenarios", []),
                    "summary": d.get("summary", {}),
                    "first_run": bool(d.get("first_run", False)),
                }
            )
        return out

    @app.get("/api/serving")
    async def serving() -> dict[str, Any]:
        """The shared recogniser's batching: how many streams each decode carried."""
        svc = stt.get("en")
        if svc is None:
            return {"ready": False}
        st = svc.stats
        return {
            "ready": True,
            "streams": len(svc.streams),
            "decode_calls": st.decode_calls,
            "mean_batch": round(st.streams_decoded / st.decode_calls, 2) if st.decode_calls else None,
            "batch_sizes": st.batch_sizes,
            "busy_s": round(st.busy_s, 2),
        }

    @app.get("/api/live")
    async def live_calls() -> list[dict[str, Any]]:
        return [{"id": s.id, "lang": s.lang, "events": len(s.log.events)} for s in live.values()]

    web = Path(os.environ.get("DCR_WEB_DIR", config.ROOT / "web" / "dist"))
    if web.exists():
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Any:
            if path.startswith(("api/", "media", "twilio/")):
                raise HTTPException(404)
            f = web / path
            return FileResponse(f if path and f.is_file() else web / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> PlainTextResponse:
            return PlainTextResponse("duplex-call-runtime: build the console with `cd web && npm run build`")

    return app


def twilio_signature_ok(token: str, url: str, params: dict[str, str], signature: str) -> bool:
    """Twilio's request signature: HMAC-SHA1 over the URL followed by the POST parameters
    sorted by name, each name directly followed by its value, base64-encoded."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    want = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(want, signature)


def app_from_env() -> FastAPI:  # pragma: no cover - wiring
    return create_app()
