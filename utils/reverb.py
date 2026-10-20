"""A Freeverb-style hall reverb in plain Python, wrapped so a piece's tail rings over its own loop
point.

Every filter here feeds back with a delay of at least one block, so each block is computed with list
comprehensions over the previous block instead of a per-sample Python loop. The wet signal runs at
half the sample rate (a reverb tail needs no top octave), which halves the cost.
"""
from __future__ import annotations

import math

from .samples import SAMPLE_RATE

__all__ = ["reverb", "decay_seconds"]

RATE = SAMPLE_RATE // 2  # the wet signal's sample rate
COMB_DELAYS = (558, 594, 638, 678, 711, 745)  # frames at RATE: Freeverb's 44.1 kHz tunings halved
ALLPASS_DELAYS = ((278, 170), (289, 182))  # per channel (left, right): offset for stereo width
ALLPASS_GAIN = 0.5
DAMPING = 0.4  # 0-0.5: share of each comb's feedback taken one frame later (a gentle lowpass)
PREDELAY_SECONDS = 0.02
INPUT_GAIN = 0.015
WET_SCALE = 3.0  # with INPUT_GAIN, amount=1 gives wet at about 0.7x the dry level on these pieces


def _feedback(room: float) -> float:
    return 0.7 + 0.28 * room


def decay_seconds(room: float) -> float:
    """Approximate RT60 (time to fall 60 dB) for a room size."""
    mean_delay = sum(COMB_DELAYS) / len(COMB_DELAYS)
    return -3 * mean_delay / (RATE * math.log10(_feedback(room)))


def _comb(x: list[float], d: int, g: float) -> list[float]:
    """y[n] = x[n] + g * ((1 - DAMPING) * y[n-d] + DAMPING * y[n-d-1])."""
    a_, b_ = g * (1 - DAMPING), g * DAMPING
    y = [0.0] * (d + 1)  # history: y[-d-1 .. -1]
    for a in range(0, len(x), d):
        y.extend([xi + a_ * p + b_ * q for xi, p, q in zip(x[a:a + d], y[a + 1:a + d + 1], y[a:a + d])])
    return y[d + 1:]


def _allpass(x: list[float], d: int) -> list[float]:
    """Freeverb allpass: u[n] = x[n] + g * u[n-d]; y[n] = u[n-d] - x[n]."""
    u = [0.0] * d  # history: u[-d .. -1]
    y: list[float] = []
    for a in range(0, len(x), d):
        block, prev = x[a:a + d], u[a:a + d]
        u.extend([xi + ALLPASS_GAIN * p for xi, p in zip(block, prev)])
        y.extend([p - xi for xi, p in zip(block, prev)])
    return y


def reverb(left: list[float], right: list[float], amount: float, room: float) -> tuple[list[float], list[float]]:
    """Dry plus `amount` of hall reverb, as if the piece had already been looping: the input is
    pre-rolled with the piece's own ending so the tail carries over the loop point."""
    if amount < 0:
        raise ValueError(f"reverb amount must be >= 0, got {amount!r}")
    if not 0 <= room <= 1:
        raise ValueError(f"room must be in [0, 1], got {room!r}")
    n = len(left)
    if amount == 0 or n == 0:
        return left, right
    # mono at half rate: average each pair of frames (an odd last frame pairs with the first)
    k = (n + 1) // 2
    mono = [(left[i] + right[i] + left[(i + 1) % n] + right[(i + 1) % n]) * 0.25 * INPUT_GAIN
            for i in range(0, n, 2)]
    preroll = round(2 * decay_seconds(room) * RATE)
    delay = round(PREDELAY_SECONDS * RATE)
    # times -preroll .. k-1 of the looping piece, pre-delayed: mono[(t - delay) mod k]
    source = [mono[(t - delay) % k] for t in range(-preroll, k)]
    g = _feedback(room)
    combs = [_comb(source, d, g) for d in COMB_DELAYS]
    summed = [sum(frame) for frame in zip(*combs)]
    out = []
    for dry, delays in zip((left, right), ALLPASS_DELAYS):
        wet = summed
        for d in delays:
            wet = _allpass(wet, d)
        wet = wet[-k:]
        # back to full rate by linear interpolation, wrapping at the loop point
        full = [0.0] * (2 * k)
        full[0::2] = wet
        full[1::2] = [(a + b) * 0.5 for a, b in zip(wet, wet[1:] + wet[:1])]
        scale = amount * WET_SCALE
        out.append([a + scale * w for a, w in zip(dry, full)])
    return out[0], out[1]
