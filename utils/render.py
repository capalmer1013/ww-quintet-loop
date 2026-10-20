"""Turn five voices into audio: monophonic lines, a panned stereo mix, WAV files and piece code."""
from __future__ import annotations

import math
import wave
from array import array
from fractions import Fraction
from functools import lru_cache
from itertools import accumulate
from pathlib import Path

from .config import Config
from .pattern import tile
from .samples import QUINTET, SAMPLE_RATE, Instrument, Sample, instrument, midi_to_note
from .theory import PitchSet
from .voice import Voice, palette, piece_beats

__all__ = ["render", "piece_code", "voice_line", "sustain", "mix", "write_wav", "seconds",
           "leveled", "loudness_db", "hairpin"]

# fade where a note is cut short: 10% of the note, between 10 ms (short notes) and 150 ms (long)
CUT_FADE_SECONDS = (0.01, 0.15)
# sustain extension: a note longer than its sample loops the sample's steady middle
ATTACK_SECONDS = 0.3  # (or the first quarter of the sample) kept as-is at the start
RELEASE_SECONDS = 0.6  # (or the last 35%) played at the end as the note's natural release
CROSSFADE_SECONDS = 0.1  # equal-power crossfade at each loop seam
# short notes fade in over this many beats (80 ms at 60 bpm), at most a quarter of the note
ATTACK_BEATS = 0.08
# long notes (at least this long) swell <> from near silence up to their level and away again
LONG_NOTE_SECONDS = 1.5
HAIRPIN_PEAK = 0.4  # where in the note the swell peaks
HAIRPIN_FLOOR_DB = -30.0  # level at the note's start and end, relative to its peak
MAX_LAYER = "mp"  # loudest recorded dynamic ever used; quieter layers stand in when a note lacks it
# levelling: the library's recording levels differ by up to ~14 dB between instruments, so every
# sample is scaled so its loudest LEVEL_WINDOW_SECONDS hit LEVEL_REF_DB + DYNAMIC_DB[dynamic] (RMS)
LEVEL_REF_DB = -24.0  # mf
LEVEL_WINDOW_SECONDS = 0.3
DYNAMIC_DB = {"pp": -12.0, "p": -8.0, "mp": -4.0, "mf": 0.0, "f": 3.0, "ff": 6.0}
INSTRUMENT_TRIM_DB = {"flute": 0.0, "oboe": 0.0, "clarinet": 0.0, "horn": 0.0, "bassoon": 0.0}
PAN = {"flute": -0.6, "oboe": -0.25, "bassoon": 0.0, "clarinet": 0.25, "horn": 0.6}
MASTER_GAIN = 0.6
PEAK = 0.99


def seconds(beats, tempo: float) -> float:
    return float(Fraction(beats) * 60 / Fraction(tempo))


def _frame(beats: Fraction, tempo: float) -> int:
    return round(Fraction(beats) * 60 * SAMPLE_RATE / Fraction(tempo))


def loudness_db(audio: array) -> float:
    """RMS level in dBFS of the loudest LEVEL_WINDOW_SECONDS of a sample."""
    w = min(len(audio), round(LEVEL_WINDOW_SECONDS * SAMPLE_RATE))
    energy = [0, *accumulate(x * x for x in audio)]
    best = max(energy[i + w] - energy[i] for i in range(0, len(audio) - w + 1, SAMPLE_RATE // 100))
    return 10 * math.log10(best / w / 32768 ** 2) if best else -120.0


@lru_cache(maxsize=None)
def leveled(sample: Sample, dynamic: str) -> array:
    """The sample scaled to the target level for `dynamic` (see LEVEL_REF_DB). Cached."""
    audio = sample.load()
    target = LEVEL_REF_DB + DYNAMIC_DB[dynamic] + INSTRUMENT_TRIM_DB[sample.instrument]
    g = 10 ** ((target - loudness_db(audio)) / 20)
    return array("h", [max(-32768, min(32767, round(x * g))) for x in audio])


@lru_cache(maxsize=256)
def _hairpin_curve(n: int) -> tuple[float, ...]:
    floor = 10 ** (HAIRPIN_FLOOR_DB / 20)
    warp = math.log(0.5) / math.log(HAIRPIN_PEAK)  # moves sin^2's peak from 0.5 to HAIRPIN_PEAK
    return tuple(floor + (1 - floor) * math.sin(math.pi * ((i + 0.5) / n) ** warp) ** 2 for i in range(n))


def hairpin(audio: array) -> array:
    """A copy of a note shaped <>: up from HAIRPIN_FLOOR_DB to full at HAIRPIN_PEAK, then away."""
    return array("h", [int(x * g) for x, g in zip(audio, _hairpin_curve(len(audio)))])


def _crossfade(a: array, b: array) -> array:
    """a then b, overlapping a's tail with b's head over len(overlap) frames (equal power)."""
    x = min(round(CROSSFADE_SECONDS * SAMPLE_RATE), len(a) // 3, len(b) // 3)
    mixed = array("h", (
        round(a[len(a) - x + i] * math.cos(math.pi / 2 * (i + 0.5) / x)
              + b[i] * math.sin(math.pi / 2 * (i + 0.5) / x))
        for i in range(x)
    ))
    return a[:len(a) - x] + mixed + b[x:]


def sustain(audio: array, n: int) -> array:
    """Stretch a sample to n frames: attack, the steady middle looped with crossfades, release."""
    attack = min(len(audio) // 4, round(ATTACK_SECONDS * SAMPLE_RATE))
    release_at = len(audio) - min(round(len(audio) * 0.35), round(RELEASE_SECONDS * SAMPLE_RATE))
    loop, release = audio[attack:release_at], audio[release_at:]
    body = audio[:release_at]
    while len(body) + len(release) < n + 2 * round(CROSSFADE_SECONDS * SAMPLE_RATE):
        body = _crossfade(body, loop)
    # trim the body so that body + release (minus their crossfade) is exactly n frames
    x = min(round(CROSSFADE_SECONDS * SAMPLE_RATE), len(release) // 3)
    keep = n - len(release) + x
    while True:
        out = _crossfade(body[:keep], release)
        if len(out) == n:
            return out
        keep += n - len(out)


@lru_cache(maxsize=1024)
def _note_audio(sample: Sample, dynamic: str, n: int, tempo: float) -> array:
    """One note of n frames: levelled, cut with a fade or sustained, then shaped. Cached, since a
    cycling voice plays the same notes over and over; do not modify the result."""
    source = leveled(sample, dynamic)
    if len(source) >= n:  # cut short by the next event
        audio = source[:n]
        low, high = CUT_FADE_SECONDS
        k = min(n, round(min(high, max(low, 0.1 * n / SAMPLE_RATE)) * SAMPLE_RATE))
        for i in range(k):
            audio[n - k + i] = int(audio[n - k + i] * (k - 1 - i) / k)
    else:
        audio = sustain(source, n)
    if n >= LONG_NOTE_SECONDS * SAMPLE_RATE:
        return hairpin(audio)
    k = min(n // 4, round(ATTACK_BEATS * 60 / tempo * SAMPLE_RATE))
    for i in range(k):
        audio[i] = int(audio[i] * math.sin(math.pi / 2 * (i + 0.5) / k) ** 2)
    return audio


def voice_line(inst: Instrument, v: Voice, notes: PitchSet, total: Fraction, tempo: float) -> array:
    """One instrument's monophonic line as 16-bit frames, exactly `total` beats long.

    Each note sounds until the next event starts: a sample longer than that is cut with a fade, a
    shorter one is sustained (see sustain()). Long notes swell <> (hairpin()); short ones fade in.
    """
    tones = palette(notes, inst)
    line = array("h")
    for e in tile(v.pattern, v.span, total):
        start, end = _frame(e.start, tempo), _frame(e.start + e.beats, tempo)
        n = end - start
        if e.index is None:
            line.extend(array("h", bytes(2 * n)))
            continue
        midi = tones[(e.index - 1) % len(tones)]
        sample = inst.note(midi_to_note(midi), v.dynamic, seconds(e.beats, tempo), max_dynamic=MAX_LAYER)
        audio = _note_audio(sample, v.dynamic, n, tempo)
        line.extend(audio)
    return line


def mix(lines: dict[str, array]) -> tuple[array, array]:
    """Constant-power panned stereo at MASTER_GAIN, scaled down if it would peak above PEAK."""
    pans = [(PAN[n] + 1) * math.pi / 4 for n in QUINTET]
    l0, l1, l2, l3, l4 = (MASTER_GAIN * math.cos(t) for t in pans)
    r0, r1, r2, r3, r4 = (MASTER_GAIN * math.sin(t) for t in pans)
    frames = list(zip(*(lines[n] for n in QUINTET)))
    left = [v * l0 + w * l1 + x * l2 + y * l3 + z * l4 for v, w, x, y, z in frames]
    right = [v * r0 + w * r1 + x * r2 + y * r3 + z * r4 for v, w, x, y, z in frames]
    peak = max(max(map(abs, left), default=0), max(map(abs, right), default=0))
    scale = min(1.0, PEAK * 32767 / peak) if peak else 1.0
    return array("h", [int(x * scale) for x in left]), array("h", [int(x * scale) for x in right])


def write_wav(path: Path, *channels: array) -> Path:
    """Write one (mono) or two (stereo) equal-length 16-bit channels at SAMPLE_RATE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = channels[0]
    if len(channels) == 2:
        data = array("h", bytes(4 * len(channels[0])))
        data[0::2], data[1::2] = channels
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data.tobytes())
    return path


def render(name: str, notes: PitchSet, **voices: Voice) -> list[Path]:
    """Write <name>.wav (and stems if config.stems) for the five quintet voices."""
    if set(voices) != set(QUINTET):
        missing, unknown = set(QUINTET) - set(voices), set(voices) - set(QUINTET)
        raise ValueError(f"render needs exactly {QUINTET}; missing {sorted(missing)}, unknown {sorted(unknown)}")
    config = Config.current()
    total = piece_beats(voices.values())
    lines = {n: voice_line(instrument(n, config), voices[n], notes, total, config.tempo) for n in QUINTET}
    out = config.output_dir
    paths = [write_wav(out / f"{name}.wav", *mix(lines))]
    if config.stems:
        paths += [write_wav(out / f"{name}_{n}.wav", lines[n]) for n in QUINTET]
    return paths


def piece_code(name: str, notes: PitchSet, voices: dict[str, Voice], seed: int | None = None) -> str:
    """Source for a .py file that reproduces this piece with render()."""
    config = Config.current()
    total = piece_beats(voices.values())
    about = f"seed {seed}, " if seed is not None else ""
    repo = Path(__file__).resolve().parent.parent
    width = max(map(len, QUINTET))
    body = "".join(f"    {n:<{width}} = {voices[n].code()},\n" for n in QUINTET)
    return (
        f'"""{name}: {about}{notes!r}, {seconds(total, config.tempo):.2f}s"""\n'
        "import sys\n"
        f"sys.path.insert(0, {str(repo)!r})  # directory containing utils/\n"
        "from utils import *\n\n"
        f"Config(tempo={config.tempo!r})\n"
        f"render({name!r}, {notes!r},\n{body})\n"
    )
