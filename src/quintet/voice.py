"""Voices: a pattern cycling over its own span, with a palette spaced by the harmonic series."""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import reduce
from itertools import combinations

from .config import Config
from .pattern import _CONTINUE, STEP, _, event_paths, expand, leaves
from .samples import DYNAMICS, QUINTET, SAMPLE_RATE, Instrument, instrument, midi_to_note, sustainable_frames
from .theory import PitchSet

__all__ = ["Voice", "voice", "piece_beats", "palette", "generate", "Profile", "PROFILES", "resolve_pitch", "parallels"]

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
    slots: tuple[int, int]  # slots per phrase cell, inclusive
    beats: tuple[int, int]  # phrase cell length in beats, inclusive (a cycle strings several cells)
    sustain: float  # relative chance of being a sustaining voice (follows how long its recordings last)
    anchors: tuple[int, ...] = ()  # semitones above the root weighted x2 (0 root, 7 fifth)
    octave: float = 1.0  # extra weight on leaping exactly an octave
    passing: float = 0.0  # chance a skip of a 3rd is filled with a passing tone
    neighbour: float = 0.0  # chance a note is decorated with a neighbour tone
    suspension: float = 0.0  # chance a sustained note starts on the step above and resolves down


PROFILES = {
    "flute": Profile(
        (10, 50, 25, 15),
        0.20,
        "run",
        (3, 4),
        0.05,
        0.10,
        (3, 6),
        (2, 8),
        2.5,
        passing=0.5,
        neighbour=0.25,
        suspension=0.15,
    ),
    "oboe": Profile(
        (15, 60, 20, 5),
        0.10,
        "pair",
        (2, 2),
        0.20,
        0.20,
        (2, 5),
        (3, 8),
        0.5,
        passing=0.45,
        neighbour=0.2,
        suspension=0.35,
    ),
    "clarinet": Profile(
        (10, 25, 45, 20),
        0.15,
        "arpeggio",
        (2, 4),
        0.10,
        0.15,
        (2, 6),
        (2, 8),
        3,
        passing=0.45,
        neighbour=0.15,
        suspension=0.3,
    ),
    "horn": Profile(
        (50, 15, 30, 5),
        0.12,
        "repeat",
        (2, 3),
        0.10,
        0.25,
        (2, 5),
        (3, 8),
        3,
        anchors=(0, 7),
        passing=0.1,
        neighbour=0.05,
        suspension=0.45,
    ),
    "bassoon": Profile(
        (25, 25, 15, 35),
        0.12,
        "bounce",
        (2, 2),
        0.15,
        0.10,
        (2, 6),
        (2, 8),
        1,
        anchors=(0,),
        octave=3.0,
        passing=0.3,
        neighbour=0.08,
        suspension=0.1,
    ),
}
REPAIR_STEPS = 60  # nudges allowed to clear a candidate of parallel 5ths/octaves
CYCLE_SECONDS = (6, 10)  # each voice's loop, at the piece's tempo (rounded to whole beats)
DRIFT_CHANCE, DRIFTS, MAX_DRIFTING = 0.2, (8, 12, 16, 24), 2  # drift is kept only if the cycle stays in range
MIN_DISTINCT_SPANS = 3  # at least this many different cycle lengths, so the voices phase
MAX_ATTEMPTS = 100_000  # cycle-length draws are cheap; patterns are only written for ones that fit
# sustaining voices: a few long notes filling the cycle
SUSTAINERS = (1, 2)  # voices per piece, inclusive
SUSTAIN_NOTES = (2, 4)  # notes per cycle, inclusive (fewer if the cycle is short)
SUSTAIN_MIN_BEATS = 3  # each sustained note is held at least this long
P_SUSTAIN_REST = 0.3  # chance of a one-beat rest closing the cycle
GEN_SOFTEST = "p"  # generated dynamics run from this up to each instrument's max_layer

# --- volume sine (LFO): each voice ebbs and flows on its own slow sine, out of step with its cycle ---
LFO_DEPTH_DB = 12.0  # quietest point, relative to the loudest
LFO_PEAK_DB = -4.0  # the loudest point, relative to the voice's level
LFO_SECONDS = (10.0, 30.0)  # preferred period; must still fit a whole number of times in the piece


@dataclass(frozen=True)
class Voice:
    pattern: list
    beats: int
    drift: int = 0
    dynamic: str = "p"  # level of every note; long notes swell <> up to it (see render)
    lfo: int = 0  # volume-sine cycles over the whole piece; 0 = steady
    lfo_phase: float = 0.0  # where the sine starts, 0-1 (0 = loudest)

    def __post_init__(self) -> None:
        if type(self.beats) is not int or self.beats < 1:
            raise ValueError(f"beats must be a positive int, got {self.beats!r}")
        if type(self.drift) is not int or self.drift < 0:
            raise ValueError(f"drift must be a non-negative int, got {self.drift!r}")
        if self.dynamic not in DYNAMICS:
            raise ValueError(f"dynamic must be one of {DYNAMICS}, got {self.dynamic!r}")
        if type(self.lfo) is not int or self.lfo < 0:
            raise ValueError(f"lfo must be a non-negative int, got {self.lfo!r}")
        if not 0 <= self.lfo_phase < 1:
            raise ValueError(f"lfo_phase must be in [0, 1), got {self.lfo_phase!r}")
        expand(self.pattern, Fraction(1))  # validates the pattern

    @property
    def span(self) -> Fraction:
        """Cycle length in beats. drift=k runs k+1 cycles in the time of k undrifted ones."""
        if self.drift:
            return Fraction(self.beats * self.drift, self.drift + 1)
        return Fraction(self.beats)

    def gain(self, position: float) -> float:
        """Volume-sine gain at a position through the piece (0-1): from LFO_PEAK_DB down by
        LFO_DEPTH_DB."""
        if not self.lfo:
            return 1.0
        dip = (1 - math.cos(2 * math.pi * (position * self.lfo + self.lfo_phase))) / 2
        return 10 ** ((LFO_PEAK_DB - LFO_DEPTH_DB * dip) / 20)

    def code(self) -> str:
        args = [repr(self.pattern), f"beats={self.beats}"]
        if self.drift:
            args.append(f"drift={self.drift}")
        if self.dynamic != "p":
            args.append(f"dynamic={self.dynamic!r}")
        if self.lfo:
            args += [f"lfo={self.lfo}", f"lfo_phase={self.lfo_phase!r}"]
        return f"voice({', '.join(args)})"


def voice(pattern: list, beats: int, drift: int = 0, dynamic: str = "p", lfo: int = 0, lfo_phase: float = 0.0) -> Voice:
    """A pattern repeating every `beats` beats (shortened by `drift`, see Voice.span), its volume
    on a slow sine with `lfo` cycles over the piece."""
    return Voice(pattern, beats, drift, dynamic, lfo, lfo_phase)


def _lcm(a: Fraction, b: Fraction) -> Fraction:
    return Fraction(math.lcm(a.numerator, b.numerator), math.gcd(a.denominator, b.denominator))


def piece_beats(voices) -> Fraction:
    """Beats until every voice realigns: the LCM of their cycle spans."""
    return reduce(_lcm, (v.span for v in voices))


# which of the set's tones each instrument plays: colour notes (9ths, 11ths, ...) stay up top
VOICING = {"bassoon": "bass", "horn": "core", "clarinet": "all", "oboe": "all", "flute": "all"}


def palette(notes: PitchSet, inst: Instrument) -> list[int]:
    """MIDI pitches this instrument chooses from: its band (see PARTIALS) of the set's tones it may
    play (see VOICING)."""
    classes = {"bass": notes.bass, "core": notes.core, "all": notes.pitch_classes}[VOICING[inst.name]]
    fundamental = FUNDAMENTAL_NEAR + (notes.root + 5) % 12 - 5
    centres = [fundamental + round(12 * math.log2(p)) for p in PARTIALS]
    i = LOW_TO_HIGH.index(inst.name)
    lo = (centres[i - 1] + centres[i]) // 2 + 1 if i > 0 else centres[i] - OUTER_REACH
    hi = (centres[i] + centres[i + 1]) // 2 if i < len(centres) - 1 else centres[i] + OUTER_REACH
    low, high = min(inst.playable), max(inst.playable)
    while True:
        tones = [m for m in notes.pitches(lo, hi, classes) if m in inst.playable]
        if len(tones) >= MIN_PALETTE or (lo <= low and hi >= high):
            return tones
        lo, hi = lo - 1, hi + 1


def resolve_pitch(index: int | str, tones: list[int], notes: PitchSet, playable=None) -> int:
    """MIDI pitch of a pattern element: palette note k (wrapping), or "k+"/"k-": the next tone of
    the chord's parent scale above/below it. A step the instrument can't play stays on the note."""
    if isinstance(index, int):
        return tones[(index - 1) % len(tones)]
    k, sign = STEP.fullmatch(index).groups()
    base = tones[(int(k) - 1) % len(tones)]
    scale = set(notes.scale.pitch_classes)
    step = 1 if sign == "+" else -1
    m = next((base + step * d for d in (1, 2) if (base + step * d) % 12 in scale), base)
    return m if playable is None or m in playable else base


class _Walk:
    """A melodic walk over a palette (1-based indices), shaped by an instrument's Profile."""

    def __init__(self, rng: random.Random, tones: list[int], notes: PitchSet, profile: Profile, playable):
        self.rng, self.tones, self.profile, self.notes, self.playable = rng, tones, profile, notes, playable
        root = notes.root
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

    def pitch(self, index: int | str) -> int:
        return resolve_pitch(index, self.tones, self.notes, self.playable)

    def non_chord_step(self, k: int, sign: str) -> str | None:
        """ "k+"/"k-" if that scale step is a playable non-chord tone, else None."""
        step = f"{k}{sign}"
        m = self.pitch(step)
        return step if m != self.pitch(k) and m % 12 not in self.notes.pitch_classes else None


def _pattern(walk: _Walk, beats: int) -> list:
    """A moving line for a cycle of `beats`: several equal phrase cells (each about the profile's
    cell length), the walk carrying on from one to the next."""
    cells = max(2, round(beats / walk.rng.randint(*walk.profile.beats)))
    return [_cell(walk, first=i == 0) for i in range(cells)]


def _cell(walk: _Walk, first: bool) -> list:
    """One phrase cell, with passing and neighbour tones on weak half-slots."""
    p, rng = walk.profile, walk.rng
    slots: list = [walk.cur if first else walk.next()]
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
            a, b = slots[-1], walk.next()
            if type(a) is int and a and 3 <= abs(walk.pitch(b) - walk.pitch(a)) <= 4 and rng.random() < p.passing:
                passing = walk.non_chord_step(a, "+" if walk.pitch(b) > walk.pitch(a) else "-")
                lo, hi = sorted((walk.pitch(a), walk.pitch(b)))
                if passing and lo < walk.pitch(passing) < hi:
                    slots[-1] = [a, passing]  # a, then the passing tone, then on by step to b
            if rng.random() < p.neighbour:
                neighbour = walk.non_chord_step(b, rng.choice("+-"))
                if neighbour:
                    slots.append([b, neighbour, b])
                    continue
            slots.append(b)
    return slots


def _sustain_pattern(walk: _Walk, beats: int) -> list:
    """A few long notes filling a cycle of `beats` one-beat slots, some as suspensions (the step
    above, held, resolving down onto the note)."""
    rng, p = walk.rng, walk.profile
    rest = int(rng.random() < P_SUSTAIN_REST and beats >= 7)  # a closing one-beat breath
    count = max(1, min(rng.randint(*SUSTAIN_NOTES), (beats - rest) // SUSTAIN_MIN_BEATS))
    # held lengths: a random split of the remaining beats into `count` parts of SUSTAIN_MIN_BEATS+
    extra = beats - rest - SUSTAIN_MIN_BEATS * count
    bars = sorted(rng.sample(range(extra + count - 1), count - 1))
    edges = [-1, *bars, extra + count - 1]
    helds = [SUSTAIN_MIN_BEATS + b - a - 1 for a, b in zip(edges, edges[1:])]
    slots: list = []
    for i, held in enumerate(helds):
        k = walk.next() if i else walk.cur
        upper = walk.non_chord_step(k, "+")
        if upper and rng.random() < p.suspension:
            first = (held + 1) // 2
            slots += [upper] + [_] * (first - 1) + [k] + [_] * (held - first - 1)
        else:
            slots += [k] + [_] * (held - 1)
    return slots + [0] * rest


def _onsets(v: Voice, pitch, total: Fraction) -> dict[Fraction, tuple[int | None, int | None, int]]:
    """{beat: (previous pitch, new pitch, event ordinal in the cycle)} for every event that starts a
    note or rest over the looping piece (pitch None = rest)."""
    one = expand(v.pattern, v.span)
    events = [
        (c * v.span + e.start, None if e.index is None else pitch(e.index), k)
        for c in range(int(total / v.span))
        for k, e in enumerate(one)
        if e.index != _CONTINUE
    ]
    return {t: (events[i - 1][1], p, k) for i, (t, p, k) in enumerate(events)}  # i-1 wraps: it loops


def parallels(voices: dict[str, Voice], notes: PitchSet, config: Config | None = None) -> list[tuple]:
    """Parallel (or contrary) perfect 5ths and octaves: both voices move at the same moment from a
    5th/octave/unison apart to the same interval again. Returns (beat, voice_a, voice_b, ordinal_a,
    ordinal_b) for each."""
    config = config or Config.current()
    total = piece_beats(voices.values())
    onsets = {}
    for name, v in voices.items():
        inst = instrument(name, config)
        tones = palette(notes, inst)
        onsets[name] = _onsets(v, lambda i, t=tones, pl=inst.playable: resolve_pitch(i, t, notes, pl), total)
    found = []
    for a, b in combinations(QUINTET, 2):
        for t in onsets[a].keys() & onsets[b].keys():
            (a0, a1, ka), (b0, b1, kb) = onsets[a][t], onsets[b][t]
            if None in (a0, a1, b0, b1) or a0 == a1 or b0 == b1:
                continue
            before, after = abs(a0 - b0) % 12, abs(a1 - b1) % 12
            if before == after and before in (0, 7):
                found.append((t, a, b, ka, kb))
    return sorted(found)


def _leaf(pattern: list, path: tuple[int, ...]):
    for i in path:
        pattern = pattern[i]
    return pattern


def _repair(
    rng: random.Random, voices: dict[str, Voice], notes: PitchSet, sizes: dict[str, int], config: Config
) -> dict[str, Voice] | None:
    """Nudge notes to neighbouring palette notes until no parallel 5ths/octaves remain (None if
    REPAIR_STEPS isn't enough)."""
    voices = {n: replace(v, pattern=copy.deepcopy(v.pattern)) for n, v in voices.items()}
    found = parallels(voices, notes, config)
    for _step in range(REPAIR_STEPS):
        if not found:
            return voices
        _t, a, b, ka, kb = found[0]
        improved = False
        for name, k in rng.sample([(a, ka), (b, kb)], 2):
            paths = event_paths(voices[name].pattern)
            leaves = [_leaf(voices[name].pattern, q) if q else None for q in paths]
            # leave non-chord tones and the notes they resolve from/to alone, so figures stay intact
            if paths[k] is None or any(type(leaves[j % len(leaves)]) is str for j in (k - 1, k, k + 1)):
                continue
            path = paths[k]
            parent = voices[name].pattern
            for i in path[:-1]:
                parent = parent[i]
            leaf = base = parent[path[-1]]
            options = [c for c in (base - 1, base + 1) if 1 <= c <= sizes[name] and c != leaf]
            for option in rng.sample(options, len(options)):
                parent[path[-1]] = option
                after = parallels(voices, notes, config)
                if len(after) < len(found):
                    found, improved = after, True
                    break
                parent[path[-1]] = leaf
            if improved:
                break
        if not improved:
            return None
    return voices if not found else None


def _max_beats(inst: Instrument, midi: int, dynamic: str, beat_seconds: Fraction) -> Fraction:
    """The longest this pitch can be held without the sample stuttering or running out."""
    sample = inst.note(midi_to_note(midi), dynamic, 1e9, max_dynamic=inst.max_layer)  # the longest
    return Fraction(sustainable_frames(round(sample.seconds * SAMPLE_RATE)), SAMPLE_RATE) / beat_seconds


def _rearticulate(v: Voice, inst: Instrument, notes: PitchSet, beat_seconds: Fraction) -> Voice:
    """Re-attack notes held longer than the instrument can sustain them: a hold that would carry a
    note past its limit sounds the note again, and a single slot that is itself too long splits
    into repeated notes."""
    pattern = copy.deepcopy(v.pattern)
    tones = palette(notes, inst)
    limit = {}

    def most(index) -> Fraction:
        m = resolve_pitch(index, tones, notes, inst.playable)
        if m not in limit:
            limit[m] = _max_beats(inst, m, v.dynamic, beat_seconds)
        return limit[m]

    current, held = None, Fraction(0)
    for path, _start, beats, leaf in leaves(pattern, v.span):
        if leaf is _ and current is not None:
            if held + beats <= most(current):
                held += beats
                continue
            leaf = current  # this hold re-attacks the note
        if leaf is _ or leaf == 0:
            current, held = None, Fraction(0)
            continue
        parts = math.ceil(beats / most(leaf))
        _set(pattern, path, leaf if parts == 1 else [leaf] * parts)
        current, held = leaf, beats / parts
    return replace(v, pattern=pattern)


def _set(pattern: list, path: tuple[int, ...], value) -> None:
    for i in path[:-1]:
        pattern = pattern[i]
    pattern[path[-1]] = value


def _pick_sustainers(rng: random.Random) -> set[str]:
    """1-2 voices, weighted by each Profile.sustain."""
    pool, chosen = list(QUINTET), set()
    for _i in range(rng.randint(*SUSTAINERS)):
        name = rng.choices(pool, [PROFILES[n].sustain for n in pool])[0]
        pool.remove(name)
        chosen.add(name)
    return chosen


def _lfo(rng: random.Random, cycles: int, piece_seconds: float) -> int:
    """Sine cycles over the piece: a period of about LFO_SECONDS that is not a whole number of the
    voice's own cycles (so each repeat of its pattern meets the sine at a different point)."""
    low, high = LFO_SECONDS
    fits = [k for k in range(1, int(piece_seconds / low) + 2) if low <= piece_seconds / k <= high]
    out_of_step = [k for k in fits if cycles % k]
    if out_of_step or fits:
        return rng.choice(out_of_step or fits)
    return max(1, round(piece_seconds / ((low + high) / 2)))


def generate(seed: int, notes: PitchSet, config: Config | None = None) -> dict[str, Voice]:
    """Five voices for one piece: deterministic for a seed, phasing, at most config.max_seconds long."""
    config = config or Config.current()
    rng = random.Random(seed)
    palettes = {name: palette(notes, instrument(name, config)) for name in QUINTET}
    beat_seconds = 60 / Fraction(config.bpm())
    low, high = math.ceil(CYCLE_SECONDS[0] / beat_seconds), math.floor(CYCLE_SECONDS[1] / beat_seconds)
    for _attempt in range(MAX_ATTEMPTS):
        # cycle lengths first (cheap): only write patterns for a set that realigns in time
        cycles, drifting = {}, 0
        for name in QUINTET:
            beats, drift = rng.randint(low, high), 0
            if drifting < MAX_DRIFTING and rng.random() < DRIFT_CHANCE:
                k = rng.choice(DRIFTS)
                if Fraction(beats * k, k + 1) >= low:
                    drift, drifting = k, drifting + 1
            cycles[name] = (beats, drift)
        spans = [Voice([1], b, d).span for b, d in cycles.values()]
        total = reduce(_lcm, spans)
        if total * beat_seconds > config.max_seconds or len(set(spans)) < MIN_DISTINCT_SPANS:
            continue
        voices = {}
        sustainers = _pick_sustainers(rng)
        for name in QUINTET:
            beats, drift = cycles[name]
            walk = _Walk(rng, palettes[name], notes, PROFILES[name], instrument(name, config).playable)
            pattern = (_sustain_pattern if name in sustainers else _pattern)(walk, beats)
            top = DYNAMICS.index(instrument(name, config).max_layer)
            voices[name] = Voice(pattern, beats, drift, rng.choice(DYNAMICS[DYNAMICS.index(GEN_SOFTEST) : top + 1]))
        voices = _repair(rng, voices, notes, {n: len(t) for n, t in palettes.items()}, config)
        if voices is None:
            continue
        voices = {n: _rearticulate(v, instrument(n, config), notes, beat_seconds) for n, v in voices.items()}
        return {
            name: replace(
                v, lfo=_lfo(rng, int(total / v.span), float(total * beat_seconds)), lfo_phase=round(rng.random(), 2) % 1
            )
            for name, v in voices.items()
        }
    raise ValueError(f"seed {seed}: no piece fits in {config.max_seconds}s; raise --max-seconds")
