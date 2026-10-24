"""The speech models, on CPU through sherpa-onnx, loaded once per process.

- Silero VAD, streaming, one detector per call.
- English STT: NVIDIA's streaming FastConformer transducer (80 ms chunks, int8), or the much
  cheaper and much less accurate 20M-parameter Zipformer. Partial transcripts arrive as the
  audio does; the turn-taking engine reads them at every pause.
- German STT: Whisper tiny, run on the caller's audio so far when they pause (no streaming
  German model is published as a sherpa-onnx release; see docs/MEASUREMENTS.md for the cost).
- TTS: Piper voices (VITS), English and German.

`threads` comes from DCR_MODEL_THREADS. Models are shared across calls; per-call state lives
in streams, which are cheap."""

from __future__ import annotations

import os
import threading
from functools import cache
from typing import Any

import numpy as np

from .. import assets

THREADS = int(os.environ.get("DCR_MODEL_THREADS", "1"))
# onnxruntime execution provider: "cpu", or "cuda" with the CUDA build of sherpa-onnx (deploy/k8s)
PROVIDER = os.environ.get("DCR_MODEL_PROVIDER", "cpu")


def _so() -> Any:
    import sherpa_onnx

    return sherpa_onnx


class StreamingVAD:
    """Speech or not, per 32 ms window at 16 kHz."""

    def __init__(self, threshold: float, window: int) -> None:
        so = _so()
        cfg = so.VadModelConfig()
        cfg.silero_vad.model = str(assets.model_dir("silero_vad"))
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = 0.05
        cfg.silero_vad.min_speech_duration = 0.05
        cfg.silero_vad.window_size = window
        cfg.sample_rate = 16000
        cfg.num_threads = 1
        self.window = window
        self.det = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        self.buf = np.zeros(0, dtype=np.float32)

    def feed(self, x16: np.ndarray) -> list[bool]:
        """One flag per complete window in the audio fed so far."""
        self.buf = np.concatenate([self.buf, x16.astype(np.float32)])
        out = []
        while len(self.buf) >= self.window:
            w, self.buf = self.buf[: self.window], self.buf[self.window :]
            self.det.accept_waveform(w)
            out.append(bool(self.det.is_speech_detected()))
            while not self.det.empty():  # segments are not needed; keep the buffer small
                self.det.pop()
        return out


STT_MODELS = {
    "stt_en_nemo": ("nemo_transducer", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"),
    "stt_en_streaming": ("", "encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.int8.onnx", "joiner-epoch-99-avg-1.int8.onnx"),
}


@cache
def _en_recognizer(name: str = "stt_en_nemo") -> Any:
    model_type, enc, dec, join = STT_MODELS[name]
    d = assets.model_dir(name)
    kw: dict[str, Any] = {"model_type": model_type} if model_type else {}
    return _so().OnlineRecognizer.from_transducer(
        tokens=str(d / "tokens.txt"),
        encoder=str(d / enc),
        decoder=str(d / dec),
        joiner=str(d / join),
        num_threads=THREADS,
        provider=PROVIDER,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        **kw,
    )


class StreamingSTT:
    """English: decode as audio arrives; `text` is the transcript of the current caller turn."""

    lang = "en"

    def __init__(self, model: str = "stt_en_nemo", flush_seconds: float = 0.4) -> None:
        self.rec = _en_recognizer(model)
        self.flush_seconds = flush_seconds
        self.stream = self.rec.create_stream()
        self.text = ""

    def feed(self, x16: np.ndarray) -> str:
        self.stream.accept_waveform(16000, x16)
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        self.text = str(self.rec.get_result(self.stream)).strip().lower()
        return self.text

    def flush(self, seconds: float | None = None) -> str:
        """The streaming model emits a word a few hundred ms after hearing it. When the caller
        pauses, push silence through so the transcript includes their last word. (Silence in
        the stream is harmless if they go on.)"""
        return self.feed(np.zeros(int(16000 * (seconds or self.flush_seconds)), dtype=np.float32))

    def reset(self) -> None:
        self.rec.reset(self.stream)
        self.text = ""


def warm(voices: list[str], stt: str = "stt_en_nemo", stt_de: str = "stt_whisper_base") -> None:
    """Load every model once, so the first call does not pay for it."""
    _en_recognizer(stt)
    _whisper("de", stt_de)
    for v in voices:
        synthesize("Hallo.", v)


@cache
def _whisper(language: str, model: str = "stt_whisper_base") -> Any:
    d = assets.model_dir(model)
    size = model.removeprefix("stt_whisper_")
    return _so().OfflineRecognizer.from_whisper(
        encoder=str(d / f"{size}-encoder.int8.onnx"),
        decoder=str(d / f"{size}-decoder.int8.onnx"),
        tokens=str(d / f"{size}-tokens.txt"),
        language=language,
        task="transcribe",
        num_threads=THREADS,
        provider=PROVIDER,
    )


_whisper_lock = threading.Lock()


def speech_span(x16: np.ndarray, rel: float = 0.02, floor: float = 0.004) -> np.ndarray:
    """The part of a buffer that holds speech, with 200 ms before and 300 ms after. Whisper
    hallucinates on long silence ("mein name ist ... mein name ist ..."), and the turn's
    buffer starts when the agent stopped talking and runs through the pause."""
    f = 320
    n = len(x16) // f
    if n == 0:
        return x16
    r = np.sqrt(np.mean(x16[: n * f].reshape(n, f) ** 2, axis=1))
    idx = np.nonzero(r > max(rel * float(r.max()), floor))[0]
    if not len(idx):
        return x16
    return x16[max(0, (int(idx[0]) - 10) * f) : min(len(x16), (int(idx[-1]) + 15) * f)]


def transcribe(x16: np.ndarray, language: str, model: str = "stt_whisper_base") -> str:
    """Whole-utterance transcript (German path). Thread-safe; call it from an executor."""
    rec = _whisper(language, model)
    with _whisper_lock:
        s = rec.create_stream()
        s.accept_waveform(16000, speech_span(np.asarray(x16, dtype=np.float32)))
        rec.decode_stream(s)
        return str(s.result.text).strip().lower()


class BufferedSTT:
    """German: keep the turn's audio; transcribe it when the turn-taking engine asks."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.audio: list[np.ndarray] = []
        self.text = ""
        self.text_for: float | None = None  # the caller speech end the current text covers

    def feed(self, x16: np.ndarray) -> str:
        self.audio.append(x16)
        return self.text

    def samples(self) -> np.ndarray:
        return np.concatenate(self.audio) if self.audio else np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        self.audio = []
        self.text = ""
        self.text_for = None


VOICE_FILES = {
    "tts_en_lessac": "en_US-lessac-medium.onnx",
    "tts_en_amy": "en_US-amy-low.onnx",
    "tts_de_thorsten": "de_DE-thorsten-medium.onnx",
    "tts_en_ryan": "en_US-ryan-medium.onnx",
    "tts_en_gb_alan": "en_GB-alan-medium.onnx",
}
_tts_locks: dict[str, threading.Lock] = {v: threading.Lock() for v in VOICE_FILES}


@cache
def _tts(voice: str) -> Any:
    so = _so()
    d = assets.model_dir(voice)
    return so.OfflineTts(
        so.OfflineTtsConfig(
            model=so.OfflineTtsModelConfig(
                vits=so.OfflineTtsVitsModelConfig(
                    model=str(d / VOICE_FILES[voice]), tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data")
                ),
                num_threads=THREADS,
                provider=PROVIDER,
            )
        )
    )


def synthesize(text: str, voice: str, speed: float = 1.0) -> tuple[np.ndarray, int]:
    """Thread-safe per voice; call it from an executor."""
    with _tts_locks[voice]:
        a = _tts(voice).generate(text, sid=0, speed=speed)
    return np.asarray(a.samples, dtype=np.float32), int(a.sample_rate)
