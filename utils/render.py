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
from .pattern import accents, expand, tile
from .master import eq, master
from .reverb import reverb
from .samples import QUINTET, SAMPLE_RATE, Instrument, Sample, instrument, midi_to_note
from .theory import PitchSet
from .voice import Voice, palette, piece_beats, resolve_pitch

__all__ = ["render", "piece_code", "voice_line", "sustain", "mix", "write_wav", "seconds",
           "leveled", "loudness_db", "hairpin", "lfo_gains", "with_gains", "loopable", "sustainable_frames"]

# fade where a note is cut short: 10% of the note, between 10 ms (short notes) and 150 ms (long)
CUT_FADE_SECONDS = (0.01, 0.15)
# sustain extension: a note longer than its sample loops the sample's steady middle
ATTACK_SECONDS = 0.3  # (or the first quarter of the sample) kept as-is at the start
RELEASE_SECONDS = 0.6  # (or the last 35%) played at the end as the note's natural release
CROSSFADE_SECONDS = 0.1  # equal-power crossfade at each loop seam
# only loop a sample whose steady middle is long enough not to stutter, and not too many times;
# otherwise the sample plays once (with its natural release) and the rest of the note is silent
MIN_LOOP_SECONDS = 0.8
MAX_LOOP_REPEATS = 3
LFO_BLOCK = 512  # frames per volume-sine gain step (~12 ms)
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
def leveled(sample: Sample, dynamic: str, equalised: bool = False) -> array:
    """The sample (EQ'd for small speakers if `equalised`, see master.eq) scaled to the target level
    for `dynamic` (see LEVEL_REF_DB). Cached."""
    audio = sample.load()
    if equalised:
        audio = eq(audio)
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


def _loop_bounds(audio) -> tuple[int, int]:
    """(attack end, release start): the steady middle a sustain loops."""
    attack = min(len(audio) // 4, round(ATTACK_SECONDS * SAMPLE_RATE))
    return attack, len(audio) - min(round(len(audio) * 0.35), round(RELEASE_SECONDS * SAMPLE_RATE))


def sustainable_frames(length: int) -> int:
    """The longest note a sample of `length` frames can play without stuttering: itself, plus
    MAX_LOOP_REPEATS of its steady middle if that is long enough to loop."""
    attack, release_at = _loop_bounds(range(length))
    loop = release_at - attack
    if loop < MIN_LOOP_SECONDS * SAMPLE_RATE:
        return length
    step = loop - min(round(CROSSFADE_SECONDS * SAMPLE_RATE), loop // 3)  # each repeat adds this much
    return length + MAX_LOOP_REPEATS * step


def loopable(audio: array, n: int) -> bool:
    """Whether stretching the sample to n frames keeps its loop long and its repeats few."""
    most = sustainable_frames(len(audio))
    return most > len(audio) and n <= most


def sustain(audio: array, n: int) -> array:
    """Stretch a sample to n frames: attack, the steady middle looped with crossfades, release."""
    attack, release_at = _loop_bounds(audio)
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
def _note_audio(sample: Sample, dynamic: str, n: int, tempo: float, accent_db: float = 0.0,
                equalised: bool = False) -> array:
    """One note of n frames: levelled, cut with a fade or sustained, shaped, then accented. Cached,
    since a cycling voice plays the same notes over and over; do not modify the result."""
    source = leveled(sample, dynamic, equalised)
    if len(source) >= n:  # cut short by the next event
        audio = source[:n]
        low, high = CUT_FADE_SECONDS
        k = min(n, round(min(high, max(low, 0.1 * n / SAMPLE_RATE)) * SAMPLE_RATE))
        for i in range(k):
            audio[n - k + i] = int(audio[n - k + i] * (k - 1 - i) / k)
    elif loopable(source, n):
        audio = sustain(source, n)
    else:  # too short to loop smoothly: play it once and let the rest of the note be silent
        audio = source[:]
    sounding = len(audio)
    if sounding >= LONG_NOTE_SECONDS * SAMPLE_RATE:
        audio = hairpin(audio)
    else:
        k = min(sounding // 4, round(ATTACK_BEATS * 60 / tempo * SAMPLE_RATE))
        for i in range(k):
            audio[i] = int(audio[i] * math.sin(math.pi / 2 * (i + 0.5) / k) ** 2)
    if accent_db:
        g = 10 ** (accent_db / 20)
        audio = array("h", [max(-32768, min(32767, int(x * g))) for x in audio])
    if sounding < n:
        audio.extend(array("h", bytes(2 * (n - sounding))))
    return audio


def voice_line(inst: Instrument, v: Voice, notes: PitchSet, total: Fraction, tempo: float,
               equalised: bool = False) -> array:
    """One instrument's monophonic line as 16-bit frames, exactly `total` beats long.

    Each note sounds until the next event starts: a sample longer than that is cut with a fade, a
    shorter one is sustained (see sustain()). Long notes swell <> (hairpin()); short ones fade in.
    """
    tones = palette(notes, inst)
    # metric accent of each event, by its start within the cycle
    accent = {e.start: a for e, a in zip(expand(v.pattern, v.span), accents(v.pattern))}
    line = array("h")
    for e in tile(v.pattern, v.span, total):
        start, end = _frame(e.start, tempo), _frame(e.start + e.beats, tempo)
        n = end - start
        if e.index is None:
            line.extend(array("h", bytes(2 * n)))
            continue
        midi = resolve_pitch(e.index, tones, notes, inst.playable)
        sample = inst.note(midi_to_note(midi), v.dynamic, seconds(e.beats, tempo), max_dynamic=inst.max_layer)
        local = e.start - (e.start // v.span) * v.span
        audio = _note_audio(sample, v.dynamic, n, tempo, round(accent.get(local, 0.0), 2), equalised)
        line.extend(audio)
    return line


def lfo_gains(v: Voice, frames: int) -> list[float]:
    """The voice's volume-sine gain for each LFO_BLOCK of a piece `frames` long."""
    return [v.gain((a + LFO_BLOCK / 2) / frames) for a in range(0, frames, LFO_BLOCK)]


def with_gains(line: array, gains: list[float]) -> array:
    """A copy of a line with per-LFO_BLOCK gains applied (for stems)."""
    out = array("h")
    for b, g in enumerate(gains):
        out.extend(array("h", [int(x * g) for x in line[b * LFO_BLOCK:(b + 1) * LFO_BLOCK]]))
    return out


def mix(lines: dict[str, array], gains: dict[str, list[float]] | None = None, reverb_amount: float = 0.0,
        room: float = 0.8, mastered: bool = False) -> tuple[array, array]:
    """Constant-power panned stereo at MASTER_GAIN, with per-LFO_BLOCK voice gains folded into the pan
    gains, plus reverb; scaled down if it would peak above PEAK."""
    frames = len(lines[QUINTET[0]])
    blocks = range(0, frames, LFO_BLOCK)
    gains = gains or {}
    voice_gains = [gains.get(n) or [1.0] * len(blocks) for n in QUINTET]
    pans = [(PAN[n] + 1) * math.pi / 4 for n in QUINTET]
    pan_l = [MASTER_GAIN * math.cos(t) for t in pans]
    pan_r = [MASTER_GAIN * math.sin(t) for t in pans]
    a, b, c, d, e = (lines[n] for n in QUINTET)
    left: list[float] = []
    right: list[float] = []
    for i, start in enumerate(blocks):
        gs = [g[i] for g in voice_gains]
        l0, l1, l2, l3, l4 = (p * g for p, g in zip(pan_l, gs))
        r0, r1, r2, r3, r4 = (p * g for p, g in zip(pan_r, gs))
        sl = slice(start, start + LFO_BLOCK)
        block = list(zip(a[sl], b[sl], c[sl], d[sl], e[sl]))
        left += [v * l0 + w * l1 + x * l2 + y * l3 + z * l4 for v, w, x, y, z in block]
        right += [v * r0 + w * r1 + x * r2 + y * r3 + z * r4 for v, w, x, y, z in block]
    left, right = reverb(left, right, reverb_amount, room)
    if mastered:  # EQ, compression, loudness and a -1 dB limiter (see master.py)
        left, right = master(left, right)  # its limiter keeps every sample at or under -1 dBFS
        return array("h", map(int, left)), array("h", map(int, right))
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
    lines = {n: voice_line(instrument(n, config), voices[n], notes, total, config.bpm(), config.master)
             for n in QUINTET}
    out = config.output_dir
    frames = len(lines[QUINTET[0]])
    gains = {n: lfo_gains(voices[n], frames) for n in QUINTET if voices[n].lfo}
    paths = [write_wav(out / f"{name}.wav", *mix(lines, gains, config.reverb, config.room, config.master))]
    if config.stems:
        paths += [write_wav(out / f"{name}_{n}.wav", with_gains(lines[n], gains[n]) if n in gains else lines[n])
                  for n in QUINTET]
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
        f'"""{name}: {about}{notes!r}, {config.bpm():g} bpm, {seconds(total, config.bpm()):.2f}s"""\n'
        "import sys\n"
        f"sys.path.insert(0, {str(repo)!r})  # directory containing utils/\n"
        "from utils import *\n\n"
        f"Config(tempo={config.tempo!r}, reverb={config.reverb!r}, room={config.room!r}, master={config.master!r})\n"
        f"render({name!r}, {notes!r},\n{body})\n"
    )
