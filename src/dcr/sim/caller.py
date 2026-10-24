"""A simulated phone caller: the carrier, the line and the person, speaking Twilio's protocol.

**The carrier.** Like Twilio Media Streams, it buffers the agent's audio and plays it out at
real time, 20 ms per frame. It echoes each mark back when playback reaches it, and on `clear`
it drops the buffer (pending marks come back at once).

**The line.** Every 20 ms it sends one mu-law frame. The frame is the caller's voice
(band-limited to 300-3400 Hz), plus background noise at a set SNR, plus echo: the agent's own
audio, delayed and attenuated, as a phone hybrid returns it.

**The person.** They follow a script:
- each line is said once the agent has finished, after a human reaction time;
- some lines pause mid-sentence (while dictating a number, say);
- some interrupt the agent after it has spoken for a while;
- some are backchannels ("mhm") said over the agent.

Everything is measured from the audio, as a recording would show it, not from the server's
own log. Caller speech intervals are known exactly, because the caller produced them. Agent
audio intervals are found by energy in what the carrier played. So the evaluation checks the
runtime instead of trusting it."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import websockets

from ..audio.codec import resample, telephone_band, ulaw_decode, ulaw_encode
from ..speech import engines

RATE = 8000
FRAME = 160  # 20 ms
FRAME_S = FRAME / RATE


@dataclass
class Line:
    say: str
    pauses: list[dict[str, Any]] = field(default_factory=list)  # [{after_word: n, ms: m}]
    kind: str = "say"  # say | interrupt | backchannel
    after_agent_ms: float = 0.0  # interrupt/backchannel: how far into the agent's speech


@dataclass
class Scenario:
    id: str
    lang: str
    today: str
    voice: str
    lines: list[Line]
    echo_db: float = -30.0
    echo_delay_ms: float = 40.0
    noise: str = "none"  # none | pink | babble
    noise_snr_db: float = 35.0
    reaction_ms: float = 350.0
    expect: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    taken: list[str] = field(default_factory=list)  # booked slots, "YYYY-MM-DD HH:MM"; the rest is free
    notes: str = ""

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Scenario:
        lines = []
        for item in d["lines"]:
            if isinstance(item, bool):
                item = "yes" if item else "no"  # YAML reads a bare `- yes` as true
            if isinstance(item, str | int | float):
                lines.append(Line(str(item)))
            else:
                kind = "interrupt" if "interrupt" in item else "backchannel" if "backchannel" in item else "say"
                lines.append(
                    Line(
                        item.get("say") or item.get("interrupt") or item.get("backchannel"),
                        item.get("pauses", []),
                        kind,
                        float(item.get("after_agent_ms", 1200)),
                    )
                )
        line = d.get("line", {})
        return Scenario(
            id=d["id"],
            lang=d.get("lang", "en"),
            today=str(d.get("today", "2026-10-26")),
            voice=d.get("voice", "tts_en_amy" if d.get("lang", "en") == "en" else "tts_de_thorsten"),
            lines=lines,
            echo_db=float(line.get("echo_db", -30)),
            echo_delay_ms=float(line.get("echo_delay_ms", 40)),
            noise=line.get("noise", "none"),
            noise_snr_db=float(line.get("noise_snr_db", 35)),
            reaction_ms=float(d.get("reaction_ms", 350)),
            expect=d.get("expect", {}),
            options=d.get("options", {}),
            taken=[str(x) for x in (d.get("calendar") or {}).get("taken", [])],
            notes=d.get("notes", ""),
        )


@dataclass
class Utterance:
    """A line rendered to 8 kHz phone audio, with where its words and pauses fall."""

    line: Line
    audio: np.ndarray
    pause_spans: list[tuple[int, int]]  # sample ranges of scripted mid-sentence pauses


def render(line: Line, voice: str, speed: float = 1.0) -> Utterance:
    """Synthesise a line, inserting the scripted pauses between words."""
    ws = line.say.split()
    cuts = sorted({int(p["after_word"]) for p in line.pauses if 0 < int(p["after_word"]) < len(ws)})
    ms = {int(p["after_word"]): float(p["ms"]) for p in line.pauses}
    parts, start = [], 0
    for c in [*cuts, len(ws)]:
        parts.append(" ".join(ws[start:c]))
        start = c
    pieces: list[np.ndarray] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, text in enumerate(parts):
        x, rate = engines.synthesize(text, voice, speed)
        x8 = telephone_band(resample(_trim(x, rate), rate, RATE), RATE)
        pieces.append(x8)
        pos += len(x8)
        if i < len(cuts):
            gap = np.zeros(int(RATE * ms[cuts[i]] / 1000), dtype=np.float32)
            spans.append((pos, pos + len(gap)))
            pieces.append(gap)
            pos += len(gap)
    audio = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if len(audio) else 1.0
    return Utterance(line, (audio / max(peak, 1e-6) * 0.6).astype(np.float32), spans)


def _trim(x: np.ndarray, rate: int, thr: float = 0.01) -> np.ndarray:
    """Piper pads its output with silence; a person's words start and stop where the sound does."""
    idx = np.nonzero(np.abs(x) > thr)[0]
    if not len(idx):
        return x
    pad = int(rate * 0.02)
    return x[max(0, idx[0] - pad) : idx[-1] + pad]


def noise_bed(kind: str, seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Background noise for a whole call, generated once so it is continuous across frames."""
    n = int(RATE * seconds)
    if kind == "pink":
        from scipy.signal import lfilter

        w = rng.standard_normal(n + 1024)
        b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
        a = np.array([1, -2.494956002, 2.017265875, -0.522189400])
        x = lfilter(b, a, w)[1024:]
    elif kind == "babble":
        # amplitude-modulated band noise: the texture of a busy room on a phone line
        w = telephone_band(rng.standard_normal(n).astype(np.float32), RATE)
        env = np.abs(np.convolve(rng.standard_normal(n), np.ones(800) / 800, mode="same"))
        x = w * (0.3 + env * 6)
    else:
        return np.zeros(n, dtype=np.float32)
    x = x / (np.sqrt(np.mean(x**2)) + 1e-12)  # unit RMS: the SNR sets the level
    return x.astype(np.float32)


@dataclass
class Timeline:
    """Ground truth from the caller's side, in ms from the call's first frame."""

    caller: list[dict[str, Any]] = field(default_factory=list)  # one per line: start, end, pauses, kind
    agent_frames: list[tuple[float, float]] = field(default_factory=list)  # (t, rms) of each played frame
    clears: list[float] = field(default_factory=list)
    marks: list[tuple[float, str]] = field(default_factory=list)


class Caller:
    def __init__(self, sc: Scenario, url: str, call_id: str, options: dict[str, Any] | None = None, seed: int = 0) -> None:
        self.sc = sc
        self.url = url
        self.call_id = call_id
        self.options = options or sc.options
        self.rng = np.random.default_rng(seed)
        self.tl = Timeline()
        self.playout: list[tuple[bytes, str | None]] = []  # agent frames waiting, with a mark after some
        self.pending_marks: list[str] = []
        self.heard = np.zeros(0, dtype=np.float32)  # every agent sample played, in order
        self.t = 0.0  # ms since start, advanced 20 ms per tick

    async def run(self, max_s: float = 120.0) -> Timeline:
        utts = [render(ln, self.sc.voice) for ln in self.sc.lines]
        async with websockets.connect(self.url, max_size=None) as ws:
            sid = f"MZ{self.call_id}"
            await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
            params = {
                "lang": self.sc.lang,
                "today": self.sc.today,
                "call_id": self.call_id,
                "scenario": self.sc.id,
                "options": json.dumps(self.options),
                "taken": json.dumps(self.sc.taken),
            }
            await ws.send(
                json.dumps(
                    {
                        "event": "start",
                        "sequenceNumber": "1",
                        "start": {
                            "streamSid": sid,
                            "callSid": f"CA{self.call_id}",
                            "tracks": ["inbound"],
                            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                            "customParameters": params,
                        },
                        "streamSid": sid,
                    }
                )
            )
            recv = asyncio.create_task(self._receive(ws))
            try:
                await self._talk(ws, sid, utts, max_s)
            finally:
                recv.cancel()
                await ws.send(json.dumps({"event": "stop", "streamSid": sid, "stop": {"callSid": f"CA{self.call_id}"}}))
        return self.tl

    async def _receive(self, ws: Any) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            ev = msg.get("event")
            if ev == "media":
                self.playout.append((base64.b64decode(msg["media"]["payload"]), None))
            elif ev == "mark":
                if self.playout:
                    f, _ = self.playout[-1]
                    self.playout[-1] = (f, msg["mark"]["name"])
                else:
                    self.pending_marks.append(msg["mark"]["name"])
            elif ev == "clear":
                self.tl.clears.append(self.t)
                for _, mk in self.playout:
                    if mk:
                        self.pending_marks.append(mk)
                self.playout.clear()

    async def _talk(self, ws: Any, sid: str, utts: list[Utterance], max_s: float) -> None:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        sc = self.sc
        echo_gain = 10 ** (sc.echo_db / 20)
        delay = int(RATE * sc.echo_delay_ms / 1000)
        speech_level = 0.6 / 3  # rough RMS of the normalised caller voice
        noise_gain = speech_level / (10 ** (sc.noise_snr_db / 20))
        bed = noise_bed(sc.noise, 30.0, self.rng)
        mouth = np.zeros(0, dtype=np.float32)
        mouth_pos = 0
        current: dict[str, Any] | None = None
        i = 0  # next script line
        agent_ms = 0.0  # how long the agent has been audible in its current turn
        quiet_ms = 0.0  # how long since the agent was last audible
        agent_turn_seen = False
        wait_ms = 0.0
        last_end = 0.0  # when the caller last finished a line
        seq = 2
        n = 0
        while self.t < max_s * 1000:
            n += 1
            await asyncio.sleep(max(0.0, t0 + n * FRAME_S - loop.time()))
            self.t = n * FRAME_S * 1000
            # carrier: play one frame of agent audio
            if self.playout:
                frame, mk = self.playout.pop(0)
                played = ulaw_decode(frame)
                if mk:
                    await ws.send(json.dumps({"event": "mark", "sequenceNumber": str(seq), "streamSid": sid, "mark": {"name": mk}}))
                    self.tl.marks.append((self.t, mk))
            else:
                played = np.zeros(FRAME, dtype=np.float32)
            for mk in self.pending_marks:
                await ws.send(json.dumps({"event": "mark", "streamSid": sid, "mark": {"name": mk}}))
                self.tl.marks.append((self.t, mk))
            self.pending_marks.clear()
            self.heard = np.concatenate([self.heard[-RATE:], played])
            rms = float(np.sqrt(np.mean(played**2)))
            self.tl.agent_frames.append((self.t, rms))
            audible = rms > 0.01
            if audible:
                agent_ms += 20
                quiet_ms = 0.0
                agent_turn_seen = True
            else:
                quiet_ms += 20
            # the person: decide whether to start the next line
            if current is None and i < len(utts):
                u = utts[i]
                kind = u.line.kind
                start = False
                if kind in ("interrupt", "backchannel"):
                    start = audible and agent_ms >= u.line.after_agent_ms
                    if not start and agent_turn_seen and quiet_ms >= 1500:
                        start = True  # the agent finished before the cue: say it anyway, as a normal line
                elif agent_turn_seen and quiet_ms >= 700:
                    wait_ms += 20
                    start = wait_ms >= sc.reaction_ms
                elif not agent_turn_seen and self.t - last_end >= 8000:
                    start = True  # the agent has not answered for 8 s: the caller goes on anyway
                if start:
                    mouth, mouth_pos = u.audio, 0
                    current = {"line": i, "kind": kind, "text": u.line.say, "start": self.t, "pauses": [], "agent_ms_at_start": agent_ms}
                    for a, b in u.pause_spans:
                        current["pauses"].append((self.t + a / RATE * 1000, self.t + b / RATE * 1000))
                    wait_ms = 0.0
                    i += 1
                    if kind != "backchannel":
                        agent_ms = 0.0
                        agent_turn_seen = False
            # the line: caller voice + noise + echo of what was played
            voice = np.zeros(FRAME, dtype=np.float32)
            if current is not None:
                chunk = mouth[mouth_pos : mouth_pos + FRAME]
                voice[: len(chunk)] = chunk
                mouth_pos += FRAME
                if mouth_pos >= len(mouth):
                    current["end"] = self.t - (mouth_pos - len(mouth)) / RATE * 1000
                    last_end = self.t
                    if current["kind"] != "backchannel":
                        # wait for the agent's answer to this line, not the tail of what it was
                        # saying when an interruption began
                        agent_turn_seen = False
                        agent_ms = 0.0
                    self.tl.caller.append(current)
                    current = None
            hist = self.heard[-(FRAME + delay) :]
            echo = hist[:FRAME] if len(hist) >= FRAME + delay else np.zeros(FRAME, dtype=np.float32)
            k = (n * FRAME) % (len(bed) - FRAME)
            mic = voice + echo * echo_gain + bed[k : k + FRAME] * noise_gain
            payload = base64.b64encode(ulaw_encode(np.clip(mic, -1, 1))).decode()
            seq += 1
            await ws.send(
                json.dumps(
                    {
                        "event": "media",
                        "sequenceNumber": str(seq),
                        "streamSid": sid,
                        "media": {"track": "inbound", "chunk": str(n), "timestamp": str(int(self.t)), "payload": payload},
                    }
                )
            )
            # hang up once the script is done and the agent has finished its last reply
            if i >= len(utts) and current is None and agent_turn_seen and quiet_ms >= 2500:
                return
            if i >= len(utts) and current is None and not agent_turn_seen and quiet_ms >= 8000:
                return
