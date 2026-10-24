"""One phone call: listen, decide when the caller has finished, think, speak, and yield.

Everything runs on one asyncio loop per call; model inference runs in a thread pool.

Inbound, every 20 ms: mu-law -> echo cancellation against what the agent was playing -> 16 kHz
-> VAD and streaming STT -> the turn engine. Outbound, every 20 ms: the pacer sends the next
frame of agent speech in real time (so `clear` on barge-in drops at most a frame or two), feeds
the echo canceller its reference, and marks the end of each chunk.

A response streams end to end: the LLM's tokens are cut at the first clause long enough to
say, that clause is synthesised while the LLM keeps writing, and audio starts before the
sentence is finished. When the caller is likely done but not certainly, the response starts
speculatively and its audio is held; if they go on talking it is thrown away, if they stop it
is played at once. Read-only tools may run speculatively; booking never does.

Every step is logged with its time, so a call can be replayed as a timeline and every turn's
latency split into its parts (docs/ARCHITECTURE.md)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from ..audio.aec import EchoCanceller
from ..audio.codec import Upsampler2, frames_of, resample, ulaw_decode, ulaw_encode
from ..llm.router import Done, LLMUnavailable, Router, StreamBroken, Text, ToolCall
from ..serving.stt_service import Handle, STTService
from ..speech import engines
from ..text.numbers import words
from ..turn import policy
from ..turn.context import asked
from .tools import TOOL_SCHEMAS, ToolBox

FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law
SIDE_EFFECTS = {"book_appointment", "transfer_to_human"}

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dcr-models")


class Transport(Protocol):
    async def send_media(self, ulaw: bytes) -> None: ...
    async def send_mark(self, name: str) -> None: ...
    async def send_clear(self) -> None: ...


@dataclass
class Options:
    """What a session does; the evaluation switches these to measure each piece's worth."""

    turn_mode: str = "model"  # model | silence
    speculate: bool = True
    aec: bool = True
    barge_in: bool = True


@dataclass
class Chunk:
    turn: int
    idx: int
    text: str
    frames: list[bytes]
    played: int = 0


@dataclass
class Reply:
    turn: int
    user_text: str
    speculative: bool
    task: asyncio.Task[None] | None = None
    committed: asyncio.Event = field(default_factory=asyncio.Event)
    text: str = ""  # everything the agent has generated for this turn
    chunks: list[Chunk] = field(default_factory=list)
    held: list[Chunk] = field(default_factory=list)  # synthesised while speculative
    tool_msgs: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    cancelled: bool = False
    t_commit: float | None = None
    first_audio_logged: bool = False


class CallLog:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.events: list[dict[str, Any]] = []

    def now(self) -> float:
        return (time.monotonic() - self.t0) * 1000

    def add(self, kind: str, **data: Any) -> dict[str, Any]:
        ev = {"t": round(self.now(), 1), "kind": kind, **data}
        self.events.append(ev)
        return ev


class CallSession:
    def __init__(
        self,
        call_id: str,
        transport: Transport,
        settings: dict[str, Any],
        router: Router,
        lang: str = "en",
        today: dt.date | None = None,
        options: Options | None = None,
        on_end: Callable[[CallSession], Awaitable[None]] | None = None,
        stt_service: STTService | None = None,
        taken: list[str] | None = None,
    ) -> None:
        self.id = call_id
        self.tx = transport
        self.cfg = settings
        self.router = router
        self.lang = lang
        self.today = today or dt.date.today()
        self.opt = options or Options()
        self.on_end = on_end
        self.log = CallLog()
        self.tools = ToolBox(self.today, taken=taken)
        a = settings["audio"]
        self.frame_ms = int(a["frame_ms"])
        self.window_ms = 1000 * int(settings["vad"]["window_samples"]) / int(a["model_rate"])
        ac = settings["aec"]
        self.aec = (
            EchoCanceller(
                int(ac["taps"]),
                float(ac["step"]),
                suppress_db=float(ac["suppress_db"]),
                near_end_ratio=float(ac.get("near_end_ratio", 0.35)),
                near_end_hold_blocks=max(1, round(float(ac.get("near_end_hold_ms", 240)) / settings["audio"]["frame_ms"])),
            )
            if self.opt.aec
            else None
        )
        self.up = Upsampler2()
        self.vad = engines.StreamingVAD(float(settings["vad"]["threshold"]), int(settings["vad"]["window_samples"]))
        flush = float(settings["stt"]["flush_seconds"])
        self.stt: Handle | engines.StreamingSTT | engines.BufferedSTT
        if lang != "en":
            self.stt = engines.BufferedSTT(lang)
        elif stt_service is not None:
            self.stt = stt_service.open()
            self.stt.flush_seconds = flush
        else:
            self.stt = engines.StreamingSTT(settings["stt"]["en"], flush)
        self.voice = settings["tts"]["voices"][lang]
        self.history: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt()}]
        # caller speech tracking (per VAD window)
        self.speech_ms = 0.0  # current run of speech
        self.silence_ms = 0.0  # current run of silence
        self.speaking = False
        self.in_turn = False  # the caller has said something not yet answered
        self.turn_no = 0
        self.speech_start_t: float | None = None
        self.last_speech_end_t: float | None = None
        # agent output
        self.out: deque[Chunk] = deque()
        # what the agent played, as a ring the echo canceller reads in step with inbound audio
        self.ref_ring = np.zeros(4 * int(a["telephony_rate"]), dtype=np.float32)  # four seconds of reference
        self.out_frames = 0  # outbound ticks so far (speech or silence)
        self.in_frames = 0  # inbound frames so far
        self.in_base = -1  # inbound frame count at the pacer's first tick
        self.first_in: float | None = None
        self.lags: list[float] = []  # how late each inbound frame was handled, vs. its place in the stream
        self.committing = False
        self.debug_audio: list[tuple[np.ndarray, np.ndarray]] | None = [] if os.environ.get("DCR_DEBUG_AUDIO") else None
        self.reply: Reply | None = None  # the reply being spoken or prepared
        self.spec: Reply | None = None  # a speculative reply waiting for the turn to end
        self.spec_syncing = False
        self.paused = False  # audio stopped by a possible barge-in (barge_in.hold: pause)
        self.hold_start_t: float | None = None  # when a possible barge-in started a hold
        self.duck_gain = 10 ** (-float(settings["barge_in"].get("duck_db", 14)) / 20)
        self.agent_speaking = False
        self.agent_audio_t: float | None = None
        self.barge_onset_t: float | None = None
        self.backchannel_logged = False
        self.de_job: asyncio.Future[str] | None = None
        self.closed = False
        self.pacer: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Future[Any]] = set()
        self.de_mark: float | None = None
        self.flushed = False  # the recogniser was flushed during the current pause

    # ------------------------------------------------------------------ lifecycle

    def _system_prompt(self) -> str:
        day = self.today.strftime("%A")
        return (
            f"You are Mira, the receptionist of Salon Lindner, on a phone call. Today is {self.today.isoformat()} ({day}). "
            f"Language: {self.lang}. Speak briefly, one question at a time. Use the tools to check and book; "
            "never book without reading the details back and getting a yes."
        )

    async def start(self) -> None:
        self.log.add("call_start", lang=self.lang, options=self.opt.__dict__)
        self.pacer = asyncio.create_task(self._pace())
        greeting = self.cfg["calls"]["greeting"][self.lang]
        self.history.append({"role": "assistant", "content": greeting})
        r = Reply(0, "", speculative=False)
        r.committed.set()
        r.t_commit = self.log.now()
        self.reply = r
        r.task = asyncio.create_task(self._speak_text(r, greeting, final=True))

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for t in (self.pacer, self.reply.task if self.reply else None, self.spec.task if self.spec else None, self.de_job):
            if t:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        lags = np.asarray(self.lags[50:] or [0.0])  # skip the first second (connection set-up)
        lags = lags - lags.min()
        lag = {
            "p50": round(float(np.percentile(lags, 50)), 1),
            "p95": round(float(np.percentile(lags, 95)), 1),
            "max": round(float(lags.max()), 1),
        }
        self.log.add("call_end", tools=json.loads(self.tools.dump()), inbound_lag_ms=lag)
        if isinstance(self.stt, Handle):
            self.stt.close()
        if self.debug_audio:
            np.savez(
                os.environ["DCR_DEBUG_AUDIO"],
                mic=np.concatenate([m for m, _ in self.debug_audio]),
                ref=np.concatenate([r for _, r in self.debug_audio]),
            )
        if self.on_end:
            await self.on_end(self)

    # ------------------------------------------------------------------ inbound

    async def on_media(self, ulaw: bytes) -> None:
        now = time.monotonic()
        if self.first_in is None:
            self.first_in = now
        self.lags.append((now - self.first_in) * 1000 - self.in_frames * self.frame_ms)
        x8 = ulaw_decode(ulaw)
        ref = self._ref_block(len(x8))
        if self.debug_audio is not None:
            self.debug_audio.append((x8.copy(), ref.copy()))
        if self.aec is not None and len(x8) == self.aec.B:
            x8 = self.aec.process(x8, ref)
        x16 = self.up(x8)
        flags = self.vad.feed(x16)
        if self.agent_speaking and self.aec is not None and not self.aec.near_end:
            flags = [False] * len(flags)  # only echo can be on the line: not the caller
        # while the agent talks, only what sounds like the caller reaches the recogniser, so
        # residual echo is never transcribed into their turn
        if not self.agent_speaking or self.speaking or any(flags):
            self.stt.feed(x16)
        for f in flags:
            self._window(f)

    def _ref_block(self, n: int) -> np.ndarray:
        """The agent audio played in step with inbound frame number `in_frames`.

        Both directions run at exactly 50 frames a second, so frames are matched by count, not
        by arrival time: inbound frame j is paired with outbound tick j. Network and scheduling
        jitter then cannot shift the reference under the echo canceller, and the fixed offset
        (playout buffer plus echo delay) is well inside the filter's 160 ms span."""
        # pair with a tick a little earlier: the echo of tick k can only arrive in inbound k + 2 or
        # later (line delay plus playout buffer), and that tick is certainly written by now
        j = self.in_frames - self.in_base - int(self.cfg["aec"]["reference_lag_frames"])
        self.in_frames += 1
        if self.in_base < 0 or j < 0 or j >= self.out_frames or self.out_frames - j > len(self.ref_ring) // n:
            return np.zeros(n, dtype=np.float32)
        start = (j * n) % len(self.ref_ring)
        return self.ref_ring[start : start + n].copy()

    def _ref_write(self, x: np.ndarray) -> None:
        if self.in_base < 0:
            self.in_base = self.in_frames  # both counts start here: inbound j <-> outbound tick j - base
        start = (self.out_frames * len(x)) % len(self.ref_ring)
        self.ref_ring[start : start + len(x)] = x
        self.out_frames += 1

    async def on_mark(self, name: str) -> None:
        self.log.add("mark", name=name)

    def _window(self, speech: bool) -> None:
        now = self.log.now()
        min_speech = float(self.cfg["vad"]["min_speech_ms"])
        if speech:
            self.speech_ms += self.window_ms
            self.silence_ms = 0.0
            if not self.speaking and self.speech_ms >= min_speech:
                self.speaking = True
                self.flushed = False
                self.speech_start_t = now - self.speech_ms
                self.log.add("caller_speech_start", at=round(self.speech_start_t, 1))
                if self.spec is not None and not self.agent_speaking:
                    self._cancel_spec("caller went on")
                r = self.reply
                if r is not None and r.turn > 0 and not self.agent_speaking and not r.first_audio_logged and not r.done:
                    self._take_back(r)
        else:
            self.silence_ms += self.window_ms
            if self.speaking and self.silence_ms >= self.window_ms:
                self.speaking = False
                self.last_speech_end_t = now - self.silence_ms
                self.log.add("caller_speech_end", at=round(self.last_speech_end_t, 1), text=self.stt.text)
                self.in_turn = True
            if not self.speaking:
                self.speech_ms = 0.0
        if self.agent_speaking and self.opt.barge_in:
            self._barge(now)
        elif not self.agent_speaking and self.in_turn and not self.speaking:
            self._turn(now)

    # ------------------------------------------------------------------ barge-in

    def _barge(self, now: float) -> None:
        if self.speaking:
            if self.barge_onset_t is None:
                self.barge_onset_t = self.speech_start_t
            verdict = policy.barge_in(self.speech_ms, self.stt.text if self.lang == "en" else "", self.cfg)
            if verdict == "interrupt":
                self._interrupt(now)
            elif verdict == "hold" and self.hold_start_t is None:
                # maybe an interruption: yield at once, and keep the words ready
                self.hold_start_t = now
                if self.cfg["barge_in"].get("hold", "duck") == "pause":
                    self.paused = True
                    self._bg(self.tx.send_clear())
                self.log.add(
                    "hold",
                    mode="pause" if self.paused else "duck",
                    speech_ms=self.speech_ms,
                    latency_ms=round(now - (self.barge_onset_t or now), 1),
                )
            elif verdict == "ignore" and policy.is_backchannel(self.stt.text) and not self.backchannel_logged:
                self.backchannel_logged = True
                self.log.add("backchannel", text=self.stt.text)
        elif self.hold_start_t is not None:
            # the sound stopped: if it never became words (or only "mhm"), carry on
            bc = policy.is_backchannel(self.stt.text)
            if bc or self.silence_ms >= float(self.cfg["barge_in"]["resume_after_ms"]):
                self.paused = False
                self.hold_start_t = None
                self.barge_onset_t = None
                self.log.add("resume", heard=self.stt.text, backchannel=bc)
                self._reset_stt()
        elif self.barge_onset_t is not None:
            # a backchannel ended without stopping the agent
            self.barge_onset_t = None
            self.backchannel_logged = False
            self.in_turn = False
            self._reset_stt()

    def _bg(self, coro: Any) -> None:
        """Fire-and-forget, but keep a reference so the task is not garbage-collected mid-flight."""
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def _interrupt(self, now: float) -> None:
        r = self.reply
        heard = self._heard_text()
        if not self.paused:
            self._bg(self.tx.send_clear())
        self.out.clear()
        self.paused = False
        self.hold_start_t = None
        self.agent_speaking = False
        latency = now - (self.barge_onset_t or now)
        self.barge_onset_t = None
        if r is not None:
            r.cancelled = True
            if r.task:
                r.task.cancel()
            self._record_assistant(heard + (" —" if heard else ""), interrupted=True, reply=r)
            self.reply = None
        self.log.add("interrupt", heard=heard, latency_ms=round(latency, 1), text=self.stt.text)
        self.in_turn = True

    def _heard_text(self) -> str:
        """The words the caller actually heard: whole chunks played, plus the share of the
        current chunk's words that its played frames cover."""
        r = self.reply
        if r is None:
            return ""
        parts = []
        for c in r.chunks:
            if c.played >= len(c.frames):
                parts.append(c.text)
            elif c.played > 0:
                ws = c.text.split()
                parts.append(" ".join(ws[: int(len(ws) * c.played / max(1, len(c.frames)))]))
                break
            else:
                break
        return " ".join(p for p in parts if p).strip()

    # ------------------------------------------------------------------ end of turn

    def _context(self) -> str:
        last = next((m["content"] for m in reversed(self.history) if m["role"] == "assistant" and m.get("content")), "")
        return asked(last)

    def _turn(self, now: float) -> None:
        if self.last_speech_end_t is None:
            return
        pause = now - self.last_speech_end_t
        if self.committing:
            return
        if (
            isinstance(self.stt, Handle | engines.StreamingSTT)
            and not self.flushed
            and policy.flush_due(pause, self.stt.text, self._context(), self.cfg)
        ):
            self.flushed = True
            self.stt.flush()
        text = self.stt.text
        if self.lang != "en":
            got = self._german_text(pause)
            if got is None:
                return
            text = got
        d = policy.decide(pause, text, self._context(), self.cfg, self.opt.turn_mode)
        if d.action == "speculate" and self.opt.speculate and (self.spec is None or self.spec.user_text != text):
            if isinstance(self.stt, Handle):
                if not self.spec_syncing:
                    self.spec_syncing = True
                    self._bg(self._speculate_synced(d, pause))
            else:
                self._speculate(text, d, pause)
        elif d.action == "respond":
            if isinstance(self.stt, Handle):
                self.committing = True
                self._bg(self._commit_synced(d, pause))
            else:
                self._commit(now, text, d, pause)

    def _speculate(self, text: str, d: policy.Decision, pause: float) -> None:
        if self.spec is not None:
            if self.spec.user_text == text:
                return
            self._cancel_spec("transcript changed")
        self.spec = Reply(self.turn_no + 1, text, speculative=True)
        self.spec.task = asyncio.create_task(self._respond(self.spec))
        self.log.add("speculate", p=round(d.probability, 3), pause_ms=round(pause, 1), text=text)

    async def _speculate_synced(self, d: policy.Decision, pause: float) -> None:
        """Speculate on the transcript of everything said so far, so that the commit a moment
        later finds the same text and can use the reply."""
        assert isinstance(self.stt, Handle)
        try:
            text = await self.stt.sync()
            if self.in_turn and not self.speaking and words(text):
                self._speculate(text, d, pause)
        finally:
            self.spec_syncing = False

    async def _commit_synced(self, d: policy.Decision, pause: float) -> None:
        """Commit with the transcript of everything the caller said, not the one the decoder
        had reached when the decision was made."""
        assert isinstance(self.stt, Handle)
        try:
            text = await self.stt.sync()
            if self.in_turn and not self.speaking:
                self._commit(self.log.now(), text, d, pause)
        finally:
            self.committing = False

    def _german_text(self, pause: float) -> str | None:
        """Whisper runs on the turn's audio so far once the caller pauses; the decision waits for
        it. A result is dropped if the caller spoke again while it ran (the turn has grown).
        Silence fed during the pause does not count: it adds no words."""
        stt = self.stt
        assert isinstance(stt, engines.BufferedSTT)
        mark = self.last_speech_end_t
        if stt.text_for == mark and mark is not None:
            return stt.text
        if self.de_job is None:
            if pause < float(self.cfg["turn"]["evaluate_after_ms"]):
                return None
            audio = stt.samples()
            loop = asyncio.get_running_loop()
            self.de_mark = mark
            self.de_job = asyncio.ensure_future(
                loop.run_in_executor(_pool, engines.transcribe, audio, self.lang, self.cfg["stt"].get("de", "stt_whisper_base"))
            )
            self.log.add("stt_request", seconds=round(len(audio) / 16000, 2))
            return None
        if not self.de_job.done():
            return None
        job, self.de_job = self.de_job, None
        if self.de_mark != mark or job.cancelled() or job.exception() is not None:
            return None
        stt.text, stt.text_for = job.result(), mark
        self.log.add("stt_result", text=stt.text)
        return stt.text

    def _commit(self, now: float, text: str, d: policy.Decision, pause: float) -> None:
        self.turn_no += 1
        self.in_turn = False
        self.log.add(
            "end_of_turn",
            turn=self.turn_no,
            text=text,
            p=round(d.probability, 3),
            reason=d.reason,
            pause_ms=round(pause, 1),
            speech_end=round(self.last_speech_end_t or now, 1),
        )
        self.history.append({"role": "user", "content": text})
        # The recogniser is not reset here but when the reply is first heard: until then the
        # caller may go on, the reply is taken back, and the turn's transcript must be whole
        # (a word split by a pause, "wednes ... day", must not lose its second half).
        if self.spec is not None and self.spec.user_text == text:
            r = self.spec
            self.spec = None
            r.turn = self.turn_no
            r.speculative = False
            self.log.add("speculation_used", turn=self.turn_no, held_chunks=len(r.held))
        else:
            if self.spec is not None:
                self._cancel_spec("transcript changed at commit")
            r = Reply(self.turn_no, text, speculative=False)
            r.task = asyncio.create_task(self._respond(r))
        r.t_commit = now
        self.reply = r
        r.committed.set()
        for c in r.held:
            self._enqueue(r, c)
        r.held.clear()

    def _take_back(self, r: Reply) -> None:
        """We answered too soon: the caller is still talking and has heard nothing from us. Drop
        the reply silently and treat what they said as the start of the same turn."""
        r.cancelled = True
        if r.task:
            r.task.cancel()
        self.out.clear()
        self.reply = None
        taken = ""
        if self.history and self.history[-1]["role"] == "user":
            taken = str(self.history.pop()["content"] or "")
        # the recogniser still holds the whole turn (it is reset on first audio), so the next
        # commit's transcript already includes what was taken back; German re-transcribes it all
        self.turn_no -= 1
        self.log.add("taken_back", turn=r.turn, text=taken)

    def _cancel_spec(self, why: str) -> None:
        s = self.spec
        if s is None:
            return
        s.cancelled = True
        if s.task:
            s.task.cancel()
        self.spec = None
        self.log.add("speculation_cancelled", why=why, text=s.user_text)

    def _reset_stt(self) -> None:
        self.stt.reset()
        if self.de_job is not None:
            self.de_job.cancel()
            self.de_job = None

    # ------------------------------------------------------------------ responding

    async def _respond(self, r: Reply) -> None:
        messages = [*self.history]
        if r.speculative:
            messages.append({"role": "user", "content": r.user_text})
        try:
            for _ in range(4):  # LLM -> tool -> LLM, at most a few rounds
                call = await self._llm_round(r, messages)
                if call is None:
                    break
                if call.name in SIDE_EFFECTS and not r.committed.is_set():
                    await r.committed.wait()  # never book on a guess about the caller being done
                result = await self._run_tool(r, call)
                msgs: list[dict[str, Any]] = [
                    {"role": "assistant", "content": None, "tool_calls": [_tool_msg(call)]},
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)},
                ]
                messages.extend(msgs)
                r.tool_msgs.extend(msgs)
            await r.committed.wait()
            r.done = True
            self._record_assistant(r.text, interrupted=False, reply=r)
        except asyncio.CancelledError:
            raise
        except LLMUnavailable as e:
            self.log.add("llm_unavailable", error=str(e))
            await r.committed.wait()
            await self._speak_text(r, _sorry(self.lang), final=True)

    async def _llm_round(self, r: Reply, messages: list[dict[str, Any]]) -> ToolCall | None:
        t_req = self.log.now()
        self.log.add("llm_request", turn=r.turn, speculative=r.speculative)
        pending = ""
        first_chunk = True
        tool: ToolCall | None = None
        cfg = self.cfg["tts"]
        try:
            async for ev in self.router.stream(messages, TOOL_SCHEMAS):
                if isinstance(ev, Text):
                    if not r.text and not pending:
                        self.log.add("llm_first_token", turn=r.turn, ms=round(self.log.now() - t_req, 1))
                    pending += ev.text
                    r.text += ev.text
                    cut = _clause_cut(pending, int(cfg["first_chunk_min_chars"]) if first_chunk else 40, int(cfg["chunk_max_chars"]))
                    if cut:
                        await self._synth(r, pending[:cut].strip())
                        pending = pending[cut:]
                        first_chunk = False
                elif isinstance(ev, ToolCall):
                    tool = ev
                elif isinstance(ev, Done):
                    self.log.add(
                        "llm_done", turn=r.turn, provider=ev.provider, ttft_ms=round(ev.ttft_ms, 1), hedged=ev.hedged, attempts=ev.attempts
                    )
        except StreamBroken as e:
            self.log.add("llm_stream_broken", provider=e.provider, emitted=e.emitted)
            # what was said stands; finish the turn with a short apology rather than going silent
            pending += " " + _sorry(self.lang)
        if pending.strip():
            await self._synth(r, pending.strip())
        return tool

    async def _run_tool(self, r: Reply, call: ToolCall) -> dict[str, Any]:
        t = self.log.now()
        filler_after = float(self.cfg["tools"]["filler_after_ms"]) / 1000
        loop = asyncio.get_running_loop()
        job = loop.run_in_executor(None, self.tools.call, call.name, call.arguments)
        try:
            result = await asyncio.wait_for(asyncio.shield(job), timeout=filler_after)
        except TimeoutError:
            await self._synth(r, _moment(self.lang))
            result = await job
        self.log.add("tool", turn=r.turn, name=call.name, arguments=call.arguments, result=result, ms=round(self.log.now() - t, 1))
        return dict(result)

    async def _speak_text(self, r: Reply, text: str, final: bool) -> None:
        r.text = text if not r.text else r.text
        await self._synth(r, text)
        if final:
            r.done = True

    async def _synth(self, r: Reply, text: str) -> None:
        if not text or r.cancelled:
            return
        t = self.log.now()
        loop = asyncio.get_running_loop()
        audio, rate = await loop.run_in_executor(_pool, engines.synthesize, text, self.voice, float(self.cfg["tts"]["speed"]))
        if r.cancelled:
            return
        x8 = resample(audio, rate, int(self.cfg["audio"]["telephony_rate"]))
        frames = frames_of(ulaw_encode(np.clip(x8 * 0.9, -1, 1)), FRAME_BYTES)
        chunk = Chunk(r.turn, len(r.chunks) + len(r.held), text, frames)
        self.log.add(
            "tts",
            turn=r.turn,
            chars=len(text),
            ms=round(self.log.now() - t, 1),
            audio_ms=len(frames) * self.frame_ms,
            held=not r.committed.is_set(),
        )
        if r.committed.is_set() and self.reply is r:
            self._enqueue(r, chunk)
        else:
            r.held.append(chunk)

    def _enqueue(self, r: Reply, c: Chunk) -> None:
        r.chunks.append(c)
        self.out.append(c)

    def _record_assistant(self, text: str, interrupted: bool, reply: Reply | None = None) -> None:
        if reply is not None and reply.tool_msgs:
            self.history.extend(reply.tool_msgs)
            reply.tool_msgs = []
        if text:
            self.history.append({"role": "assistant", "content": text})
        self.log.add("assistant", text=text, interrupted=interrupted)

    # ------------------------------------------------------------------ outbound pacer

    async def _pace(self) -> None:
        period = self.frame_ms / 1000
        loop = asyncio.get_running_loop()
        nxt = loop.time()
        silence = np.zeros(int(self.cfg["audio"]["telephony_rate"]) * self.frame_ms // 1000, dtype=np.float32)
        while True:
            nxt += period
            await asyncio.sleep(max(0.0, nxt - loop.time()))
            sent = False
            if not self.paused and self.out:
                c = self.out[0]
                frame = c.frames[c.played]
                c.played += 1
                if self.hold_start_t is not None:  # held, not paused: ducked under the caller
                    frame = ulaw_encode(ulaw_decode(frame) * self.duck_gain)
                await self.tx.send_media(frame)
                self._ref_write(ulaw_decode(frame))
                sent = True
                if not self.agent_speaking:
                    self.agent_speaking = True
                    self.backchannel_logged = False
                    r = self.reply
                    if r is not None and not r.first_audio_logged:
                        r.first_audio_logged = True
                        self._reset_stt()  # the turn is final once the caller hears the answer
                        self.log.add(
                            "agent_audio_start",
                            turn=r.turn,
                            after_commit_ms=round(self.log.now() - (r.t_commit or self.log.now()), 1),
                        )
                if c.played >= len(c.frames):
                    self.out.popleft()
                    await self.tx.send_mark(f"{c.turn}:{c.idx}")
            if not sent:
                self._ref_write(silence)
                if self.agent_speaking and not self.out and not self.paused:
                    r = self.reply
                    if r is None or r.done or r.cancelled:
                        self.agent_speaking = False
                        self.log.add(
                            "agent_audio_end", turn=r.turn if r else None, erle_db=round(self.aec.erle_db, 1) if self.aec else None
                        )
                        if not self.in_turn and not self.speaking:
                            self._reset_stt()  # nothing the caller said during our turn is pending


def _tool_msg(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}


def _clause_cut(text: str, min_chars: int, max_chars: int) -> int:
    """Where to cut streamed text for speech: after the first sentence or clause end past
    `min_chars`, or at a space before `max_chars`. 0 means keep waiting."""
    for i, ch in enumerate(text):
        if i + 1 >= min_chars and ch in ".!?;:," and (i + 1 == len(text) or text[i + 1] == " "):
            return i + 1
    if len(text) > max_chars:
        sp = text.rfind(" ", 0, max_chars)
        return sp if sp > 0 else max_chars
    return 0


def _sorry(lang: str) -> str:
    return "Entschuldigung, einen Moment bitte." if lang == "de" else "Sorry, one moment please."


def _moment(lang: str) -> str:
    return "Einen Moment, ich schaue nach." if lang == "de" else "One moment, let me check."
