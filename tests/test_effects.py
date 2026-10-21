import math

import numpy as np
import pytest
from pedalboard import Pedalboard

from quintet import SAMPLE_RATE, Config, finish, loudness_lufs, master, reverb
from quintet.effects import CEILING_DB, TARGET_LUFS, eq_board

RNG = np.random.default_rng(1)


def bursts(seconds: float) -> np.ndarray:
    """A quiet stand-in for a piece: alternating loud and soft noise bursts, stereo."""
    n = int(SAMPLE_RATE * seconds)
    envelope = np.where((np.arange(n) // (SAMPLE_RATE // 2)) % 2 == 0, 0.1, 0.01)
    return (RNG.uniform(-1, 1, (2, n)) * envelope).astype(np.float32)


def rms(x) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def test_reverb_tail_decays():
    impulse = np.zeros((2, SAMPLE_RATE * 6), dtype=np.float32)
    impulse[:, SAMPLE_RATE] = 1.0  # one click a second in, so the tail doesn't wrap onto itself
    wet = reverb(impulse, 0.5, 0.8)
    half = SAMPLE_RATE // 2
    windows = [rms(wet[:, i : i + half]) for i in range(SAMPLE_RATE + 2205, 5 * SAMPLE_RATE, half)]
    assert windows[0] > 0
    assert all(b < a for a, b in zip(windows, windows[1:]))


def test_reverb_tail_wraps_over_the_loop_point():
    x = bursts(3)
    once = reverb(x, 0.5, 0.8)
    twice = reverb(np.concatenate([x, x], axis=1), 0.5, 0.8)
    assert rms(once - twice[:, x.shape[1] :]) < 0.02 * rms(once)  # one loop == a loop that follows another


def test_reverb_off_and_invalid():
    x = bursts(1)
    assert reverb(x, 0, 0.8) is x
    for amount, room in ((-0.1, 0.5), (0.5, 1.5)):
        with pytest.raises(ValueError):
            reverb(x, amount, room)


@pytest.mark.parametrize(
    "hz, low, high", [(40, -40, -8), (100, -5, -2), (300, -4, -2), (1000, -0.7, 0.7), (3500, 3, 4), (10000, -0.5, 1.5)]
)
def test_eq_response(hz, low, high):
    t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * hz * t).astype(np.float32)[None]
    out = Pedalboard(eq_board())(tone, SAMPLE_RATE, reset=True)
    assert low <= 20 * math.log10(rms(out[:, SAMPLE_RATE:]) / rms(tone[:, SAMPLE_RATE:])) <= high


def test_master_loudness_ceiling_and_seam():
    x = bursts(12)
    out = master(x)
    assert out.shape == x.shape
    assert abs(loudness_lufs(out) - TARGET_LUFS) < 0.5
    assert float(np.abs(out).max()) <= 10 ** (CEILING_DB / 20) + 1e-6
    twice = master(np.concatenate([x, x], axis=1))
    assert rms(out - twice[:, x.shape[1] :]) < 0.05 * rms(out)


def test_finish_respects_flags():
    x = bursts(2)
    dry = finish(x, Config(argv=[], tempo=60, reverb=0, master=False))
    np.testing.assert_allclose(dry, x * min(1.0, 0.99 / float(np.abs(x).max())))
    mastered = finish(x, Config(argv=[], tempo=60, reverb=0, master=True))
    assert abs(loudness_lufs(mastered) - TARGET_LUFS) < 0.5
    Config(argv=[], tempo=60)
