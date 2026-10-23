"""Finishing the stereo mix for render.py: the stage (each voice's tone, depth and early
reflections), a convolution hall and, when mastering, EQ, saturation, compression, loudness and
limiting for small speakers (numpy, pedalboard and pyloudnorm).

Every piece loops, so nothing here may make the loop point sound different from the rest of it.
Delays wrap round and the hall is a circular convolution, both exact. pedalboard's processors are
stateful and know nothing about loops, so each stateful stage runs over the piece's own ending
followed by the piece, keeping only the piece: a loop then sounds as it does when it follows itself.
"""

from __future__ import annotations

import math
from functools import cache

import numpy as np
import pyloudnorm
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    Limiter,
    LowpassFilter,
    PeakFilter,
    Pedalboard,
)
from pedalboard.io import AudioFile

from .config import Config
from .samples import SAMPLE_RATE

__all__ = [
    "finish",
    "reverb",
    "impulse_response",
    "voice_tone",
    "place",
    "reflections",
    "send_gain",
    "master",
    "saturate",
    "eq_board",
    "loudness_lufs",
]

# --- pre-roll: how much of a piece's ending a stateful processor hears before the piece ---
FILTER_PREROLL_SECONDS = 0.1  # plenty for a shelf or pass filter to settle
DYNAMICS_PREROLL_SECONDS = 2.0  # several compressor/limiter release times

# --- stage: a voice further back (depth 0 = front row .. 1 = back) arrives later, darker and wetter ---
DEPTH_DELAY_MS = 6.0  # at depth 1: about 2 m further away
DEPTH_SHELF_HZ, DEPTH_SHELF_DB = 4000.0, -4.0  # at depth 1: air absorbs the highs
DEPTH_SEND_DB = 4.0  # extra hall at depth 1

# --- per-instrument tone, by ear: (hz, dB, q) peaks then a (hz, dB) high shelf ---
# the oboe: its nasal honk and reedy edge down (the edge is also where mastering's presence boost
# lands), its buzz softened
VOICE_EQ = {"oboe": ([(1200.0, -3.0, 1.0), (3000.0, -3.0, 1.0)], (6000.0, -3.0))}

# --- early reflections: (ms after the direct sound, dB) off alternate side walls, left first ---
# a voice panned towards a wall hears it sooner; one further back hears all of them closer together
REFLECTIONS = ((9.0, -14.0), (14.0, -15.0), (21.0, -17.0), (29.0, -19.0), (38.0, -21.0))  # quiet: no combing
REFLECTION_PAN_SKEW = 0.25  # share of a tap's delay a full pan towards its wall takes off (away: adds)
REFLECTION_DEPTH_SQUEEZE = 0.35  # share of every tap's delay depth 1 takes off
REFLECTION_LOWPASS_HZ = 6000.0  # walls absorb the highs

# --- hall: --reverb sets the wet level, --room its size, --reverb-ir a recorded space instead ---
REVERB_WET_SCALE = 0.2  # wet level per unit of --reverb (calibrated by loudness over seeds 7, 12 and 31)
REVERB_PREDELAY_MS = 25.0  # a gap before the hall, so attacks stay clear
REVERB_HIGHPASS_HZ, REVERB_LOWPASS_HZ = 250.0, 7000.0  # the hall's own EQ: no low-end mud, no hiss
REVERB_FILTER_STAGES = 2  # each first-order: two give 12 dB/octave
REVERB_CROSSFEED = 0.5  # how much of the other channel each side of the hall hears

# --- the built-in hall: decaying noise, each octave at its own rate (highs die first) ---
HALL_RT60_SECONDS = (0.6, 3.1)  # time to fall 60 dB at --room 0 and 1; 0.9 gives about 2.85 s
HALL_OCTAVES_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
HALL_DECAY_RATIO = (1.3, 1.2, 1.1, 1.0, 1.0, 0.9, 0.75, 0.55, 0.4)  # each octave's RT60, times the hall's
HALL_LENGTH_RT60S = 1.2  # long enough to fall 72 dB
HALL_ONSET_MS = 12.0  # the reflections build up into the diffuse tail over this long
HALL_SEED = 0

# --- mastering EQ for phone speakers: rumble out, low-mid boxiness down, presence and air up ---
HIGHPASS_HZ, HIGHPASS_STAGES = 60.0, 2  # each stage is first-order: two give 12 dB/octave
MUD_HZ, MUD_DB, MUD_Q = 300.0, -3.0, 1.0
PRESENCE_HZ, PRESENCE_DB, PRESENCE_Q = 3500.0, 3.5, 0.9
AIR_HZ, AIR_DB = 10000.0, 1.5  # a high shelf

# --- mastering dynamics ---
# saturation is tanh(drive * x) / drive: quiet audio passes unchanged, peaks round off with a little
# warmth; drive = --saturation * SATURATION_DRIVE
SATURATION_DRIVE = 3.0
# gentle compression of anything louder than COMP_BELOW_TARGET dB under the target loudness (applied
# once the piece is at that loudness), so quiet hairpins and sine troughs survive small speakers
COMP_BELOW_TARGET, COMP_RATIO, COMP_ATTACK_MS, COMP_RELEASE_MS = 10.0, 3.0, 20.0, 300.0
TARGET_LUFS = -13.0  # loud enough for phones that the peaks reach the ceiling
CEILING_DB = -3.0  # headroom for lossy encoding and players' own processing
LIMITER_RELEASE_MS = 100.0
PEAK = 0.99  # without mastering, the mix is only scaled down to keep its peak under this


def _frames(ms: float) -> int:
    """Milliseconds as a whole number of frames."""
    return round(ms * SAMPLE_RATE / 1000)


def _looped(board: Pedalboard, audio: np.ndarray, preroll_seconds: float) -> np.ndarray:
    """Run `board` over the piece's own last `preroll_seconds` then the piece; keep the piece."""
    n = audio.shape[-1]
    pre = round(preroll_seconds * SAMPLE_RATE)
    head = np.tile(audio, math.ceil(pre / n))[..., -pre:] if pre else audio[..., :0]
    out = board(np.concatenate([head, audio], axis=-1), SAMPLE_RATE, reset=True)
    return out[..., -n:]


def loudness_lufs(audio: np.ndarray) -> float:
    """Integrated loudness (EBU R128, K-weighted and gated) of (channels, frames) audio."""
    return pyloudnorm.Meter(SAMPLE_RATE).integrated_loudness(audio.T.astype(np.float64))


def _gain_to_target(audio: np.ndarray) -> float:
    """The gain that brings `audio` to TARGET_LUFS (1 for silence, which has no loudness)."""
    loudness = loudness_lufs(audio)
    return 1.0 if not math.isfinite(loudness) else 10 ** ((TARGET_LUFS - loudness) / 20)


# --- the stage ---


def voice_tone(line: np.ndarray, name: str) -> np.ndarray:
    """A mono line with its instrument's VOICE_EQ (the line itself if it has none)."""
    if name not in VOICE_EQ or len(line) == 0:
        return line
    peaks, (shelf_hz, shelf_db) = VOICE_EQ[name]
    board = Pedalboard([*(PeakFilter(hz, db, q) for hz, db, q in peaks), HighShelfFilter(shelf_hz, shelf_db)])
    return _looped(board, line, FILTER_PREROLL_SECONDS)


def place(line: np.ndarray, depth: float) -> np.ndarray:
    """A mono line moved `depth` back on the stage: later and darker (the delay wraps round)."""
    if depth == 0 or len(line) == 0:
        return line
    darker = Pedalboard([HighShelfFilter(DEPTH_SHELF_HZ, DEPTH_SHELF_DB * depth)])
    return np.roll(_looped(darker, line, FILTER_PREROLL_SECONDS), _frames(DEPTH_DELAY_MS * depth))


def send_gain(depth: float) -> float:
    """How much of a voice at `depth` goes to the hall, relative to the front row."""
    return 10 ** (DEPTH_SEND_DB * depth / 20)


def reflections(line: np.ndarray, pan: float, depth: float) -> np.ndarray:
    """A placed mono line's early reflections, stereo (2, frames). Still full-range: finish() darkens
    the sum over all voices once."""
    out = np.zeros((2, len(line)), dtype=np.float32)
    for i, (ms, db) in enumerate(REFLECTIONS):
        side = i % 2  # 0 = left wall, 1 = right
        towards = -pan if side == 0 else pan  # +1 = panned all the way to this wall
        delay = ms * (1 - REFLECTION_PAN_SKEW * towards) * (1 - REFLECTION_DEPTH_SQUEEZE * depth)
        out[side] += 10 ** (db / 20) * np.roll(line, _frames(delay))
    return out


# --- the hall ---


def _hall(room: float) -> np.ndarray:
    """The built-in hall's stereo impulse response, before its EQ and pre-delay."""
    rt60 = HALL_RT60_SECONDS[0] + room * (HALL_RT60_SECONDS[1] - HALL_RT60_SECONDS[0])
    n = round(HALL_LENGTH_RT60S * rt60 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    spectrum = np.fft.rfft(np.random.default_rng(HALL_SEED).standard_normal((2, n)))
    octave = np.log2(np.maximum(np.fft.rfftfreq(n, 1 / SAMPLE_RATE), 1.0))
    centres = np.log2(HALL_OCTAVES_HZ)
    out = np.zeros((2, n))
    for k, (centre, ratio) in enumerate(zip(centres, HALL_DECAY_RATIO)):
        # triangular weights in log-frequency between neighbouring octaves: they sum to 1 everywhere
        weight = np.clip(1 - np.abs(octave - centre), 0, 1)
        if k == 0:
            weight[octave < centre] = 1
        if k == len(centres) - 1:
            weight[octave > centre] = 1
        band = np.fft.irfft(spectrum * weight, n)
        out += band * 10 ** (-3 * t / (rt60 * ratio))  # -60 dB at this octave's RT60
    return out * (1 - np.exp(-t / (HALL_ONSET_MS / 1000)))


def _recorded(path: str) -> np.ndarray:
    """A recorded impulse response at SAMPLE_RATE, stereo (a mono one on both sides)."""
    with AudioFile(path) as f, f.resampled_to(SAMPLE_RATE) as r:
        ir = r.read(r.frames)
    return np.vstack([ir[0], ir[0]]) if ir.shape[0] == 1 else ir[:2]


@cache
def impulse_response(room: float, path: str = "") -> np.ndarray:
    """The hall the mix is convolved with, stereo (2, frames): a recorded space from `path`, else
    the built-in hall of size `room`. EQ'd, pre-delayed and scaled to unit energy per channel, so
    --reverb means the same for any space. Cached, so returned read-only."""
    ir = (_recorded(path) if path else _hall(room)).astype(np.float32)
    eq = Pedalboard(
        [HighpassFilter(REVERB_HIGHPASS_HZ) for _ in range(REVERB_FILTER_STAGES)]
        + [LowpassFilter(REVERB_LOWPASS_HZ) for _ in range(REVERB_FILTER_STAGES)]
    )
    ir = eq(ir, SAMPLE_RATE, reset=True)
    ir = np.concatenate([np.zeros((2, _frames(REVERB_PREDELAY_MS)), dtype=np.float32), ir], axis=1)
    energy = np.sqrt(np.sum(np.square(ir, dtype=np.float64), axis=1, keepdims=True))
    ir = (ir / np.where(energy > 0, energy, 1)).astype(np.float32)
    ir.flags.writeable = False
    return ir


def _fast_length(n: int) -> int:
    """The smallest 2^a 3^b 5^c at least n: a length numpy's FFT is quick at."""
    best = 1 << max(n - 1, 0).bit_length()
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def _circular_convolve(audio: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Each channel of `audio` convolved with the same channel of `ir`, the tail wrapping round to the
    start: exactly what a loop that follows itself hears."""
    n = audio.shape[1]
    if ir.shape[1] > n:  # a piece shorter than the hall: fold the hall onto the piece's length
        ir = np.pad(ir, ((0, 0), (0, -ir.shape[1] % n))).reshape(2, -1, n).sum(axis=1)
    size = _fast_length(n + ir.shape[1] - 1)
    full = np.fft.irfft(np.fft.rfft(audio, size) * np.fft.rfft(ir, size), size)[:, : n + ir.shape[1] - 1]
    out = full[:, :n].copy()
    out[:, : full.shape[1] - n] += full[:, n:]
    return out.astype(np.float32)


def reverb(audio: np.ndarray, amount: float, room: float, send: np.ndarray | None = None, ir: str = "") -> np.ndarray:
    """The dry mix plus `amount` of the hall, fed by `send` (the mix itself if None), its tail carried
    over the loop point. Both channels feed each side of the hall, the other one at REVERB_CROSSFEED."""
    if amount < 0:
        raise ValueError(f"reverb amount must be >= 0, got {amount!r}")
    if not 0 <= room <= 1:
        raise ValueError(f"room must be in [0, 1], got {room!r}")
    if amount == 0 or audio.shape[1] == 0:
        return audio
    send = audio if send is None else send
    crossed = np.stack([send[0] + REVERB_CROSSFEED * send[1], send[1] + REVERB_CROSSFEED * send[0]])
    return audio + amount * REVERB_WET_SCALE * _circular_convolve(crossed, impulse_response(room, ir))


# --- mastering ---


def eq_board() -> list:
    """The phone EQ: rumble out, low-mid boxiness down, presence and air up."""
    return [
        *(HighpassFilter(HIGHPASS_HZ) for _ in range(HIGHPASS_STAGES)),
        PeakFilter(MUD_HZ, MUD_DB, MUD_Q),
        PeakFilter(PRESENCE_HZ, PRESENCE_DB, PRESENCE_Q),
        HighShelfFilter(AIR_HZ, AIR_DB),
    ]


def saturate(audio: np.ndarray, amount: float) -> np.ndarray:
    """Gentle tape-style saturation: tanh(drive * x) / drive, with drive = amount * SATURATION_DRIVE."""
    if amount < 0:
        raise ValueError(f"saturation must be >= 0, got {amount!r}")
    drive = amount * SATURATION_DRIVE
    return audio if drive == 0 else (np.tanh(drive * audio) / drive).astype(np.float32)


def master(audio: np.ndarray, saturation: float = 0.0) -> np.ndarray:
    """EQ, saturate, compress, normalise to TARGET_LUFS and limit to CEILING_DB."""
    if audio.shape[1] == 0 or not np.any(audio):
        return audio
    # the mix arrives far below full scale (levelling only cuts): bring its peak to full scale first,
    # or the loudness meter's absolute gate (-70 LUFS) would leave out its quiet passages
    audio = audio / float(np.abs(audio).max())
    audio = audio * _gain_to_target(audio)  # at the target, saturation and compression mean the same for any piece
    audio = saturate(_looped(Pedalboard(eq_board()), audio, FILTER_PREROLL_SECONDS), saturation)
    compressor = Pedalboard([Compressor(TARGET_LUFS - COMP_BELOW_TARGET, COMP_RATIO, COMP_ATTACK_MS, COMP_RELEASE_MS)])
    audio = _looped(compressor, audio, DYNAMICS_PREROLL_SECONDS)
    limiter = Pedalboard([Limiter(CEILING_DB, LIMITER_RELEASE_MS)])
    ceiling = 10 ** (CEILING_DB / 20)
    limit = lambda gain: np.clip(_looped(limiter, audio * gain, DYNAMICS_PREROLL_SECONDS), -ceiling, ceiling)
    gain = _gain_to_target(audio)
    gain *= _gain_to_target(limit(gain))  # limiting lowers the loudness a little: aim again once
    return limit(gain)


def finish(
    stereo: np.ndarray, config: Config, early: np.ndarray | None = None, send: np.ndarray | None = None
) -> np.ndarray:
    """The room (early reflections, darkened by the walls, and the hall, fed by `send`), then mastering
    (or, with --no-master, just a peak-safe scale). --reverb 0 leaves out the whole room."""
    if config.reverb and early is not None:
        walls = Pedalboard([LowpassFilter(REFLECTION_LOWPASS_HZ)])
        stereo = stereo + _looped(walls, early, FILTER_PREROLL_SECONDS)
    stereo = reverb(stereo, config.reverb, config.room, send, config.reverb_ir)
    if config.master:
        return master(stereo, config.saturation)
    peak = float(np.abs(stereo).max()) if stereo.size else 0.0
    return stereo * min(1.0, PEAK / peak) if peak else stereo
