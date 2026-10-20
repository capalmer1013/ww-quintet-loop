"""Voices: a pattern cycling over its own span, with a palette spaced by the harmonic series."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from fractions import Fraction
from functools import reduce

from .config import Config
from .pattern import _, expand
from .samples import DYNAMICS, QUINTET, Instrument, instrument
from .theory import PitchSet

__all__ = ["Voice", "voice", "piece_beats", "palette", "generate", "Profile", "PROFILES"]

# --- spacing: each voice is centred on a partial of a low fundamental on the set's root, and owns
# the band halfway to its neighbours' centres, so bands are wide at the bottom and narrow on top ---
FUNDAMENTAL_NEAR = 36  # the fundamental is the set's root nearest C2: G1 (31) .. Fs2 (42)
LOW_TO_HIGH = ("bassoon", "horn", "clarinet", "oboe", "flute")
PARTIALS = (2, 3, 4, 6, 8)  # per LOW_TO_HIGH; for C: C3 G3 C4 G4 C5
OUTER_REACH = 12  # semitones below the lowest centre / above the highest
MIN_PALETTE = 3  # widen a band a semitone each side until it has this many notes

# --- generation ---
@dataclass(frozen=True)
class Profile:
    """How one instrument tends to play. Lines are a walk over its palette (see _walk)."""

    moves: tuple[float, float, float, float]  # weights: repeat, step (±1), skip (±2), leap (±3+)
    split: float  # chance a slot subdivides into a quick figure
    figure: str  # what a subdivision plays: run, pair, arpeggio, repeat, bounce
    figure_notes: tuple[int, int]  # notes in a figure, inclusive
    rest: float  # chance a slot rests (breathing)
    hold: float  # chance a slot holds the previous note
    slots: tuple[int, int]  # slots per cycle, inclusive
    beats: tuple[int, int]  # cycle length in beats, inclusive
    sustain: float  # relative chance of being one of the piece's sustaining voices
    anchors: tuple[int, ...] = ()  # semitones above the root weighted x2 (0 root, 7 fifth)
    octave: float = 1.0  # extra weight on leaping exactly an octave


PROFILES = {
    "flute": Profile((10, 50, 25, 15), 0.20, "run", (3, 4), 0.05, 0.10, (3, 6), (2, 8), 1),
    "oboe": Profile((15, 60, 20, 5), 0.10, "pair", (2, 2), 0.20, 0.20, (2, 5), (3, 8), 2),
    "clarinet": Profile((10, 25, 45, 20), 0.15, "arpeggio", (2, 4), 0.10, 0.15, (2, 6), (2, 8), 3),
    "horn": Profile((50, 15, 30, 5), 0.12, "repeat", (2, 3), 0.10, 0.25, (2, 5), (3, 8), 3,
                    anchors=(0, 7)),
    "bassoon": Profile((25, 25, 15, 35), 0.12, "bounce", (2, 2), 0.15, 0.10, (2, 6), (2, 8), 2,
                       anchors=(0,), octave=3.0),
}
DRIFT_CHANCE, DRIFTS, MAX_DRIFTING = 0.2, (8, 12, 16, 24), 2
MIN_DISTINCT_SPANS = 4  # at least this many different cycle lengths, so the voices phase
MAX_ATTEMPTS = 10_000
# sustaining voices: few notes, mostly held, over longer cycles
SUSTAINERS = (1, 2)  # voices per piece, inclusive
SUSTAIN_NOTES = (2, 3)  # notes per cycle, inclusive
SUSTAIN_NOTE_BEATS = (3, 6)  # beats each note is held, inclusive (cycle = their sum, plus any rest)
P_SUSTAIN_REST = 0.3  # chance of a one-beat rest closing the cycle
GEN_DYNAMICS = ("p", "mp")  # everything stays fairly quiet


@dataclass(frozen=True)
class Voice:
    pattern: list
    beats: int
    drift: int = 0
    dynamic: str = "p"  # level of every note; long notes swell <> up to it (see render)

    def __post_init__(self) -> None:
        if type(self.beats) is not int or self.beats < 1:
            raise ValueError(f"beats must be a positive int, got {self.beats!r}")
        if type(self.drift) is not int or self.drift < 0:
            raise ValueError(f"drift must be a non-negative int, got {self.drift!r}")
        if self.dynamic not in DYNAMICS:
            raise ValueError(f"dynamic must be one of {DYNAMICS}, got {self.dynamic!r}")
        expand(self.pattern, Fraction(1))  # validates the pattern

    @property
    def span(self) -> Fraction:
        """Cycle length in beats. drift=k runs k+1 cycles in the time of k undrifted ones."""
        if self.drift:
            return Fraction(self.beats * self.drift, self.drift + 1)
        return Fraction(self.beats)

    def code(self) -> str:
        args = [repr(self.pattern), f"beats={self.beats}"]
        if self.drift:
            args.append(f"drift={self.drift}")
        if self.dynamic != "p":
            args.append(f"dynamic={self.dynamic!r}")
        return f"voice({', '.join(args)})"


def voice(pattern: list, beats: int, drift: int = 0, dynamic: str = "p") -> Voice:
    """A pattern repeating every `beats` beats (shortened by `drift`, see Voice.span)."""
    return Voice(pattern, beats, drift, dynamic)


def _lcm(a: Fraction, b: Fraction) -> Fraction:
    return Fraction(math.lcm(a.numerator, b.numerator), math.gcd(a.denominator, b.denominator))


def piece_beats(voices) -> Fraction:
    """Beats until every voice realigns: the LCM of their cycle spans."""
    return reduce(_lcm, (v.span for v in voices))


def palette(notes: PitchSet, inst: Instrument) -> list[int]:
    """MIDI pitches this instrument chooses from: its band of the set's tones (see PARTIALS)."""
    fundamental = FUNDAMENTAL_NEAR + (notes.root + 5) % 12 - 5
    centres = [fundamental + round(12 * math.log2(p)) for p in PARTIALS]
    i = LOW_TO_HIGH.index(inst.name)
    lo = (centres[i - 1] + centres[i]) // 2 + 1 if i > 0 else centres[i] - OUTER_REACH
    hi = (centres[i] + centres[i + 1]) // 2 if i < len(centres) - 1 else centres[i] + OUTER_REACH
    low, high = min(inst.pitches), max(inst.pitches)
    while True:
        tones = [m for m in notes.pitches(lo, hi) if m in inst.pitches]
        if len(tones) >= MIN_PALETTE or (lo <= low and hi >= high):
            return tones
        lo, hi = lo - 1, hi + 1


class _Walk:
    """A melodic walk over a palette (1-based indices), shaped by an instrument's Profile."""

    def __init__(self, rng: random.Random, tones: list[int], root: int, profile: Profile):
        self.rng, self.tones, self.profile = rng, tones, profile
        self.anchored = [(t - root) % 12 in profile.anchors for t in tones]
        self.cur = self._choose(lambda j: 2.0 if self.anchored[j] else 1.0)

    def _choose(self, weight) -> int:
        idx = range(len(self.tones))
        return self.rng.choices(idx, [weight(j) for j in idx])[0] + 1

    def next(self) -> int:
        """Move from the current note by a weighted repeat / step / skip / leap."""
        cur, p = self.cur - 1, self.profile
        leaps = max(1, sum(abs(j - cur) >= 3 for j in range(len(self.tones))))

        def weight(j: int) -> float:
            d = abs(j - cur)
            w = p.moves[min(d, 3)] / (2 if d in (1, 2) else leaps if d >= 3 else 1)
            if abs(self.tones[j] - self.tones[cur]) == 12:
                w *= p.octave
            return w * (2.0 if self.anchored[j] else 1.0) + 1e-9

        self.cur = self._choose(weight)
        return self.cur

    def figure(self) -> list[int]:
        """A quick subdivided figure in the instrument's idiom, continuing the walk."""
        p, n, size = self.profile, self.rng.randint(*self.profile.figure_notes), len(self.tones)
        if p.figure == "repeat":
            return [self.cur] * n
        if p.figure == "bounce":
            notes = [self.cur, self.next()]
            self.cur = notes[0]
            return notes
        if p.figure == "pair":
            return [self.cur, self.next()]
        step = 1 if p.figure == "run" else 2  # run: scale steps; arpeggio: skips
        direction = self.rng.choice((-1, 1))
        notes = [self.cur]
        for _i in range(n - 1):
            if not 1 <= notes[-1] + direction * step <= size:
                direction = -direction
            notes.append(min(size, max(1, notes[-1] + direction * step)))
        self.cur = notes[-1]
        return notes


def _pattern(walk: _Walk) -> tuple[list, int]:
    """A moving line; returns (pattern, beats)."""
    p, rng = walk.profile, walk.rng
    slots: list = [walk.cur]
    for _i in range(rng.randint(*p.slots) - 1):
        r = rng.random()
        if r < p.hold:
            slots.append(_)
        elif r < p.hold + p.rest:
            slots.append(0)
        elif r < p.hold + p.rest + p.split:
            walk.next()
            slots.append(walk.figure())
        else:
            slots.append(walk.next())
    return slots, rng.randint(*p.beats)


def _sustain_pattern(walk: _Walk) -> tuple[list, int]:
    """A few long notes in one-beat slots; returns (pattern, beats)."""
    rng = walk.rng
    slots: list = []
    for i in range(rng.randint(*SUSTAIN_NOTES)):
        slots += [walk.next() if i else walk.cur] + [_] * (rng.randint(*SUSTAIN_NOTE_BEATS) - 1)
    if rng.random() < P_SUSTAIN_REST:
        slots.append(0)
    return slots, len(slots)


def _pick_sustainers(rng: random.Random) -> set[str]:
    """1-2 voices, weighted by each Profile.sustain."""
    pool, chosen = list(QUINTET), set()
    for _i in range(rng.randint(*SUSTAINERS)):
        name = rng.choices(pool, [PROFILES[n].sustain for n in pool])[0]
        pool.remove(name)
        chosen.add(name)
    return chosen


def generate(seed: int, notes: PitchSet, config: Config | None = None) -> dict[str, Voice]:
    """Five voices for one piece: deterministic for a seed, phasing, at most config.max_seconds long."""
    config = config or Config.current()
    rng = random.Random(seed)
    palettes = {name: palette(notes, instrument(name, config)) for name in QUINTET}
    beat_seconds = 60 / Fraction(config.tempo)
    for _attempt in range(MAX_ATTEMPTS):
        voices, drifting = {}, 0
        sustainers = _pick_sustainers(rng)
        for name in QUINTET:
            drift = 0
            if drifting < MAX_DRIFTING and rng.random() < DRIFT_CHANCE:
                drift, drifting = rng.choice(DRIFTS), drifting + 1
            walk = _Walk(rng, palettes[name], notes.root, PROFILES[name])
            pattern, beats = (_sustain_pattern if name in sustainers else _pattern)(walk)
            voices[name] = Voice(pattern, beats, drift, rng.choice(GEN_DYNAMICS))
        total = piece_beats(voices.values())
        spans = {v.span for v in voices.values()}
        if total * beat_seconds <= config.max_seconds and len(spans) >= MIN_DISTINCT_SPANS:
            return voices
    raise ValueError(f"seed {seed}: no piece fits in {config.max_seconds}s; raise --max-seconds")
