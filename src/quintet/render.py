"""Turn five voices into audio: monophonic lines, a staged stereo mix (finished by effects.py), WAV
files and piece code. Audio is float32 numpy, in [-1, 1]."""

from __future__ import annotations

import math
import zlib
from fractions import Fraction
from functools import cache, lru_cache
from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile

from .config import Config
from .effects import finish, place, reflections, send_gain
from .pattern import accents, expand, tile
from .samples import (
    CROSSFADE_SECONDS,
    QUINTET,
    RELEASE_SECONDS,
    SAMPLE_RATE,
    Instrument,
    Sample,
    instrument,
    loop_bounds,
    loopable,
    midi_to_note,
)
from .theory import PitchSet
from .voice import LFO_DEPTH_DB, LFO_PEAK_DB, SUSTAIN_MIN_BEATS, Voice, palette, piece_beats, resolve_pitch

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
    "retuned",
]

# fade where a note is cut short: 10% of the note, between 10 ms (short notes) and 150 ms (long)
CUT_FADE_SECONDS = (0.01, 0.15)
# short notes fade in over this many beats (150 ms at 60 bpm), at most a quarter of the note
ATTACK_BEATS = 0.15
# long notes (at least this long) swell <> from near silence up to their level and away again
LONG_NOTE_SECONDS = 1.5
HAIRPIN_PEAK = 0.4  # where in the note the swell peaks
HAIRPIN_FLOOR_DB = -30.0  # level at the note's start and end, relative to its peak
HAIRPIN_RISE_POWER = 3.0  # the crescendo stays quiet for longer, then blooms (1 = plain sin^2)
HAIRPIN_LEGATO_FLOOR_DB = -9.0  # a long note joined legato swells from (and back to) the line's level
# legato: only a phrase's first note is articulated (plays its recording's attack). Later notes skip
# their tongued attack and crossfade from the previous note:
LEGATO_SKIP_SECONDS = 0.06  # at least this much tongued attack is skipped on a joined note...
ATTACK_REACHED_DB = -4.0  # ...or up to where the recording first comes within this of its full level
LEGATO_CROSSFADE_SECONDS = 0.08  # pitch to pitch
# a repeated pitch is heard as a gentle "du": the old note fades out quicker and the new one comes in
# a little after, giving a short dip without a tongued attack
REPEAT_OUT_SECONDS, REPEAT_IN_DELAY_SECONDS, REPEAT_IN_SECONDS = 0.04, 0.03, 0.08
ALIGN_WINDOW, ALIGN_SEARCH = 1024, 1024  # frames: same-pitch joins are phase-aligned by cross-correlation
RENEW_CROSSFADE_SECONDS = 0.15  # a renewed note ("3=") joins its recording's steady middle seamlessly
# levelling: the library's recording levels differ by up to ~14 dB between instruments, so every
# sample is scaled so its loudest LEVEL_WINDOW_SECONDS hit LEVEL_REF_DB + DYNAMIC_DB[dynamic] (RMS)
LEVEL_REF_DB = -24.0  # mf
LEVEL_WINDOW_SECONDS = 0.3
DYNAMIC_DB = {"pp": -12.0, "p": -8.0, "mp": -4.0, "mf": 0.0, "f": 3.0, "ff": 6.0}
INSTRUMENT_TRIM_DB = {"flute": 0.0, "oboe": -3.0, "clarinet": 0.0, "horn": 1.5, "bassoon": 0.0}
# mild, fixed seating (-1 left .. +1 right): the high voices apart, horn and bassoon near the middle
PAN = {"flute": -0.35, "clarinet": -0.2, "bassoon": -0.05, "horn": 0.1, "oboe": 0.35}
# ...and how far back each sits (0 = front row .. 1 = back): flute and oboe in front, the horn at the
# back with its bell facing away
STAGE_DEPTH = {"flute": 0.0, "oboe": 0.0, "clarinet": 0.4, "bassoon": 0.6, "horn": 1.0}
MASTER_GAIN = 0.6
# performance (--humanize): seeded, and repeating with the piece so loops stay seamless
TIMING_SPREAD_MS, TIMING_LIMIT_MS, TIMING_STEP_MS = 10.0, 25.0, 2.0  # note onsets off the grid
# each instrument sits a little ahead of (-) or behind (+) the beat; horns speak late
ENSEMBLE_MS = {"flute": -6.0, "oboe": 4.0, "clarinet": 0.0, "horn": 10.0, "bassoon": 6.0}
PHRASE_END_STRETCH, PHRASE_END_STRETCH_MAX = 0.1, 0.2  # a phrase's last note leans into the rest (share; seconds)
LEVEL_SPREAD_DB, LEVEL_LIMIT_DB, LEVEL_STEP_DB = 0.5, 1.0, 0.25  # per-note level variation
BREATH_EVERY_SECONDS = (4.0, 8.0)  # a voice playing on without a rest breathes this often...
BREATH_SECONDS = (0.15, 0.3)  # ...for this long
PHRASE_GAP_SECONDS = (0.3, 0.6)  # a long tone running straight into another note ends this early
# intonation (--intonation): each note is tuned a few cents off, differently every time
INTONATION_SPREAD_CENTS, INTONATION_LIMIT_CENTS, INTONATION_STEP_CENTS = 2.0, 4.0, 0.5
SAMPLE_A4 = 440.0  # the concert pitch the sample library was recorded at
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


def hairpin(audio: np.ndarray, start_db: float = HAIRPIN_FLOOR_DB, end_db: float = HAIRPIN_FLOOR_DB) -> np.ndarray:
    """A copy of a note shaped <>: up from start_db to full at HAIRPIN_PEAK, then away to end_db. The
    rise is held back (HAIRPIN_RISE_POWER) so the note starts quieter and swells late."""
    n = len(audio)
    warp = math.log(0.5) / math.log(HAIRPIN_PEAK)  # moves sin^2's peak from 0.5 to HAIRPIN_PEAK
    t = ((np.arange(n) + 0.5) / n) ** warp
    shape = np.sin(np.pi * t) ** 2
    rising = t < 0.5
    shape[rising] **= HAIRPIN_RISE_POWER
    floor = np.where(rising, 10 ** (start_db / 20), 10 ** (end_db / 20))
    return audio * (floor + (1 - floor) * shape)


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


def retuned(audio: np.ndarray, cents: float) -> np.ndarray:
    """The recording played `cents` sharp (or flat if negative), by resampling. Its length changes
    by the same ratio (A432 is about 2% longer), which notes absorb since they are cut to length."""
    if not cents:
        return audio
    ratio = 2 ** (cents / 1200)
    positions = np.arange(int((len(audio) - 1) / ratio)) * ratio
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


@lru_cache(maxsize=256)
def _tuned(sample: Sample, dynamic: str, cents: float) -> np.ndarray:
    """leveled(), retuned by `cents`. Cached (read-only): at a fixed concert pitch each recording is
    always shifted by the same amount."""
    return _frozen(retuned(leveled(sample, dynamic), cents))


def _join_frames(join: str) -> int:
    """How long the previous note keeps sounding under a note joined as "legato", "repeat" or "renew"."""
    seconds_ = {"renew": RENEW_CROSSFADE_SECONDS, "repeat": REPEAT_OUT_SECONDS}.get(join, LEGATO_CROSSFADE_SECONDS)
    return round(seconds_ * SAMPLE_RATE)


@lru_cache(maxsize=4096)
def _attack_end(sample: Sample, dynamic: str) -> int:
    """The frame where a recording's attack is over: it first comes within ATTACK_REACHED_DB of its
    loudest 10 ms (flutes bloom slowly; reeds speak at once)."""
    full = leveled(sample, dynamic)
    hop = SAMPLE_RATE // 100
    frames = len(full) // hop
    if frames == 0:
        return 0
    rms = np.sqrt(np.mean(np.square(full[: frames * hop].reshape(frames, hop)), axis=1))
    reached = np.flatnonzero(rms >= rms.max() * 10 ** (ATTACK_REACHED_DB / 20))
    return int(reached[0]) * hop if reached.size else 0


def _default_skip(sample: Sample, dynamic: str, join: str | None) -> int:
    """Where a note starts in its recording: the start (articulated), past the attack (joined), or
    the steady middle (renewed)."""
    full = leveled(sample, dynamic)
    if join == "renew":
        return max(loop_bounds(len(full))[0], _attack_end(sample, dynamic))
    if join:
        return min(len(full) // 3, max(round(LEGATO_SKIP_SECONDS * SAMPLE_RATE), _attack_end(sample, dynamic)))
    return 0


def _aligned_skip(full: np.ndarray, base: int, previous: np.ndarray) -> int:
    """A start near `base` in a recording whose waveform lines up in phase with the end of
    `previous` (the note it continues), so a same-pitch crossfade doesn't partly cancel."""
    if len(previous) < ALIGN_WINDOW or len(full) < base + ALIGN_SEARCH + ALIGN_WINDOW:
        return base
    target = previous[-ALIGN_WINDOW:]
    region = full[base : base + ALIGN_SEARCH + ALIGN_WINDOW]
    score = np.correlate(region, target, mode="valid")
    energy = np.sqrt(np.convolve(np.square(region), np.ones(ALIGN_WINDOW), mode="valid")) + 1e-9
    return base + int(np.argmax(score / energy)) + ALIGN_WINDOW


@lru_cache(maxsize=4096)
def _note_audio(
    sample: Sample,
    dynamic: str,
    n: int,
    tempo: float,
    accent_db: float = 0.0,
    join_in: str | None = None,
    join_out: str | None = None,
    skip: int | None = None,
    cents: float = 0.0,
) -> np.ndarray:
    """One note: levelled, cut or sustained, shaped, then accented. Cached (read-only), since a
    cycling voice plays the same notes over and over.

    join_in is how the note is joined from the previous one in its phrase (None: it starts the
    phrase, articulated). join_out is how the next note is joined from this one (None: the phrase
    ends here); the result then runs _join_frames(join_out) past n, its tail fading out under the
    next note. A renewal crossfades linearly (the two are phase-aligned, so their amplitudes add);
    other joins are equal-power. skip is where in the recording the note starts (see _default_skip).
    """
    full = _tuned(sample, dynamic, cents)
    source = full[_default_skip(sample, dynamic, join_in) if skip is None else skip :]
    tail = _join_frames(join_out) if join_out else 0
    length = n + tail
    if len(source) >= length:
        audio = source[:length].copy()
        if not join_out:  # the phrase ends here: cut with a fade
            low, high = CUT_FADE_SECONDS
            k = min(n, round(min(high, max(low, 0.1 * n / SAMPLE_RATE)) * SAMPLE_RATE))
            audio[n - k :] *= (k - 1 - np.arange(k)) / k
    elif loopable(len(source), length):
        audio = sustain(source, length)
    else:  # too short to loop smoothly: play it once and let the rest of the note be silent
        audio = source.copy()
    sounding = len(audio)
    if sounding >= LONG_NOTE_SECONDS * SAMPLE_RATE:
        audio = hairpin(
            audio,
            HAIRPIN_LEGATO_FLOOR_DB if join_in else HAIRPIN_FLOOR_DB,
            HAIRPIN_LEGATO_FLOOR_DB if join_out else HAIRPIN_FLOOR_DB,
        )
    elif not join_in:
        k = min(sounding // 4, round(ATTACK_BEATS * 60 / tempo * SAMPLE_RATE))
        audio[:k] *= np.sin(np.pi / 2 * (np.arange(k) + 0.5) / k) ** 2
    if join_in:  # fade in under the previous note's tail (equal power); a repeat comes in a little late
        if join_in == "repeat":
            delay, rise = round(REPEAT_IN_DELAY_SECONDS * SAMPLE_RATE), round(REPEAT_IN_SECONDS * SAMPLE_RATE)
        else:
            delay, rise = 0, _join_frames(join_in)
        delay, rise = min(delay, sounding // 4), min(rise, sounding // 2)
        t = (np.arange(rise) + 0.5) / rise
        ramp = t if join_in == "renew" else np.sin(np.pi / 2 * t)
        audio[:delay] = 0
        audio[delay : delay + rise] *= ramp[: len(audio[delay : delay + rise])]
    if tail and sounding > n:  # fade out under the next note's start
        x = min(tail, sounding - n)
        t = (np.arange(x) + 0.5) / x
        audio[n : n + x] *= (1 - t) if join_out == "renew" else np.cos(np.pi / 2 * t)
        audio[n + x :] = 0
    if accent_db:
        audio = audio * 10 ** (accent_db / 20)
    if sounding < length:
        audio = np.concatenate([audio, np.zeros(length - sounding, dtype=np.float32)])
    return _frozen(audio)


def _rng(*key) -> np.random.Generator:
    """A random stream fixed by `key` (stable across runs and machines)."""
    return np.random.default_rng(zlib.crc32(repr(key).encode()))


def _breaths(events, pitches, beat_seconds: float, rng: np.random.Generator) -> list[float]:
    """Seconds of silence before each event (never inside a renewed held tone):
    - a long tone (SUSTAIN_MIN_BEATS or more, counting its renewals) that runs straight into another
      note ends early, leaving PHRASE_GAP_SECONDS before it;
    - otherwise a voice that plays on without a rest for BREATH_EVERY_SECONDS breathes at the next
      change of note."""
    count = len(events)
    gaps = [0.0] * count
    renewal = [isinstance(e.index, str) and e.index.endswith("=") for e in events]
    notes = [i for i in range(count) if pitches[i] is not None]
    # start on a phrase's first note, or with no rests at all, on a tone's first note
    first = next((i for i in notes if pitches[i - 1] is None), next((i for i in notes if not renewal[i]), 0))
    target, run, tone = rng.uniform(*BREATH_EVERY_SECONDS), 0.0, 0
    for step in range(count + 1):  # the last step comes back round to `first`, for the loop point
        i = (first + step) % count
        if pitches[i] is None:
            run, tone = 0.0, 0
            continue
        if step and pitches[i - 1] is not None and not renewal[i]:
            previous = float(events[i - 1].beats) * beat_seconds
            if tone >= SUSTAIN_MIN_BEATS:
                gaps[i] = min(rng.uniform(*PHRASE_GAP_SECONDS), previous / 2)
            elif run >= target:
                gaps[i] = min(rng.uniform(*BREATH_SECONDS), previous / 2)
            if gaps[i]:
                target, run = rng.uniform(*BREATH_EVERY_SECONDS), 0.0
        if step == count:
            break
        tone = (tone if renewal[i] else 0) + events[i].beats
        run += float(events[i].beats) * beat_seconds
    return gaps


def voice_line(
    inst: Instrument,
    v: Voice,
    notes: PitchSet,
    total: Fraction,
    tempo: float,
    humanize: bool = False,
    intonation: bool = False,
    a4: float = SAMPLE_A4,
) -> np.ndarray:
    """One instrument's monophonic line, exactly `total` beats long.

    Phrases are runs of notes with no rest between them (the piece loops, so a phrase may run over
    the loop point). Only a phrase's first note is articulated; each later note is joined legato
    (see _note_audio): a new pitch crossfades in past its tongued attack, a repeated pitch does the
    same with a slight dip so the repeat is heard, and a renewed note ("3=") joins seamlessly. Long
    notes swell <> (hairpin()); a phrase's first short note fades in.

    With `humanize`, it is played rather than sequenced (all seeded, repeating with the piece):
    notes land a few ms off the grid and the instrument sits slightly ahead of or behind the beat,
    a phrase's last note leans into the rest after it, a long tone leaves a gap before the next note,
    voices breathe in long phrases, repeats
    rotate between recordings of the note, and each note's level varies a little. With
    `intonation`, each note is also tuned a few cents off (a renewal keeps its note's tuning).
    Every note is retuned from the samples' A440 to concert pitch `a4`.
    """
    tones = palette(notes, inst)
    # metric accent of each event, by its start within the cycle
    accent = {e.start: a for e, a in zip(expand(v.pattern, v.span), accents(v.pattern))}
    frames = _frame(total, tempo)
    line = np.zeros(frames, dtype=np.float32)
    events = tile(v.pattern, v.span, total)
    count = len(events)
    pitches = [None if e.index is None else resolve_pitch(e.index, tones, notes, inst.playable) for e in events]
    beat_seconds = 60 / tempo
    key = (inst.name, repr(v.pattern), v.beats, v.drift, v.dynamic)
    breaths = _breaths(events, pitches, beat_seconds, _rng(*key, "breath")) if humanize else [0.0] * count

    def join(i: int) -> str | None:  # how event i is joined from the one before it
        if pitches[i] is None or pitches[i - 1] is None or breaths[i]:
            return None
        if isinstance(events[i].index, str) and events[i].index.endswith("="):
            return "renew"
        return "repeat" if pitches[i] == pitches[i - 1] else "legato"

    joins = [join(i) for i in range(count)]
    # where each event starts, in frames (off the grid when humanized)
    starts = [_frame(e.start, tempo) for e in events]
    level = [0.0] * count
    if humanize:
        rng = _rng(*key, "timing")
        lean = ENSEMBLE_MS[inst.name]
        for i in range(count):
            ms = lean + float(np.clip(rng.normal(0, TIMING_SPREAD_MS), -TIMING_LIMIT_MS, TIMING_LIMIT_MS))
            starts[i] += round(round(ms / TIMING_STEP_MS) * TIMING_STEP_MS / 1000 * SAMPLE_RATE)
        rng = _rng(*key, "level")
        for i in range(count):
            db = float(np.clip(rng.normal(0, LEVEL_SPREAD_DB), -LEVEL_LIMIT_DB, LEVEL_LIMIT_DB))
            level[i] = round(db / LEVEL_STEP_DB) * LEVEL_STEP_DB

    tuning = [0.0] * count
    if intonation:
        rng = _rng(*key, "intonation")
        for i in range(count):
            c = float(np.clip(rng.normal(0, INTONATION_SPREAD_CENTS), -INTONATION_LIMIT_CENTS, INTONATION_LIMIT_CENTS))
            tuning[i] = round(c / INTONATION_STEP_CENTS) * INTONATION_STEP_CENTS
        for i in range(count):  # a renewal is the same held tone, so it keeps that note's tuning
            if joins[i] == "renew":
                tuning[i] = tuning[i - 1]
    concert = 1200 * math.log2(a4 / SAMPLE_A4)
    tuning = [t + concert for t in tuning]
    played: dict[int, int] = {}  # times each pitch has sounded, to rotate between its recordings
    previous = None  # the last note's audio up to where the next one starts (for phase alignment)
    previous_sample = None
    for i, e in enumerate(events):
        if pitches[i] is None:
            continue
        j = (i + 1) % count
        start = starts[i]
        end = starts[j] + (frames if j <= i else 0)
        after = joins[j]
        if not after and humanize:
            if pitches[j] is None:  # the phrase ends on a rest: lean into it a little
                rest = float(events[j].beats) * beat_seconds
                note = float(e.beats) * beat_seconds
                end += round(min(PHRASE_END_STRETCH * note, PHRASE_END_STRETCH_MAX, rest / 2) * SAMPLE_RATE)
            elif breaths[j]:  # a breath before the next note
                end -= round(breaths[j] * SAMPLE_RATE)
        n = max(end - start, SAMPLE_RATE // 100)
        # a note joined into the next must still be sustaining, not releasing, when that note arrives
        need = n / SAMPLE_RATE + (RELEASE_SECONDS if after else 0.0)
        if joins[i] == "renew" and previous_sample is not None:
            sample = previous_sample  # a renewal continues the same recording, so it lines up
        else:
            takes = inst.takes(midi_to_note(pitches[i]), v.dynamic, need, max_dynamic=inst.max_layer)
            sample = takes[played.get(pitches[i], 0) % len(takes)] if humanize else takes[0]
            played[pitches[i]] = played.get(pitches[i], 0) + 1
        local = e.start - (e.start // v.span) * v.span
        skip = None
        if joins[i] in ("repeat", "renew") and previous is not None:
            full = _tuned(sample, v.dynamic, tuning[i])
            skip = _aligned_skip(full, _default_skip(sample, v.dynamic, joins[i]), previous)
        audio = _note_audio(
            sample, v.dynamic, n, tempo, round(accent.get(local, 0.0) + level[i], 2), joins[i], after, skip, tuning[i]
        )
        previous, previous_sample = audio[:n], sample
        _add_looped(line, audio, start)
    return line


def _add_looped(line: np.ndarray, audio: np.ndarray, start: int) -> None:
    """Add `audio` into the looping `line` from `start`: whatever runs past the loop point (or, for
    a humanized early start, before it) wraps round to the other end."""
    frames = len(line)
    position, done = start % frames, 0
    while done < len(audio):
        chunk = min(len(audio) - done, frames - position)
        line[position : position + chunk] += audio[done : done + chunk]
        done, position = done + chunk, 0


def lfo_curve(v: Voice, frames: int) -> np.ndarray | None:
    """The voice's volume-sine gain for every frame of a piece `frames` long (None if steady)."""
    if not v.lfo:
        return None
    # the sine changes over seconds: compute it every LFO_STEP frames and interpolate between
    coarse = np.arange(0, frames + LFO_STEP, LFO_STEP)
    dip = (1 - np.cos(2 * np.pi * ((coarse + 0.5) / frames * v.lfo + v.lfo_phase))) / 2
    gains = 10 ** ((LFO_PEAK_DB - LFO_DEPTH_DB * dip) / 20)
    return np.interp(np.arange(frames, dtype=np.float32), coarse, gains).astype(np.float32)


def mix(lines: dict[str, np.ndarray], voices: dict[str, Voice]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The staged mix as stereo (dry, early, send), each (2, frames), at MASTER_GAIN: every voice
    with its volume sine, placed at its STAGE_DEPTH and panned with constant power. `early` is its
    early reflections and `send` what feeds the hall, more of it for voices further back."""
    frames = len(lines[QUINTET[0]])
    dry, early, send = (np.zeros((2, frames), dtype=np.float32) for _ in range(3))
    for name in QUINTET:
        line = lines[name]
        curve = lfo_curve(voices[name], frames)
        if curve is not None:
            line = line * curve
        depth = STAGE_DEPTH[name]
        line = place(MASTER_GAIN * line, depth)
        theta = (PAN[name] + 1) * math.pi / 4
        panned = np.stack([math.cos(theta) * line, math.sin(theta) * line])
        dry += panned
        send += send_gain(depth) * panned
        early += reflections(line, PAN[name], depth)
    return dry, early, send


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
    lines = {
        n: voice_line(
            instrument(n, config), voices[n], notes, total, config.bpm(), config.humanize, config.intonation, config.a4
        )
        for n in QUINTET
    }
    out = config.output_dir
    dry, early, send = mix(lines, voices)
    paths = [write_wav(out / f"{name}.wav", finish(dry, config, early, send))]
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
        f"Config(tempo={config.tempo!r}, reverb={config.reverb!r}, room={config.room!r}, "
        + (f"reverb_ir={config.reverb_ir!r}, " if config.reverb_ir else "")
        + f"master={config.master!r}, saturation={config.saturation!r}, "
        f"humanize={config.humanize!r}, intonation={config.intonation!r}, a4={config.a4!r})\n"
        f"render({name!r}, {notes!r},\n{body})\n"
    )
