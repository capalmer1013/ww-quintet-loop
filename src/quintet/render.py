"""Turn five voices into audio: monophonic lines, a panned stereo mix (finished by effects.py), WAV
files and piece code. Audio is float32 numpy, in [-1, 1]."""

from __future__ import annotations

import math
from fractions import Fraction
from functools import cache, lru_cache
from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile

from .config import Config
from .effects import finish
from .pattern import accents, expand, tile
from .samples import (
    CROSSFADE_SECONDS,
    QUINTET,
    SAMPLE_RATE,
    Instrument,
    Sample,
    instrument,
    loop_bounds,
    loopable,
    midi_to_note,
)
from .theory import PitchSet
from .voice import LFO_DEPTH_DB, LFO_PEAK_DB, Voice, palette, piece_beats, resolve_pitch

__all__ = [
    "render",
    "piece_code",
    "voice_line",
    "sustain",
    "mix",
    "write_wav",
    "seconds",
    "leveled",
    "loudness_db",
    "hairpin",
    "lfo_curve",
]

# fade where a note is cut short: 10% of the note, between 10 ms (short notes) and 150 ms (long)
CUT_FADE_SECONDS = (0.01, 0.15)
# short notes fade in over this many beats (150 ms at 60 bpm), at most a quarter of the note
ATTACK_BEATS = 0.15
# long notes (at least this long) swell <> from near silence up to their level and away again
LONG_NOTE_SECONDS = 1.5
HAIRPIN_PEAK = 0.4  # where in the note the swell peaks
HAIRPIN_FLOOR_DB = -30.0  # level at the note's start and end, relative to its peak
# levelling: the library's recording levels differ by up to ~14 dB between instruments, so every
# sample is scaled so its loudest LEVEL_WINDOW_SECONDS hit LEVEL_REF_DB + DYNAMIC_DB[dynamic] (RMS)
LEVEL_REF_DB = -24.0  # mf
LEVEL_WINDOW_SECONDS = 0.3
DYNAMIC_DB = {"pp": -12.0, "p": -8.0, "mp": -4.0, "mf": 0.0, "f": 3.0, "ff": 6.0}
INSTRUMENT_TRIM_DB = {"flute": 0.0, "oboe": 0.0, "clarinet": 0.0, "horn": 0.0, "bassoon": 0.0}
# mild, fixed seating (-1 left .. +1 right): the high voices apart, horn and bassoon near the middle
PAN = {"flute": -0.35, "clarinet": -0.2, "bassoon": -0.05, "horn": 0.1, "oboe": 0.35}
MASTER_GAIN = 0.6
LFO_STEP = 64  # frames between computed points of a volume sine (1.5 ms)


def seconds(beats, tempo: float) -> float:
    return float(Fraction(beats) * 60 / Fraction(tempo))


def _frame(beats: Fraction, tempo: float) -> int:
    return round(Fraction(beats) * 60 * SAMPLE_RATE / Fraction(tempo))


def _frozen(audio: np.ndarray) -> np.ndarray:
    audio = audio.astype(np.float32, copy=False)
    audio.flags.writeable = False
    return audio


def loudness_db(audio: np.ndarray) -> float:
    """RMS level in dBFS of the loudest LEVEL_WINDOW_SECONDS of a recording."""
    w = min(len(audio), round(LEVEL_WINDOW_SECONDS * SAMPLE_RATE))
    if w == 0:
        return -120.0
    energy = np.concatenate(([0.0], np.cumsum(np.square(audio, dtype=np.float64))))
    starts = np.arange(0, len(audio) - w + 1, SAMPLE_RATE // 100)
    best = float((energy[starts + w] - energy[starts]).max())
    return 10 * math.log10(best / w) if best > 0 else -120.0


@cache
def leveled(sample: Sample, dynamic: str) -> np.ndarray:
    """The recording scaled to the target level for `dynamic` (see LEVEL_REF_DB). Cached, read-only."""
    audio = sample.load()
    target = LEVEL_REF_DB + DYNAMIC_DB[dynamic] + INSTRUMENT_TRIM_DB[sample.instrument]
    return _frozen(audio * 10 ** ((target - loudness_db(audio)) / 20))


def hairpin(audio: np.ndarray) -> np.ndarray:
    """A copy of a note shaped <>: up from HAIRPIN_FLOOR_DB to full at HAIRPIN_PEAK, then away."""
    n = len(audio)
    floor = 10 ** (HAIRPIN_FLOOR_DB / 20)
    warp = math.log(0.5) / math.log(HAIRPIN_PEAK)  # moves sin^2's peak from 0.5 to HAIRPIN_PEAK
    t = ((np.arange(n) + 0.5) / n) ** warp
    return audio * (floor + (1 - floor) * np.sin(np.pi * t) ** 2)


def _crossfade(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a then b, overlapping a's tail with b's head (equal power)."""
    x = min(round(CROSSFADE_SECONDS * SAMPLE_RATE), len(a) // 3, len(b) // 3)
    if x == 0:
        return np.concatenate([a, b])
    t = np.pi / 2 * (np.arange(x) + 0.5) / x
    return np.concatenate([a[: len(a) - x], a[len(a) - x :] * np.cos(t) + b[:x] * np.sin(t), b[x:]])


def sustain(audio: np.ndarray, n: int) -> np.ndarray:
    """Stretch a recording to n frames: attack, the steady middle looped with crossfades, release."""
    attack, release_at = loop_bounds(len(audio))
    loop, release = audio[attack:release_at], audio[release_at:]
    body = audio[:release_at]
    while len(body) + len(release) < n + 2 * round(CROSSFADE_SECONDS * SAMPLE_RATE):
        body = _crossfade(body, loop)
    # trim the body so that body + release (minus their crossfade) is exactly n frames
    keep = n - len(release) + min(round(CROSSFADE_SECONDS * SAMPLE_RATE), len(release) // 3)
    while True:
        out = _crossfade(body[:keep], release)
        if len(out) == n:
            return out
        keep += n - len(out)


@lru_cache(maxsize=2048)
def _note_audio(sample: Sample, dynamic: str, n: int, tempo: float, accent_db: float = 0.0) -> np.ndarray:
    """One note of n frames: levelled, cut with a fade or sustained, shaped, then accented. Cached
    (read-only), since a cycling voice plays the same notes over and over."""
    source = leveled(sample, dynamic)
    if len(source) >= n:  # cut short by the next event
        audio = source[:n].copy()
        low, high = CUT_FADE_SECONDS
        k = min(n, round(min(high, max(low, 0.1 * n / SAMPLE_RATE)) * SAMPLE_RATE))
        audio[n - k :] *= (k - 1 - np.arange(k)) / k
    elif loopable(len(source), n):
        audio = sustain(source, n)
    else:  # too short to loop smoothly: play it once and let the rest of the note be silent
        audio = source.copy()
    sounding = len(audio)
    if sounding >= LONG_NOTE_SECONDS * SAMPLE_RATE:
        audio = hairpin(audio)
    else:
        k = min(sounding // 4, round(ATTACK_BEATS * 60 / tempo * SAMPLE_RATE))
        audio[:k] *= np.sin(np.pi / 2 * (np.arange(k) + 0.5) / k) ** 2
    if accent_db:
        audio = audio * 10 ** (accent_db / 20)
    if sounding < n:
        audio = np.concatenate([audio, np.zeros(n - sounding, dtype=np.float32)])
    return _frozen(audio)


def voice_line(inst: Instrument, v: Voice, notes: PitchSet, total: Fraction, tempo: float) -> np.ndarray:
    """One instrument's monophonic line, exactly `total` beats long.

    Each note sounds until the next event starts: a recording longer than that is cut with a fade, a
    shorter one is sustained (see sustain()). Long notes swell <> (hairpin()); short ones fade in.
    """
    tones = palette(notes, inst)
    # metric accent of each event, by its start within the cycle
    accent = {e.start: a for e, a in zip(expand(v.pattern, v.span), accents(v.pattern))}
    line = np.zeros(_frame(total, tempo), dtype=np.float32)
    for e in tile(v.pattern, v.span, total):
        if e.index is None:
            continue
        start, end = _frame(e.start, tempo), _frame(e.start + e.beats, tempo)
        midi = resolve_pitch(e.index, tones, notes, inst.playable)
        sample = inst.note(midi_to_note(midi), v.dynamic, seconds(e.beats, tempo), max_dynamic=inst.max_layer)
        local = e.start - (e.start // v.span) * v.span
        line[start:end] = _note_audio(sample, v.dynamic, end - start, tempo, round(accent.get(local, 0.0), 2))
    return line


def lfo_curve(v: Voice, frames: int) -> np.ndarray | None:
    """The voice's volume-sine gain for every frame of a piece `frames` long (None if steady)."""
    if not v.lfo:
        return None
    # the sine changes over seconds: compute it every LFO_STEP frames and interpolate between
    coarse = np.arange(0, frames + LFO_STEP, LFO_STEP)
    dip = (1 - np.cos(2 * np.pi * ((coarse + 0.5) / frames * v.lfo + v.lfo_phase))) / 2
    gains = 10 ** ((LFO_PEAK_DB - LFO_DEPTH_DB * dip) / 20)
    return np.interp(np.arange(frames, dtype=np.float32), coarse, gains).astype(np.float32)


def mix(lines: dict[str, np.ndarray], voices: dict[str, Voice]) -> np.ndarray:
    """Constant-power panned stereo, shape (2, frames), at MASTER_GAIN, with each voice's volume sine."""
    frames = len(lines[QUINTET[0]])
    stereo = np.zeros((2, frames), dtype=np.float32)
    for name in QUINTET:
        line = lines[name]
        curve = lfo_curve(voices[name], frames)
        if curve is not None:
            line = line * curve
        theta = (PAN[name] + 1) * math.pi / 4
        stereo[0] += MASTER_GAIN * math.cos(theta) * line
        stereo[1] += MASTER_GAIN * math.sin(theta) * line
    return stereo


def write_wav(path: Path, audio: np.ndarray) -> Path:
    """Write mono (frames,) or stereo (2, frames) float audio as 16-bit WAV at SAMPLE_RATE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.atleast_2d(audio).astype(np.float32)
    with AudioFile(str(path), "w", samplerate=SAMPLE_RATE, num_channels=audio.shape[0], bit_depth=16) as f:
        f.write(audio)
    return path


def render(name: str, notes: PitchSet, **voices: Voice) -> list[Path]:
    """Write <name>.wav (and stems if config.stems) for the five quintet voices."""
    if set(voices) != set(QUINTET):
        missing, unknown = set(QUINTET) - set(voices), set(voices) - set(QUINTET)
        raise ValueError(f"render needs exactly {QUINTET}; missing {sorted(missing)}, unknown {sorted(unknown)}")
    config = Config.current()
    total = piece_beats(voices.values())
    lines = {n: voice_line(instrument(n, config), voices[n], notes, total, config.bpm()) for n in QUINTET}
    out = config.output_dir
    paths = [write_wav(out / f"{name}.wav", finish(mix(lines, voices), config))]
    if config.stems:  # dry and unmastered, with the volume sine
        for n in QUINTET:
            curve = lfo_curve(voices[n], len(lines[n]))
            paths.append(write_wav(out / f"{name}_{n}.wav", lines[n] if curve is None else lines[n] * curve))
    return paths


def piece_code(name: str, notes: PitchSet, voices: dict[str, Voice], seed: int | None = None) -> str:
    """Source for a .py file that reproduces this piece with render()."""
    config = Config.current()
    total = piece_beats(voices.values())
    about = f"seed {seed}, " if seed is not None else ""
    width = max(map(len, QUINTET))
    body = "".join(f"    {n:<{width}} = {voices[n].code()},\n" for n in QUINTET)
    return (
        f'"""{name}: {about}{notes!r}, {config.bpm():g} bpm, {seconds(total, config.bpm()):.2f}s"""\n'
        "from quintet import *\n\n"
        f"Config(tempo={config.tempo!r}, reverb={config.reverb!r}, room={config.room!r}, master={config.master!r})\n"
        f"render({name!r}, {notes!r},\n{body})\n"
    )
