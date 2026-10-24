"""G.711 mu-law, the codec of the public phone network and of Twilio Media Streams, and the
resampling between 8 kHz telephony and the 16 kHz the speech models expect.

Python 3.13 removed `audioop`, so the codec is written out from the ITU-T G.711 definition
(bias 0x84, clip 32635, segment and mantissa bits inverted on the wire)."""

from __future__ import annotations

from functools import cache

import numpy as np
from scipy.signal import resample_poly

BIAS = 0x84
CLIP = 32635


def _encode_one(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    sample = min(sample, CLIP) + BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _decode_one(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = (((mantissa << 3) + BIAS) << exponent) - BIAS
    return -sample if sign else sample


@cache
def _tables() -> tuple[np.ndarray, np.ndarray]:
    enc = np.array([_encode_one(s) for s in range(-32768, 32768)], dtype=np.uint8)
    dec = np.array([_decode_one(b) for b in range(256)], dtype=np.int16)
    return enc, dec


def ulaw_encode(x: np.ndarray) -> bytes:
    """float32 in [-1, 1] -> mu-law bytes."""
    enc, _ = _tables()
    pcm = np.clip(np.round(np.asarray(x, dtype=np.float64) * 32767.0), -32768, 32767).astype(np.int32)
    return enc[pcm + 32768].tobytes()


def ulaw_decode(b: bytes) -> np.ndarray:
    """mu-law bytes -> float32 in [-1, 1]."""
    _, dec = _tables()
    return dec[np.frombuffer(b, dtype=np.uint8)].astype(np.float32) / 32768.0


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(x):
        return np.asarray(x, dtype=np.float32)
    g = np.gcd(src, dst)
    return resample_poly(np.asarray(x, dtype=np.float64), dst // g, src // g).astype(np.float32)


def telephone_band(x: np.ndarray, rate: int) -> np.ndarray:
    """300-3400 Hz, the band a phone line carries (used to make test audio sound like a call)."""
    from scipy.signal import butter, sosfilt

    sos = butter(4, [300, min(3400, rate / 2 - 1)], btype="band", fs=rate, output="sos")
    return sosfilt(sos, x).astype(np.float32)


class Upsampler2:
    """8 kHz -> 16 kHz for a stream of 20 ms frames, with filter state carried across frames
    (resampling each frame on its own would click at every frame edge)."""

    def __init__(self, taps: int = 31) -> None:
        from scipy.signal import firwin

        self.h = (firwin(taps, 0.5) * 2).astype(np.float64)
        self.zi = np.zeros(taps - 1)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        from scipy.signal import lfilter

        up = np.zeros(len(x) * 2)
        up[::2] = x
        y, self.zi = lfilter(self.h, 1.0, up, zi=self.zi)
        return y.astype(np.float32)


def frames_of(ulaw: bytes, frame_bytes: int) -> list[bytes]:
    """Split mu-law audio into whole frames, padding the last with mu-law silence (0xFF)."""
    pad = (-len(ulaw)) % frame_bytes
    b = ulaw + b"\xff" * pad
    return [b[i : i + frame_bytes] for i in range(0, len(b), frame_bytes)]
