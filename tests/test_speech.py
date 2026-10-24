"""The speech path with the real pinned models: recogniser service, Whisper for German, TTS."""

import asyncio

import numpy as np
import pytest
from conftest import needs_models

from dcr.audio.codec import Upsampler2, resample, telephone_band, ulaw_decode, ulaw_encode
from dcr.serving.stt_service import STTService
from dcr.sim.metrics import wer
from dcr.speech import engines

pytestmark = [needs_models, pytest.mark.models]


def phone(text: str, voice: str) -> np.ndarray:
    x, r = engines.synthesize(text, voice)
    x8 = telephone_band(resample(x, r, 8000), 8000)
    x8 = x8 / np.abs(x8).max() * 0.6
    return Upsampler2()(ulaw_decode(ulaw_encode(x8)))


async def test_the_shared_recogniser_decodes_several_calls_in_batches() -> None:
    svc = STTService("stt_en_nemo", max_batch=8)
    try:
        lines = ["i'd like to book a haircut please", "my name is anna berger", "tomorrow at ten o'clock"]
        audio = [phone(t, "tts_en_amy") for t in lines]
        handles = [svc.open() for _ in lines]
        frame = 320
        for i in range(0, max(len(a) for a in audio), frame):
            for h, a in zip(handles, audio, strict=True):
                h.feed(a[i : i + frame] if i < len(a) else np.zeros(frame, dtype=np.float32))
            await asyncio.sleep(0)
        for h in handles:
            h.flush()
        texts = await asyncio.gather(*(h.sync(wait_s=10) for h in handles))
        errs = sum(wer(t, h)[0] for t, h in zip(lines, texts, strict=True))
        assert errs <= 2, texts
        assert max(svc.stats.batch_sizes) > 1  # streams were decoded together
        handles[0].reset()
        assert await handles[0].sync() == ""
    finally:
        svc.close()


async def test_sync_never_hangs_a_turn() -> None:
    svc = STTService("stt_en_nemo")
    try:
        h = svc.open()
        h.feed(np.zeros(16000, dtype=np.float32))
        assert isinstance(await h.sync(wait_s=5), str)
        h.close()
    finally:
        svc.close()


def test_german_whisper_ignores_the_silence_around_a_turn() -> None:
    x = phone("ich hätte gern einen termin zum haare schneiden", "tts_de_thorsten")
    padded = np.concatenate([np.zeros(16000 * 2, dtype=np.float32), x, np.zeros(16000 * 2, dtype=np.float32)])
    assert len(engines.speech_span(padded)) < len(x) + 16000
    text = engines.transcribe(padded, "de").replace(".", "").replace(",", "")
    errs, _ = wer("ich hätte gern einen termin zum haare schneiden", text)
    assert errs <= 2, text


def test_tts_voices_load_and_speak() -> None:
    for voice in ("tts_en_lessac", "tts_de_thorsten", "tts_en_ryan", "tts_en_gb_alan"):
        x, rate = engines.synthesize("Hello there.", voice)
        assert rate > 8000 and len(x) > rate * 0.3
