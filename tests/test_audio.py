"""Telephony audio: the G.711 codec, resampling, and the echo canceller."""

import numpy as np
import pytest
from scipy.signal import lfilter

from dcr.audio.aec import EchoCanceller
from dcr.audio.codec import Upsampler2, frames_of, resample, ulaw_decode, ulaw_encode


def test_ulaw_matches_the_g711_reference_points():
    # ITU-T G.711: silence encodes to 0xFF, full positive scale to 0x80, full negative to 0x00
    assert ulaw_encode(np.array([0.0])) == b"\xff"
    assert ulaw_encode(np.array([1.0])) == b"\x80"
    assert ulaw_encode(np.array([-1.0])) == b"\x00"
    assert ulaw_decode(b"\xff")[0] == 0.0


def test_ulaw_round_trip_keeps_speech_level_signals_within_g711_quantisation():
    x = np.sin(np.linspace(0, 200 * np.pi, 8000)) * 0.5
    y = ulaw_decode(ulaw_encode(x))
    snr = 10 * np.log10(np.mean(x**2) / np.mean((x - y) ** 2))
    assert snr > 33  # G.711 gives about 38 dB SQNR for loud signals


def test_frames_are_whole_and_padded_with_ulaw_silence():
    fr = frames_of(b"\x01" * 330, 160)
    assert [len(f) for f in fr] == [160, 160, 160] and fr[-1].endswith(b"\xff" * 150)


def test_streaming_upsampler_matches_one_shot_resampling_without_frame_edge_clicks():
    t = np.arange(8000) / 8000
    x = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    up = Upsampler2()
    streamed = np.concatenate([up(x[i : i + 160]) for i in range(0, len(x), 160)])
    ref = resample(x, 8000, 16000)
    # the streamed filter has a fixed group delay; align and compare away from the start
    lag = int(np.argmax(np.correlate(streamed[1000:3000], ref[1000:1200], "valid")))
    err = streamed[1000 + lag : 15000 + lag] - ref[1000:15000]
    assert np.sqrt(np.mean(err**2)) < 0.02


def _speechlike(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w = lfilter([1], [1, -0.9], rng.standard_normal(n))  # coloured, like speech
    env = np.abs(np.sin(np.linspace(0, 30 * np.pi, n))) + 0.1  # syllable-ish envelope
    return (w * env / np.max(np.abs(w * env)) * 0.8).astype(np.float32)


@pytest.mark.parametrize(("delay_ms", "echo_db"), [(40, -24), (90, -18), (130, -30)])
def test_echo_canceller_removes_most_of_a_coloured_delayed_echo(delay_ms, echo_db):
    ref = _speechlike(8000 * 8, 1)
    d = int(8 * delay_ms)
    path = lfilter([1, 0.5, -0.2], [1, -0.3], np.concatenate([np.zeros(d), ref])[: len(ref)])
    echo = path / np.max(np.abs(path)) * np.max(np.abs(ref)) * 10 ** (echo_db / 20)
    a = EchoCanceller(1280, 0.5, suppress_db=0)
    out = np.concatenate([a.process(echo[i : i + 160], ref[i : i + 160]) for i in range(0, len(ref), 160)])
    half = len(out) // 2
    erle = 10 * np.log10(np.mean(echo[half:] ** 2) / np.mean(out[half:] ** 2))
    assert erle > 15, erle


def test_echo_canceller_lets_the_caller_through_while_they_talk_over_the_agent():
    ref = _speechlike(8000 * 6, 2)
    echo = np.concatenate([np.zeros(320), ref])[: len(ref)] * 0.05
    caller = _speechlike(len(ref), 3) * 0.6
    caller[: len(ref) // 2] = 0  # the caller starts talking half-way through
    a = EchoCanceller(1280, 0.5)
    mic = echo + caller
    out = np.concatenate([a.process(mic[i : i + 160], ref[i : i + 160]) for i in range(0, len(ref), 160)])
    second = slice(len(ref) // 2 + 4000, len(ref))
    kept = 10 * np.log10(np.mean(out[second] ** 2) / np.mean(caller[second] ** 2))
    assert kept > -2  # the caller's voice is not cancelled or suppressed during double talk
    assert a.frozen


def test_near_end_gate_rejects_unconverged_echo_and_accepts_the_caller():
    ref = _speechlike(8000 * 2, 4)
    echo = np.concatenate([np.zeros(720), ref])[: len(ref)] * 10 ** (-18 / 20)  # a bad handset, 90 ms
    a = EchoCanceller(1280, 0.5, near_end_hold_blocks=12)
    flags = []
    for i in range(0, 8000, 160):  # the first second: the filter has not converged yet
        a.process(echo[i : i + 160], ref[i : i + 160])
        flags.append(a.near_end)
    assert sum(flags[15:]) == 0  # once the agent is audible, its echo alone never counts as the caller
    caller = _speechlike(1600, 5) * 0.6
    a.process(echo[8000:8160] + caller[:160], ref[8000:8160])
    assert a.near_end
