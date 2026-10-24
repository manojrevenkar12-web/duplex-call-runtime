"""Serving benchmark: how many calls one machine carries, and what each costs in latency.

1. **STT throughput by batch size.** N streams of phone audio, decoded with `decode_streams`
   in batches of B. Reported as the real-time factor per stream: CPU seconds per second of
   audio, so 1 / RTF is how many calls one core keeps up with.
2. **STT under real-time load.** N calls feed audio at real-time pace through the shared
   `STTService`. How far behind is the transcript when a turn decision asks for it (`sync`
   lag), and does it hold as N grows?
3. **TTS time to first audio.** One short reply clause, with 1, 2 and 4 synthesised at once.
4. **The end-of-turn model's cost per decision.**

All on this machine's CPU. GPU serving (deploy/) changes the numbers, not the method: the
same script measures there."""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ..audio.codec import Upsampler2, resample, telephone_band, ulaw_decode, ulaw_encode
from ..speech import engines
from ..turn import model as eot
from .stt_service import STTService

SENTENCES = [
    "i'd like to book a haircut for tomorrow afternoon please",
    "my number is zero one seven six three six seven nine five zero two five",
    "can you move my appointment to friday at half past two",
    "no sorry the time is wrong it should be eleven fifteen",
]


def _phone(text: str) -> np.ndarray:
    x, r = engines.synthesize(text, "tts_en_amy")
    x8 = telephone_band(resample(x, r, 8000), 8000)
    x8 = x8 / (np.abs(x8).max() + 1e-9) * 0.6
    return Upsampler2()(ulaw_decode(ulaw_encode(x8)))


def stt_throughput(audio: np.ndarray, model: str) -> list[dict[str, Any]]:
    rec = engines._en_recognizer(model)
    out = []
    chunk = 512
    for n in (1, 2, 4, 8):
        for batch in sorted({1, n}):
            streams = [rec.create_stream() for _ in range(n)]
            cpu0, t0 = time.process_time(), time.perf_counter()
            for i in range(0, len(audio), chunk):
                for s in streams:
                    s.accept_waveform(16000, audio[i : i + chunk])
                while True:
                    ready = [s for s in streams if rec.is_ready(s)]
                    if not ready:
                        break
                    for j in range(0, len(ready), batch):
                        rec.decode_streams(ready[j : j + batch])
            wall = time.perf_counter() - t0
            cpu = time.process_time() - cpu0
            secs = len(audio) / 16000 * n
            out.append(
                {
                    "streams": n,
                    "batch": batch,
                    "wall_rtf_per_stream": round(wall / secs, 4),
                    "cpu_rtf_per_stream": round(cpu / secs, 4),
                    "streams_per_core": round(secs / cpu, 1) if cpu else None,
                }
            )
    return out


async def _realtime(svc: STTService, audio: np.ndarray, n: int, seconds: float) -> dict[str, Any]:
    handles = [svc.open() for _ in range(n)]
    lags: list[float] = []
    frame = 320  # 20 ms at 16 kHz
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    k = 0
    pos = 0
    while loop.time() - t0 < seconds:
        k += 1
        await asyncio.sleep(max(0.0, t0 + k * 0.02 - loop.time()))
        x = audio[pos : pos + frame]
        if len(x) < frame:
            pos = 0
            x = audio[:frame]
        pos += frame
        for h in handles:
            h.feed(x)
        if k % 25 == 0:  # twice a second, ask as a turn decision would
            ts = time.perf_counter()
            await asyncio.gather(*(h.sync() for h in handles))
            lags.append((time.perf_counter() - ts) * 1000)
    for h in handles:
        h.close()
    return {
        "calls": n,
        "sync_lag_ms_p50": round(float(np.percentile(lags, 50)), 1),
        "sync_lag_ms_p95": round(float(np.percentile(lags, 95)), 1),
    }


def tts_first_audio(voice: str = "tts_en_lessac") -> list[dict[str, Any]]:
    text = "Which day would you like?"
    engines.synthesize(text, voice)
    out = []
    for n in (1, 2, 4):
        with ThreadPoolExecutor(max_workers=n) as ex:
            t0 = time.perf_counter()
            futs = [ex.submit(engines.synthesize, text, voice) for _ in range(n)]
            done = [(f.result(), time.perf_counter() - t0) for f in futs]
        ms = [d * 1000 for _, d in done]
        out.append({"concurrent": n, "first_audio_ms_p50": round(float(np.median(ms)), 1), "slowest_ms": round(max(ms), 1)})
    return out


def run(seconds: float = 20.0) -> dict[str, Any]:
    model = os.environ.get("DCR_BENCH_STT", "stt_en_nemo")
    audio = np.concatenate([_phone(s) for s in SENTENCES] + [np.zeros(8000, dtype=np.float32)])
    result: dict[str, Any] = {"cpu": os.cpu_count(), "stt_model": model, "audio_seconds": round(len(audio) / 16000, 2)}
    result["stt_throughput"] = stt_throughput(audio, model)
    rt = []
    for batch in (1, 8):
        svc = STTService(model, max_batch=batch)
        for n in (1, 2, 4):
            r = asyncio.run(_realtime(svc, audio, n, seconds))
            r["max_batch"] = batch
            rt.append(r)
        svc.close()
    result["stt_realtime"] = rt
    result["tts_first_audio"] = tts_first_audio()
    m = eot.load()
    t0 = time.perf_counter()
    for _ in range(2000):
        m.probability("my number is zero one seven six three", "phone")
    result["end_of_turn_us"] = round((time.perf_counter() - t0) / 2000 * 1e6, 1)
    return result
