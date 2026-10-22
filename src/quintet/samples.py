"""The sample library: one Instrument per quintet member, indexing its WAV files."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile

from .config import Config

QUINTET = ("flute", "oboe", "clarinet", "horn", "bassoon")
SAMPLE_RATE = 44100  # every sample in the library is 44.1 kHz, 16-bit, mono
DYNAMICS = ["pp", "p", "mp", "mf", "f", "ff"]  # softest to loudest
# loudest recorded dynamic each instrument plays (louder levels come from gain); everyone stays at mp
# so the quintet blends rather than turning bright or brassy
MAX_LAYERS = {"flute": "mp", "oboe": "mp", "clarinet": "mp", "bassoon": "mp", "horn": "mp"}
# instruments whose pitches with nothing recorded at or below max_layer borrow the nearest louder
# layer (levelled to the dynamic played) rather than going unplayed: the oboe's p layer skips
# C5-Ds5 and the horn's Cs5-F5, both inside their sweet ranges
GAP_FILL = frozenset({"oboe", "horn"})
NOTE_NAMES = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]
# Nominal seconds for each recorded length; used to pick a sample for a duration.
LENGTH_SECONDS = {"0.25s": 0.25, "0.5s": 0.5, "1s": 1.0, "1.5s": 1.5, "long": 3.0, "very-long": 15.0, "phrase": 0.0}

# sustaining a note longer than its recording: keep the attack, loop the steady middle with
# crossfades, end on the recording's own release; only when the loop is long enough not to stutter
ATTACK_SECONDS = 0.3  # (or the first quarter of the recording) kept as-is at the start
RELEASE_SECONDS = 0.6  # (or the last 35%) played at the end as the note's natural release
CROSSFADE_SECONDS = 0.1  # equal-power crossfade at each loop seam
MIN_LOOP_SECONDS = 0.8
MAX_LOOP_REPEATS = 3


def loop_bounds(length: int) -> tuple[int, int]:
    """(attack end, release start) of a recording `length` frames long: the middle a sustain loops."""
    attack = min(length // 4, round(ATTACK_SECONDS * SAMPLE_RATE))
    return attack, length - min(round(length * 0.35), round(RELEASE_SECONDS * SAMPLE_RATE))


def sustainable_frames(length: int) -> int:
    """The longest note a recording of `length` frames can play without stuttering: itself, plus
    MAX_LOOP_REPEATS of its steady middle if that is long enough to loop."""
    attack, release_at = loop_bounds(length)
    loop = release_at - attack
    if loop < MIN_LOOP_SECONDS * SAMPLE_RATE:
        return length
    step = loop - min(round(CROSSFADE_SECONDS * SAMPLE_RATE), loop // 3)  # each repeat adds this much
    return length + MAX_LOOP_REPEATS * step


def loopable(length: int, n: int) -> bool:
    """Whether a recording of `length` frames can stretch to n frames by looping."""
    most = sustainable_frames(length)
    return most > length and n <= most


def note_to_midi(note: str) -> int:
    """'C4' -> 60, 'As1' -> 34."""
    return NOTE_NAMES.index(note[:-1]) + (int(note[-1]) + 1) * 12


def midi_to_note(midi: int) -> str:
    """60 -> 'C4'."""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


@dataclass(frozen=True)
class Sample:
    path: Path
    instrument: str
    note: str
    dynamic: str  # one of DYNAMICS, or e.g. "cresc-decresc" for extended samples
    length: str  # "0.25s", "0.5s", "1s", "1.5s", "long", "very-long", "phrase"
    technique: str | None = None  # None for plain notes

    @property
    def midi(self) -> int:
        return note_to_midi(self.note)

    @property
    def seconds(self) -> float:
        """Actual duration, read from the file header (the length in the name is only nominal)."""
        return _frames(self.path) / SAMPLE_RATE

    def load(self) -> np.ndarray:
        """Mono float32 audio in [-1, 1]. Cached and read-only."""
        return _read(self.path)

    @classmethod
    def from_path(cls, path: Path) -> Sample:
        # notes/<dyn>/<inst>_<note>_<dyn>_<len>.wav
        # extended/<tech>/<inst>_<note>_<tech>_<dyn>_<len>.wav
        parts = path.stem.split("_")
        if path.parent.parent.name == "notes":
            inst, note, dyn, length = parts
            return cls(path, inst, note, dyn, length)
        inst, note, tech, dyn, length = parts
        return cls(path, inst, note, dyn, length, tech)


class Instrument:
    """Index of one instrument's samples under <sample_root>/<name>/."""

    def __init__(self, name: str, config: Config | None = None):
        self.config = config or Config.current()
        self.name = name
        self.root = self.config.sample_root / name
        if not self.config.sample_root.is_dir():
            raise FileNotFoundError(f"no sample library at {self.config.sample_root}; point --sample-root at it")
        if not self.root.is_dir():
            available = sorted(p.name for p in self.config.sample_root.iterdir() if p.is_dir())
            raise FileNotFoundError(f"no instrument {name!r} in {self.config.sample_root}; available: {available}")
        self.samples = [Sample.from_path(p) for p in sorted(self.root.glob("*/*/*.wav"))]
        self.notes = [s for s in self.samples if s.technique is None]
        self.extended = [s for s in self.samples if s.technique is not None]
        self.pitches = frozenset(s.midi for s in self.notes)  # MIDI numbers with plain-note samples
        self.max_layer = MAX_LAYERS.get(name, "ff")
        soft = DYNAMICS[: DYNAMICS.index(self.max_layer) + 1]
        soft_pitches = frozenset(s.midi for s in self.notes if s.dynamic in soft)  # ... at or below max_layer
        self.gap_filled = self.pitches - soft_pitches if name in GAP_FILL else frozenset()  # ... borrowed louder
        self.playable = soft_pitches | self.gap_filled

    def __repr__(self) -> str:
        return f"Instrument({self.name!r}, {len(self.notes)} notes, {len(self.extended)} extended)"

    @property
    def dynamics(self) -> list[str]:
        present = {s.dynamic for s in self.notes}
        return [d for d in DYNAMICS if d in present]

    @property
    def techniques(self) -> list[str]:
        return sorted({s.technique for s in self.extended})

    @property
    def range(self) -> tuple[str, str]:
        return midi_to_note(min(self.pitches)), midi_to_note(max(self.pitches))

    def find(
        self,
        note: str | None = None,
        dynamic: str | None = None,
        length: str | None = None,
        technique: str | None = None,
    ) -> list[Sample]:
        """Plain-note samples by default; pass technique= to search extended samples."""
        pool = self.extended if technique else self.notes
        return [
            s
            for s in pool
            if (note is None or s.note == note)
            and (dynamic is None or s.dynamic == dynamic)
            and (length is None or s.length == length)
            and (technique is None or s.technique == technique)
        ]

    def note(self, note: str, dynamic: str = "mf", length: str | float = "1s", max_dynamic: str = "ff") -> Sample:
        """One plain note, falling back to the nearest recorded dynamic no louder than max_dynamic.
        A GAP_FILL instrument with nothing that soft for the note takes its nearest louder layer.

        length is a recorded length ("0.25s", "long", ...) or a duration in seconds.
        - A recorded length picks that recording at the nearest dynamic (else falls back as below,
          using its nominal seconds).
        - A duration picks, at the nearest dynamic, the shortest recording whose actual length
          covers it. If no allowed dynamic has one that long, it takes the actually-longest
          recording, preferring nearer dynamics, so long notes need as little sustaining as possible.
        """
        target = min(DYNAMICS.index(dynamic), DYNAMICS.index(max_dynamic))
        allowed = DYNAMICS[: DYNAMICS.index(max_dynamic) + 1]
        nearest = sorted(allowed, key=lambda d: (abs(DYNAMICS.index(d) - target), -DYNAMICS.index(d)))
        by_dynamic = [(d, self.find(note, d)) for d in nearest]
        by_dynamic = [(d, matches) for d, matches in by_dynamic if matches]
        if not by_dynamic and self.name in GAP_FILL:
            louder = DYNAMICS[DYNAMICS.index(max_dynamic) + 1 :]
            by_dynamic = [(d, matches) for d in louder if (matches := self.find(note, d))][:1]
        if not by_dynamic:
            raise KeyError(f"{self.name} has no sample for {note}")
        if isinstance(length, str):
            exact = [s for s in by_dynamic[0][1] if s.length == length]
            if exact:
                return exact[0]
        seconds = LENGTH_SECONDS[length] if isinstance(length, str) else length
        for _d, matches in by_dynamic:
            covering = sorted((s for s in matches if s.seconds >= seconds), key=lambda s: s.seconds)
            if covering:
                return covering[0]
        rank = {d: i for i, (d, _m) in enumerate(by_dynamic)}
        return max((s for _d, matches in by_dynamic for s in matches), key=lambda s: (s.seconds, -rank[s.dynamic]))

    def takes(self, note: str, dynamic: str, seconds: float, max_dynamic: str = "ff") -> list[Sample]:
        """Every recording that would do for this note, so repeats can rotate between performances:
        note()'s pick plus any other recording of the same pitch and dynamic that is at least as able
        to cover `seconds`. Always starts with note()'s pick; the rest are in a fixed order."""
        best = self.note(note, dynamic, seconds, max_dynamic=max_dynamic)
        enough = min(seconds, best.seconds)
        others = sorted(
            (s for s in self.find(note, best.dynamic) if s is not best and s.seconds >= enough),
            key=lambda s: s.path.name,
        )
        return [best, *others]


_instruments: dict[tuple[Path, str], Instrument] = {}


def instrument(name: str, config: Config | None = None) -> Instrument:
    """Cached Instrument for the current (or given) config's sample root."""
    config = config or Config.current()
    key = (config.sample_root, name)
    if key not in _instruments:
        _instruments[key] = Instrument(name, config)
    return _instruments[key]


@cache
def _frames(path: Path) -> int:
    with AudioFile(str(path)) as f:
        return f.frames


@cache
def _read(path: Path) -> np.ndarray:
    with AudioFile(str(path)) as f:
        if (f.samplerate, f.num_channels) != (SAMPLE_RATE, 1):
            raise ValueError(f"{path}: expected {SAMPLE_RATE} Hz mono")
        audio = f.read(f.frames)[0]
    audio.flags.writeable = False
    return audio
