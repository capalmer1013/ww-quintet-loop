"""Mastering for small speakers, in plain Python: EQ, gentle compression, loudness normalisation and
a peak limiter. Everything wraps at the loop point, so a mastered piece still loops seamlessly.

- EQ: each filter is two cascaded moving averages (from running sums), subtracted or added back to
  shape a band.
  It is linear, so it is applied to each recording once (see render.leveled) rather than to the
  whole mix: same result, a fraction of the work.
- Dynamics: compression, makeup to TARGET_LUFS and the limiter become one gain per BLOCK, ramped
  linearly across each block, so the whole chain costs a single pass over the mix.
"""
from __future__ import annotations

import math
from itertools import accumulate
from operator import mul, sub

from .samples import SAMPLE_RATE

__all__ = ["master", "eq", "loudness_lufs"]

# measured response: about -11 dB at 60 Hz and -4.5 at 100, -3 dB around 250-330 Hz, +3.5 to +4 dB
# at 3-4.5 kHz, back to flat by 12 kHz
HIGHPASS_HZ = 60  # rumble phones can't play and that only eats headroom
MUD_BAND, MUD_DB = (150, 400), -5.0  # low-mid build-up that sounds boxy on small speakers
PRESENCE_BAND, PRESENCE_DB = (1800, 5000), 5.0  # where phone speakers (and ears) are most sensitive
# gentle compression of anything louder than COMP_BELOW_TARGET under the target loudness (applied
# after the piece is brought to that loudness), so quiet hairpins and sine troughs survive phones
COMP_BELOW_TARGET, COMP_RATIO = 8.0, 2.0
COMP_ATTACK, COMP_RELEASE = 0.02, 0.3  # seconds
TARGET_LUFS = -16.0  # typical for phones and streaming
CEILING_DB = -1.0  # peak limit
BLOCK = SAMPLE_RATE // 100  # 10 ms


def _smooth(x: list[float], w: int) -> list[float]:
    """Centred moving average of odd width w, padded with silence."""
    h, n = w // 2, len(x)
    p = [0.0, *accumulate([0.0] * h + x + [0.0] * h)]
    inv = 1 / w
    return [(b - a) * inv for a, b in zip(p[:n], p[w:w + n])]


def _lowpass(x: list[float], hz: float) -> list[float]:
    """Two cascaded moving averages (a triangular kernel, side-lobes about -26 dB), -3 dB near hz."""
    w = max(1, round(0.318 * SAMPLE_RATE / hz)) | 1
    return _smooth(_smooth(x, w), w)


def eq(x) -> list[float]:
    """High-pass, mud cut and presence lift for one recording."""
    x = [float(v) for v in x]
    mud, presence = 10 ** (MUD_DB / 20) - 1, 10 ** (PRESENCE_DB / 20) - 1
    lp = {hz: _lowpass(x, hz) for hz in (HIGHPASS_HZ, *MUD_BAND, *PRESENCE_BAND)}
    (m0, m1), (p0, p1) = MUD_BAND, PRESENCE_BAND
    return [v - a + mud * (c - b) + presence * (e - d)
            for v, a, b, c, d, e in zip(x, lp[HIGHPASS_HZ], lp[m0], lp[m1], lp[p0], lp[p1])]


def _blocks(x: list[float], f) -> list[float]:
    return [f(x[i:i + BLOCK]) for i in range(0, len(x), BLOCK)]


def _db(power: float) -> float:
    return 10 * math.log10(power) if power > 1e-20 else -200.0


def loudness_lufs(power_per_block: list[float]) -> float:
    """Integrated loudness (approximate EBU R128 gating, without K-weighting) from each block's
    mean square, on a 0 dBFS = 1.0 scale."""
    per = 40  # 400 ms windows
    windows = [sum(power_per_block[i:i + per]) / len(power_per_block[i:i + per])
               for i in range(0, len(power_per_block), per // 4)]  # 75% overlap
    gated = [p for p in windows if _db(p) - 0.691 > -70]
    if not gated:
        return -200.0
    relative = _db(sum(gated) / len(gated)) - 0.691 - 10
    gated = [p for p in gated if _db(p) - 0.691 > relative] or gated
    return _db(sum(gated) / len(gated)) - 0.691


def master(left: list[float], right: list[float], full_scale: float = 32767.0) -> tuple[list[float], list[float]]:
    """Compress, normalise to TARGET_LUFS and limit to CEILING_DB (the EQ was applied to each
    recording). Samples are on a scale where `full_scale` is 0 dBFS; the result is on the same scale."""
    n = len(left)
    if n == 0:
        return left, right
    norm = 1 / (full_scale * full_scale)
    power = [(a + b) * 0.5 * norm for a, b in zip(_blocks(left, lambda s: sum(map(mul, s, s)) / len(s)),
                                                 _blocks(right, lambda s: sum(map(mul, s, s)) / len(s)))]
    peaks = [max(a, b) / full_scale for a, b in zip(_blocks(left, lambda s: max(map(abs, s))),
                                                    _blocks(right, lambda s: max(map(abs, s))))]
    count = len(power)

    # bring the piece to the target loudness first, so the compressor's threshold means the same
    # thing whatever level the mix arrived at
    pre = 10 ** ((TARGET_LUFS - loudness_lufs(power)) / 20)
    power = [p * pre * pre for p in power]
    threshold = TARGET_LUFS - COMP_BELOW_TARGET

    # compressor: a block-rate envelope (circular warm-up so the loop point matches), then gain
    rate = SAMPLE_RATE / BLOCK
    attack, release = math.exp(-1 / (COMP_ATTACK * rate)), math.exp(-1 / (COMP_RELEASE * rate))
    env = _db(power[-1])
    levels = [0.0] * count
    for _pass in range(2):
        for i, p in enumerate(power):
            level = _db(p)
            k = attack if level > env else release
            env = k * env + (1 - k) * level
            levels[i] = env
    comp = [10 ** (-max(0.0, lv - threshold) * (1 - 1 / COMP_RATIO) / 20) for lv in levels]

    # makeup to the target loudness, measured after compression
    makeup = pre * 10 ** ((TARGET_LUFS - loudness_lufs([p * g * g for p, g in zip(power, comp)])) / 20)

    # limiter: each block's total gain may not push its peak (or a neighbour's) over the ceiling;
    # ramping between two gains that both respect this block's limit keeps every sample under it
    ceiling = 10 ** (CEILING_DB / 20)
    limit = [ceiling / p if p > 0 else math.inf for p in peaks]
    total = [min(c * makeup, limit[i - 1], limit[i], limit[(i + 1) % count]) for i, c in enumerate(comp)]

    out = []
    for x in (left, right):
        y: list[float] = []
        for b in range(count):
            g0, g1 = total[b - 1], total[b]  # ramp from the previous block's gain (wraps at the loop)
            block = x[b * BLOCK:(b + 1) * BLOCK]
            step = (g1 - g0) / len(block)
            y += [v * (g0 + step * (j + 1)) for j, v in enumerate(block)]
        out.append(y)
    return out[0], out[1]
