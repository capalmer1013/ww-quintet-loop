"""Finishing the stereo mix: hall reverb and, when mastering, EQ, compression, loudness and limiting
for small speakers (pedalboard and pyloudnorm).

pedalboard's processors are stateful and know nothing about loops, so each stateful stage runs over
the piece's own ending followed by the piece, keeping only the piece: a loop then sounds exactly as
it does when it follows itself, and the file repeats seamlessly.
"""

from __future__ import annotations

import math

import numpy as np
import pyloudnorm
from pedalboard import Compressor, HighpassFilter, Limiter, PeakFilter, Pedalboard, Reverb

from .config import Config
from .samples import SAMPLE_RATE

__all__ = ["finish", "reverb", "master", "eq_board", "loudness_lufs"]

# reverb: --reverb sets the wet level (times REVERB_WET_SCALE, calibrated so 0.3 matches the earlier
# hall's balance); --room sets the size
REVERB_DAMPING, REVERB_WIDTH = 0.5, 1.0
REVERB_WET_SCALE = 0.22  # pedalboard is ~3.2x wetter than the earlier hall at the same amount
REVERB_PREROLL_SECONDS = 10.0  # longer than the biggest room's tail

# EQ for phone speakers: rumble out, low-mid boxiness down, presence up
HIGHPASS_HZ, HIGHPASS_STAGES = 60.0, 2  # each stage is first-order: two give 12 dB/octave
MUD_HZ, MUD_DB, MUD_Q = 300.0, -3.0, 1.0
PRESENCE_HZ, PRESENCE_DB, PRESENCE_Q = 3500.0, 3.5, 0.9
# gentle compression of anything louder than COMP_BELOW_TARGET under the target loudness (after the
# piece is brought to that loudness), so quiet hairpins and sine troughs survive small speakers
COMP_BELOW_TARGET, COMP_RATIO, COMP_ATTACK_MS, COMP_RELEASE_MS = 8.0, 2.0, 20.0, 300.0
TARGET_LUFS = -16.0  # typical for phones and streaming
CEILING_DB = -1.0
LIMITER_RELEASE_MS = 100.0
DYNAMICS_PREROLL_SECONDS = 2.0  # several compressor/limiter release times
PEAK = 0.99  # without mastering, the mix is only scaled down to keep its peak under this


def _looped(board: Pedalboard, audio: np.ndarray, preroll_seconds: float) -> np.ndarray:
    """Run `board` over the piece's own last `preroll_seconds` then the piece; keep the piece."""
    n = audio.shape[1]
    pre = round(preroll_seconds * SAMPLE_RATE)
    head = np.tile(audio, (1, math.ceil(pre / n)))[:, -pre:] if pre else audio[:, :0]
    out = board(np.concatenate([head, audio], axis=1), SAMPLE_RATE, reset=True)
    return out[:, -n:]


def loudness_lufs(audio: np.ndarray) -> float:
    """Integrated loudness (EBU R128, K-weighted and gated) of (channels, frames) audio."""
    return pyloudnorm.Meter(SAMPLE_RATE).integrated_loudness(audio.T.astype(np.float64))


def _gain_to_target(audio: np.ndarray) -> float:
    loudness = loudness_lufs(audio)
    return 1.0 if not math.isfinite(loudness) else 10 ** ((TARGET_LUFS - loudness) / 20)


def reverb(audio: np.ndarray, amount: float, room: float) -> np.ndarray:
    """The dry mix plus `amount` of hall reverb, its tail carried over the loop point."""
    if amount < 0:
        raise ValueError(f"reverb amount must be >= 0, got {amount!r}")
    if not 0 <= room <= 1:
        raise ValueError(f"room must be in [0, 1], got {room!r}")
    if amount == 0 or audio.shape[1] == 0:
        return audio
    hall = Reverb(
        room_size=room, damping=REVERB_DAMPING, wet_level=amount * REVERB_WET_SCALE, dry_level=1.0, width=REVERB_WIDTH
    )
    return _looped(Pedalboard([hall]), audio, REVERB_PREROLL_SECONDS)


def eq_board() -> list:
    """The phone EQ: rumble out, low-mid boxiness down, presence up."""
    return [
        *(HighpassFilter(HIGHPASS_HZ) for _ in range(HIGHPASS_STAGES)),
        PeakFilter(MUD_HZ, MUD_DB, MUD_Q),
        PeakFilter(PRESENCE_HZ, PRESENCE_DB, PRESENCE_Q),
    ]


def master(audio: np.ndarray) -> np.ndarray:
    """EQ, compress, normalise to TARGET_LUFS and limit to CEILING_DB."""
    if audio.shape[1] == 0 or not np.any(audio):
        return audio
    audio = audio * _gain_to_target(audio)  # so the compressor threshold means the same for every piece
    shape = Pedalboard(
        [*eq_board(), Compressor(TARGET_LUFS - COMP_BELOW_TARGET, COMP_RATIO, COMP_ATTACK_MS, COMP_RELEASE_MS)]
    )
    audio = _looped(shape, audio, DYNAMICS_PREROLL_SECONDS)
    limiter = Pedalboard([Limiter(CEILING_DB, LIMITER_RELEASE_MS)])
    ceiling = 10 ** (CEILING_DB / 20)
    limit = lambda gain: np.clip(_looped(limiter, audio * gain, DYNAMICS_PREROLL_SECONDS), -ceiling, ceiling)
    gain = _gain_to_target(audio)
    gain *= _gain_to_target(limit(gain))  # limiting lowers the loudness a little: aim again once
    return limit(gain)


def finish(stereo: np.ndarray, config: Config) -> np.ndarray:
    """Reverb, then mastering (or, with --no-master, just a peak-safe scale)."""
    stereo = reverb(stereo, config.reverb, config.room)
    if config.master:
        return master(stereo)
    peak = float(np.abs(stereo).max()) if stereo.size else 0.0
    return stereo * min(1.0, PEAK / peak) if peak else stereo
