"""Pitch classes, chord and scale sets, intervals and the circle of fifths."""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = [
    "PitchClass",
    "PitchSet",
    "QUALITIES",
    "HARMONY_WEIGHTS",
    "fifths",
    "fourths",
    "parse_set",
    "resolve_notes",
    "C",
    "Cs",
    "Db",
    "D",
    "Ds",
    "Eb",
    "E",
    "F",
    "Fs",
    "Gb",
    "G",
    "Gs",
    "Ab",
    "A",
    "As",
    "Bb",
    "B",
    "m2",
    "M2",
    "m3",
    "M3",
    "P4",
    "TT",
    "P5",
    "m6",
    "M6",
    "m7",
    "M7",
]

NAMES = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]

# Semitones above the root.
QUALITIES = {
    # chords
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "dom7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10),
    "dim7": (0, 3, 6, 9),
    "m7b5": (0, 3, 6, 10),
    "maj7s11": (0, 4, 6, 7, 11),
    # extended chords
    "maj9": (0, 2, 4, 7, 11),
    "maj69": (0, 2, 4, 7, 9),
    "min9": (0, 2, 3, 7, 10),
    "min11": (0, 3, 5, 7, 10),
    "sus9": (0, 2, 5, 7, 10),
    "min69": (0, 2, 3, 7, 9),
    "dom9": (0, 2, 4, 7, 10),
    "dom7s11": (0, 4, 6, 7, 10),
    # scales
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "pentatonic_major": (0, 2, 4, 7, 9),
    "pentatonic_minor": (0, 3, 5, 7, 10),
    "whole_tone": (0, 2, 4, 6, 8, 10),
    "lydian_dominant": (0, 2, 4, 6, 7, 9, 10),
}


# Core tones (root, 3rd or sus, 5th, 7th or 6th) of chords with colour notes; every other chord's
# tones are all core, and a scale's core is its triad.
CORES = {
    "maj7s11": (0, 4, 7, 11),
    "maj9": (0, 4, 7, 11),
    "maj69": (0, 4, 7, 9),
    "min9": (0, 3, 7, 10),
    "min11": (0, 3, 7, 10),
    "sus9": (0, 5, 7, 10),
    "min69": (0, 3, 7, 9),
    "dom9": (0, 4, 7, 10),
    "dom7s11": (0, 4, 7, 10),
}
SCALES = {
    "major",
    "minor",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "locrian",
    "harmonic_minor",
    "pentatonic_major",
    "pentatonic_minor",
    "whole_tone",
    "lydian_dominant",
}
# The scale whose extra steps are a chord's non-chord tones (passing tones, neighbours, suspensions).
PARENT_SCALES = {
    "maj": "major",
    "maj7": "major",
    "maj9": "major",
    "maj69": "major",
    "maj7s11": "lydian",
    "min": "dorian",
    "min7": "dorian",
    "min9": "dorian",
    "min11": "dorian",
    "min69": "dorian",
    "sus2": "mixolydian",
    "sus4": "mixolydian",
    "sus9": "mixolydian",
    "dom7": "mixolydian",
    "dom9": "mixolydian",
    "dom7s11": "lydian_dominant",
    "dim": "locrian",
    "m7b5": "locrian",
    "dim7": "harmonic_minor",
    "aug": "whole_tone",
}

# Random harmony: extended chords of 4-6 notes, weighted towards the lush and consonant.
HARMONY_WEIGHTS = {
    "maj9": 3,
    "maj69": 3,
    "min9": 3,
    "min11": 2,
    "sus9": 2,
    "maj7s11": 2,
    "min69": 1.5,
    "dom9": 1.5,
    "dom7s11": 1,
}


class PitchClass(int):
    """0-11. Chord and scale qualities are attributes: C.maj7, Fs.lydian."""

    def __new__(cls, value: int) -> PitchClass:
        return super().__new__(cls, int(value) % 12)

    def __add__(self, semitones: int) -> PitchClass:
        return PitchClass(int(self) + int(semitones))

    def __sub__(self, semitones: int) -> PitchClass:
        return PitchClass(int(self) - int(semitones))

    def __repr__(self) -> str:
        return NAMES[self]

    __str__ = __repr__

    def __getattr__(self, quality: str) -> PitchSet:
        if quality in QUALITIES:
            return PitchSet(self, quality)
        raise AttributeError(f"unknown quality {quality!r}; valid: {', '.join(QUALITIES)}")

    def up(self, interval: int) -> PitchClass:
        return self + interval

    def down(self, interval: int) -> PitchClass:
        return self - interval

    def fifths(self, n: int) -> PitchClass:
        """Move n steps clockwise round the circle of fifths (negative = anticlockwise)."""
        return self + 7 * n

    def fourths(self, n: int) -> PitchClass:
        return self.fifths(-n)


@dataclass(frozen=True)
class PitchSet:
    root: PitchClass
    quality: str

    def __post_init__(self) -> None:
        if self.quality not in QUALITIES:
            raise AttributeError(f"unknown quality {self.quality!r}; valid: {', '.join(QUALITIES)}")

    def __repr__(self) -> str:
        return f"{self.root!r}.{self.quality}"

    @property
    def intervals(self) -> tuple[int, ...]:
        return QUALITIES[self.quality]

    @property
    def pitch_classes(self) -> list[PitchClass]:
        return [self.root + i for i in self.intervals]

    def up(self, interval: int) -> PitchSet:
        return PitchSet(self.root + interval, self.quality)

    def down(self, interval: int) -> PitchSet:
        return PitchSet(self.root - interval, self.quality)

    def fifths(self, n: int) -> PitchSet:
        return PitchSet(self.root.fifths(n), self.quality)

    def fourths(self, n: int) -> PitchSet:
        return self.fifths(-n)

    @property
    def core(self) -> list[PitchClass]:
        """Root, 3rd (or sus), 5th and 7th/6th: the tones without colour notes (9ths, 11ths, ...)."""
        if self.quality in CORES:
            return [self.root + i for i in CORES[self.quality]]
        if self.quality in SCALES:
            third = 4 if 4 in self.intervals else 3
            fifth = next((i for i in (7, 6, 8) if i in self.intervals), 7)
            return [self.root + i for i in (0, third, fifth) if i in self.intervals]
        return self.pitch_classes

    @property
    def scale(self) -> PitchSet:
        """The parent scale that supplies non-chord tones (a scale is its own)."""
        if self.quality in SCALES:
            return self
        return PitchSet(self.root, PARENT_SCALES[self.quality])

    @property
    def bass(self) -> list[PitchClass]:
        """Root and 5th (or the diminished/augmented 5th the set has instead)."""
        fifth = next((i for i in (7, 6, 8) if i in self.intervals), None)
        return [self.root] if fifth is None else [self.root, self.root + fifth]

    def pitches(self, low: int, high: int, classes=None) -> list[int]:
        """MIDI numbers of the set's tones (or just `classes`) in [low, high], ascending."""
        classes = set(self.pitch_classes if classes is None else classes)
        return [m for m in range(low, high + 1) if m % 12 in classes]


def fifths(start: PitchClass | PitchSet, n: int) -> list:
    """fifths(C, 4) == [C, G, D, A]."""
    return [start.fifths(i) for i in range(n)]


def fourths(start: PitchClass | PitchSet, n: int) -> list:
    """fourths(C.dom7, 3) == [C.dom7, F.dom7, Bb.dom7]."""
    return [start.fourths(i) for i in range(n)]


C = PitchClass(0)
Cs = Db = PitchClass(1)
D = PitchClass(2)
Ds = Eb = PitchClass(3)
E = PitchClass(4)
F = PitchClass(5)
Fs = Gb = PitchClass(6)
G = PitchClass(7)
Gs = Ab = PitchClass(8)
A = PitchClass(9)
As = Bb = PitchClass(10)
B = PitchClass(11)

m2, M2, m3, M3, P4, TT, P5, m6, M6, m7, M7 = range(1, 12)

_ROOTS = {
    name: globals()[name]
    for name in ("C", "Cs", "Db", "D", "Ds", "Eb", "E", "F", "Fs", "Gb", "G", "Gs", "Ab", "A", "As", "Bb", "B")
}


def resolve_notes(spec: str, seed: int) -> PitchSet:
    """The note set for a seed. spec is 'random' (random key and chord), '<root>.random' (random
    chord on that root) or '<root>.<quality>'. The harmony has its own random stream per seed, so
    fixing the tempo (or anything else) doesn't change which chord a seed gets."""
    if spec == "random":
        spec = "_.random"
    root, _, quality = spec.partition(".")
    if quality != "random":
        return parse_set(spec)
    rng = random.Random(f"{seed}:harmony")
    pc = PitchClass(rng.randrange(12)) if root == "_" else parse_set(f"{root}.maj").root
    return PitchSet(pc, rng.choices(list(HARMONY_WEIGHTS), list(HARMONY_WEIGHTS.values()))[0])


def parse_set(text: str) -> PitchSet:
    """'C.maj7s11' -> C.maj7s11."""
    root, _, quality = text.partition(".")
    if root not in _ROOTS:
        raise ValueError(f"unknown root {root!r} in {text!r}; valid: {', '.join(_ROOTS)}")
    if quality not in QUALITIES:
        raise ValueError(f"unknown quality {quality!r} in {text!r}; valid: {', '.join(QUALITIES)}")
    return PitchSet(_ROOTS[root], quality)
