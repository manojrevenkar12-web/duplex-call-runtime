"""Echo cancellation for the phone line.

A phone line sends part of the agent's own voice back: hybrid and handset echo, typically 20-40
dB down and tens of milliseconds late. Without cancellation that echo looks like the caller
talking. The agent interrupts itself, and worse, the recogniser transcribes its own words into
the caller's turn.

This is a partitioned-block frequency-domain adaptive filter, the family of algorithms in
Speex's MDF and WebRTC's AEC. The echo path, up to `taps` samples long, is split into
partitions of one 20 ms block each. Every block costs a handful of FFTs instead of a
per-sample loop. The step is normalised per frequency bin, so it converges on speech, whose
spectrum is anything but flat, where a time-domain NLMS crawls (docs/MEASUREMENTS.md has both).

After the filter, residual echo is suppressed (12 dB by default) whenever only the agent is
talking, the "non-linear processor" stage of telephone echo cancellers.

Adaptation freezes while the caller is talking over the agent: a Geigel detector compares the
inbound level with the recent reference. Otherwise the filter would learn the caller's voice as
echo and cancel it.

The same comparison, with a lower threshold and a hangover, tells the session whether inbound
sound can be the caller at all (`near_end`). Before the filter has converged, in the first
second of a call, loud echo passes the filter almost untouched; gating barge-in on `near_end`
keeps it from pausing the agent."""

from __future__ import annotations

import numpy as np


class EchoCanceller:
    def __init__(
        self,
        taps: int,
        step: float,
        block: int = 160,
        geigel: float = 0.5,
        power_smooth: float = 0.9,
        suppress_db: float = 12.0,
        near_end_ratio: float = 0.35,
        near_end_hold_blocks: int = 12,
    ) -> None:
        self.B = block
        self.N = 2 * block
        self.P = max(1, int(np.ceil(taps / block)))
        self.K = self.N // 2 + 1
        self.mu = step
        self.geigel = geigel
        self.beta = power_smooth
        self.W = np.zeros((self.P, self.K), dtype=np.complex128)
        self.X = np.zeros((self.P, self.K), dtype=np.complex128)  # spectra of the last P input blocks
        self.prev = np.zeros(block)
        self.power = np.full(self.K, 1e-6)
        self.recent_ref_peak = np.zeros(self.P)  # per block, for the double-talk check
        self.last_in_db = -120.0
        self.last_out_db = -120.0
        self.frozen = False
        self.seeded = False
        self.reg = 0.1
        self.erle_smooth = 0.0
        self.suppress = 10 ** (-suppress_db / 20)
        self.near_ratio = near_end_ratio
        self.near_hold_blocks = near_end_hold_blocks
        self.near_hold = 0

    def process(self, mic: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """`mic`: one inbound block; `ref`: the agent audio played in the same block (zeros when
        silent). Returns the inbound block with the predicted echo removed."""
        mic = np.asarray(mic, dtype=np.float64)
        ref = np.asarray(ref, dtype=np.float64)
        if len(mic) != self.B or len(ref) != self.B:
            raise ValueError(f"blocks must be {self.B} samples")
        xf = np.fft.rfft(np.concatenate([self.prev, ref]))
        self.prev = ref
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = xf
        self.recent_ref_peak = np.roll(self.recent_ref_peak, 1)
        self.recent_ref_peak[0] = float(np.max(np.abs(ref))) if len(ref) else 0.0
        y = np.fft.irfft(np.sum(self.W * self.X, axis=0), self.N)[self.B :]
        e = mic - y
        ref_peak = float(np.max(self.recent_ref_peak))
        mic_pow, y_pow, e_pow = float(np.mean(mic**2)), float(np.mean(y**2)), float(np.mean(e**2))
        # double talk: inbound far louder than anything played recently (Geigel), or, once the
        # filter has learned the path, far louder than the echo it predicts. Adapting then would
        # cancel the caller instead of the echo.
        geigel = float(np.max(np.abs(mic))) > self.geigel * ref_peak
        converged = self.erle_smooth > 6.0
        self.frozen = ref_peak <= 1e-4 or geigel or (converged and mic_pow > 4.0 * y_pow + 1e-9)
        # is the caller talking? Nothing playing, inbound louder than echo can be, or far above
        # the predicted echo once the path is learned. Held for a few blocks.
        loud = float(np.max(np.abs(mic))) > self.near_ratio * ref_peak
        if ref_peak <= 1e-4 or loud or (converged and mic_pow > 8.0 * y_pow + 1e-9):
            self.near_hold = self.near_hold_blocks
        elif self.near_hold > 0:
            self.near_hold -= 1
        px = np.abs(xf) ** 2
        if not self.seeded and ref_peak > 1e-4:
            self.power = px.copy()  # start from what is actually playing, not from zero
            self.seeded = True
        self.power = self.beta * self.power + (1 - self.beta) * px
        if not self.frozen:
            ef = np.fft.rfft(np.concatenate([np.zeros(self.B), e]))
            # regularised per-bin step: quiet bins do not get huge steps
            reg = self.reg * float(np.mean(self.power)) + 1e-8
            g = (self.mu / (self.power * self.P + reg * self.P)) * ef
            grad = np.conj(self.X) * g
            # gradient constraint: keep each partition's impulse response one block long
            gt = np.fft.irfft(grad, self.N, axis=1)
            gt[:, self.B :] = 0.0
            self.W += np.fft.rfft(gt, axis=1)
            if mic_pow > 1e-9:
                self.erle_smooth = 0.95 * self.erle_smooth + 0.05 * 10 * np.log10(mic_pow / (e_pow + 1e-12))
        self.last_in_db = _db(mic)
        self.last_out_db = _db(e)
        if ref_peak > 1e-4 and not self.frozen and e_pow < 2.0 * y_pow + 1e-9:
            # residual echo suppression: only the agent is talking and what is left is about as
            # loud as the echo the filter predicts, so it is echo; turn it down so it does not
            # look like a caller. A caller's voice is far louder than the prediction and passes.
            e = e * self.suppress
        return e.astype(np.float32)

    @property
    def near_end(self) -> bool:
        """Whether the inbound audio may hold the caller's voice (not only echo)."""
        return self.near_hold > 0

    @property
    def erle_db(self) -> float:
        """Echo return loss enhancement of the last block: how many dB were removed."""
        return self.last_in_db - self.last_out_db


def _db(x: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(np.square(x)) + 1e-12))
