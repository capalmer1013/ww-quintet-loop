"""Staging, the hall and mastering: loop-safe, and each stage doing what it claims."""

import math

import numpy as np
import pytest
from pedalboard import Pedalboard

from quintet import SAMPLE_RATE, Config, finish, loudness_lufs, master, reverb
from quintet.effects import (
    CEILING_DB,
    DEPTH_DELAY_MS,
    REVERB_PREDELAY_MS,
    TARGET_LUFS,
    _fast_length,
    eq_board,
    impulse_response,
    place,
    reflections,
    saturate,
    send_gain,
    voice_tone,
)
from quintet.render import write_wav

RNG = np.random.default_rng(1)


def bursts(seconds: float) -> np.ndarray:
    """A quiet stand-in for a piece: alternating loud and soft noise bursts, stereo."""
    n = int(SAMPLE_RATE * seconds)
    envelope = np.where((np.arange(n) // (SAMPLE_RATE // 2)) % 2 == 0, 0.1, 0.01)
    return (RNG.uniform(-1, 1, (2, n)) * envelope).astype(np.float32)


def rms(x) -> float:
    """Root mean square, in float64."""
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def band_rms(x: np.ndarray, low: float, high: float) -> float:
    """RMS of the spectrum's magnitudes between `low` and `high` Hz."""
    spectrum = np.fft.rfft(x, axis=-1)
    hz = np.fft.rfftfreq(x.shape[-1], 1 / SAMPLE_RATE)
    return rms(np.abs(spectrum[..., (hz >= low) & (hz < high)]))


def test_reverb_tail_decays():
    impulse = np.zeros((2, SAMPLE_RATE * 6), dtype=np.float32)
    impulse[:, SAMPLE_RATE] = 1.0  # one click a second in, so the tail doesn't wrap onto itself
    wet = reverb(impulse, 0.5, 0.8)
    half = SAMPLE_RATE // 2
    windows = [rms(wet[:, i : i + half]) for i in range(SAMPLE_RATE + 2205, 4 * SAMPLE_RATE, half)]
    assert windows[0] > 0
    assert all(b < a for a, b in zip(windows, windows[1:]))


def test_reverb_tail_wraps_over_the_loop_point():
    x = bursts(3)
    once = reverb(x, 0.5, 0.8)
    twice = reverb(np.concatenate([x, x], axis=1), 0.5, 0.8)
    assert rms(once - twice[:, x.shape[1] :]) < 0.02 * rms(once)  # one loop == a loop that follows another


def test_hall_is_predelayed_unit_energy_and_darkens_as_it_decays():
    ir = impulse_response(0.8)
    assert not ir.flags.writeable
    np.testing.assert_allclose(np.sum(np.square(ir, dtype=np.float64), axis=1), 1.0, rtol=1e-4)
    gap = round(REVERB_PREDELAY_MS * SAMPLE_RATE / 1000)
    assert not np.any(ir[:, :gap]) and np.any(ir[:, gap : gap + 100])
    assert rms(ir[0] - ir[1]) > rms(ir[0])  # the two sides are different noise: a wide hall
    early, late = ir[:, gap : gap + SAMPLE_RATE // 2], ir[:, SAMPLE_RATE : SAMPLE_RATE * 3 // 2]
    darkening = lambda x: band_rms(x, 4000, 8000) / band_rms(x, 500, 1000)
    assert darkening(late) < 0.5 * darkening(early)  # highs die first
    whole = band_rms(ir, 1000, 2000)
    assert band_rms(ir, 20, 100) < 0.1 * whole and band_rms(ir, 14000, 20000) < 0.1 * whole  # the hall's EQ
    assert impulse_response(0.3).shape[1] < ir.shape[1]  # a smaller room rings for less long


def test_reverb_uses_its_send_and_a_recorded_space(tmp_path):
    x = bursts(1)
    assert np.array_equal(reverb(x, 0.5, 0.8, send=np.zeros_like(x)), x)
    path = tmp_path / "space.wav"
    recorded = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
    recorded[[0, 2000]] = [1.0, 0.5]  # a mono space: two echoes
    write_wav(path, recorded)
    ir = impulse_response(0.8, str(path))
    assert ir.shape[0] == 2 and np.array_equal(ir[0], ir[1])
    assert rms(reverb(x, 0.5, 0.8, ir=str(path)) - reverb(x, 0.5, 0.8)) > 0


def test_short_piece_folds_the_hall_seamlessly():
    x = bursts(0.5)  # shorter than the hall's tail
    once = reverb(x, 0.5, 0.8)
    many = reverb(np.tile(x, 8), 0.5, 0.8)
    np.testing.assert_allclose(once, many[:, -x.shape[1] :], atol=1e-4)


def test_fast_length_is_small_and_has_only_factors_2_3_5():
    for n in (1, 7, 1000, 44100 * 150 + 1):
        m = _fast_length(n)
        assert m >= n and m < 2 * n + 1
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        assert m == 1


def test_place_delays_and_darkens_further_back():
    line = RNG.uniform(-0.1, 0.1, SAMPLE_RATE * 2).astype(np.float32)
    assert place(line, 0.0) is line
    back = place(line, 1.0)
    lag = int(np.argmax(np.abs(np.fft.irfft(np.fft.rfft(back) * np.conj(np.fft.rfft(line)), len(line)))))
    assert lag == round(DEPTH_DELAY_MS * SAMPLE_RATE / 1000)
    assert band_rms(back, 8000, 16000) < 0.75 * band_rms(line, 8000, 16000)
    assert abs(band_rms(back, 200, 1000) / band_rms(line, 200, 1000) - 1) < 0.05
    assert send_gain(0) == 1 and send_gain(1) > send_gain(0.5) > 1


def test_voice_tone_tames_the_oboe_and_leaves_the_rest():
    line = RNG.uniform(-0.1, 0.1, SAMPLE_RATE * 2).astype(np.float32)
    for name in ("flute", "clarinet", "horn", "bassoon"):
        assert voice_tone(line, name) is line
    oboe = voice_tone(line, "oboe")
    assert band_rms(oboe, 1000, 1500) < 0.8 * band_rms(line, 1000, 1500)  # the nasal honk
    assert band_rms(oboe, 2600, 3500) < 0.8 * band_rms(line, 2600, 3500)  # the reedy edge
    assert band_rms(oboe, 10000, 16000) < 0.8 * band_rms(line, 10000, 16000)  # the buzz on top
    assert abs(band_rms(oboe, 200, 500) / band_rms(line, 200, 500) - 1) < 0.05  # the body is kept
    # loop-safe: the start sounds as it does following the end
    twice = voice_tone(np.concatenate([line, line]), "oboe")
    assert np.allclose(oboe[:4096], twice[len(line) : len(line) + 4096], atol=1e-4)


def test_reflections_reach_the_nearer_wall_first():
    click = np.zeros(SAMPLE_RATE, dtype=np.float32)
    click[0] = 1.0
    first = lambda echoes, side: int(np.flatnonzero(echoes[side])[0])
    left = reflections(click, -1.0, 0.0)
    assert first(left, 0) < first(reflections(click, 1.0, 0.0), 0)
    assert first(reflections(click, 0.0, 1.0), 0) < first(reflections(click, 0.0, 0.0), 0)
    assert 0 < float(np.abs(left).max()) < 0.25  # quiet


def test_saturate_rounds_peaks_and_keeps_quiet_audio():
    x = np.linspace(-1, 1, 101, dtype=np.float32)
    assert saturate(x, 0) is x
    y = saturate(x, 0.3)
    assert np.all(np.abs(y) <= np.abs(x) + 1e-7) and np.all(np.diff(y) > 0)  # rounds peaks off, keeps order
    assert abs(float(y[51]) - float(x[51])) < 1e-4  # quiet audio passes unchanged
    assert float(y[-1]) < 0.9
    with pytest.raises(ValueError):
        saturate(x, -0.1)


def test_reverb_off_and_invalid():
    x = bursts(1)
    assert reverb(x, 0, 0.8) is x
    for amount, room in ((-0.1, 0.5), (0.5, 1.5)):
        with pytest.raises(ValueError):
            reverb(x, amount, room)


@pytest.mark.parametrize(
    "hz, low, high",
    [(40, -40, -8), (100, -5, -2), (300, -4, -2), (1000, -0.7, 0.7), (3500, 3, 4), (10000, 0.5, 2), (16000, 1, 2)],
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
    early = bursts(2)
    assert np.array_equal(finish(x, Config(argv=[], tempo=60, reverb=0, master=False), early), dry)  # no room
    roomy = finish(x, Config(argv=[], tempo=60, reverb=0.5, master=False), early, np.zeros_like(x))
    assert rms(roomy - dry) > 0  # the early reflections, with nothing sent to the hall
    Config(argv=[], tempo=60)  # leave a default current config for later tests


def test_master_saturation_still_hits_the_target():
    x = bursts(4)
    clean, warm = master(x), master(x, saturation=0.3)
    assert abs(loudness_lufs(warm) - TARGET_LUFS) < 0.5
    assert rms(warm - clean) > 0
