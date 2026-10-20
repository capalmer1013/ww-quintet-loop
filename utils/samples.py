"""The sample library: one Instrument per quintet member, indexing its WAV files."""
from __future__ import annotations

import wave
from array import array
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import Config

QUINTET = ("flute", "oboe", "clarinet", "horn", "bassoon")
SAMPLE_RATE = 44100  # every sample in the library is 44.1 kHz, 16-bit, mono
DYNAMICS = ["pp", "p", "mp", "mf", "f", "ff"]  # softest to loudest
# loudest recorded dynamic each instrument plays (louder levels come from gain); the horn stays soft
# so it blends rather than turning brassy
MAX_LAYERS = {"flute": "mf", "oboe": "mf", "clarinet": "mf", "bassoon": "mf", "horn": "mp"}
NOTE_NAMES = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]
# Nominal seconds for each recorded length; used to pick a sample for a duration.
LENGTH_SECONDS = {"0.25s": 0.25, "0.5s": 0.5, "1s": 1.0, "1.5s": 1.5, "long": 3.0, "very-long": 15.0, "phrase": 0.0}


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

    def load(self) -> array:
        """16-bit mono frames as array('h'). Cached; do not modify the result in place."""
        return _read_wav(self.path)

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
        if not self.root.is_dir():
            available = sorted(p.name for p in self.config.sample_root.iterdir() if p.is_dir())
            raise FileNotFoundError(f"no instrument {name!r} in {self.config.sample_root}; available: {available}")
        self.samples = [Sample.from_path(p) for p in sorted(self.root.glob("*/*/*.wav"))]
        self.notes = [s for s in self.samples if s.technique is None]
        self.extended = [s for s in self.samples if s.technique is not None]
        self.pitches = frozenset(s.midi for s in self.notes)  # MIDI numbers with plain-note samples
        self.max_layer = MAX_LAYERS.get(name, "ff")
        soft = DYNAMICS[:DYNAMICS.index(self.max_layer) + 1]
        self.playable = frozenset(s.midi for s in self.notes if s.dynamic in soft)  # ... at or below max_layer

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

    def find(self, note: str | None = None, dynamic: str | None = None,
             length: str | None = None, technique: str | None = None) -> list[Sample]:
        """Plain-note samples by default; pass technique= to search extended samples."""
        pool = self.extended if technique else self.notes
        return [
            s for s in pool
            if (note is None or s.note == note)
            and (dynamic is None or s.dynamic == dynamic)
            and (length is None or s.length == length)
            and (technique is None or s.technique == technique)
        ]

    def note(self, note: str, dynamic: str = "mf", length: str | float = "1s", max_dynamic: str = "ff") -> Sample:
        """One plain note, falling back to the nearest recorded dynamic no louder than max_dynamic.

        length is a recorded length ("0.25s", "long", ...) or a duration in seconds. A duration, or
        a recorded length this note lacks, picks the shortest recorded length that covers it
        (else the longest available).
        """
        target = min(DYNAMICS.index(dynamic), DYNAMICS.index(max_dynamic))
        allowed = DYNAMICS[:DYNAMICS.index(max_dynamic) + 1]
        seconds = LENGTH_SECONDS[length] if isinstance(length, str) else length
        for dyn in sorted(allowed, key=lambda d: (abs(DYNAMICS.index(d) - target), -DYNAMICS.index(d))):
            matches = self.find(note, dyn)
            if not matches:
                continue
            exact = [s for s in matches if s.length == length]
            if exact:
                return exact[0]
            by_length = sorted(matches, key=lambda s: LENGTH_SECONDS[s.length])
            return next((s for s in by_length if LENGTH_SECONDS[s.length] >= seconds), by_length[-1])
        raise KeyError(f"{self.name} has no sample for {note}")


_instruments: dict[tuple[Path, str], Instrument] = {}


def instrument(name: str, config: Config | None = None) -> Instrument:
    """Cached Instrument for the current (or given) config's sample root."""
    config = config or Config.current()
    key = (config.sample_root, name)
    if key not in _instruments:
        _instruments[key] = Instrument(name, config)
    return _instruments[key]


@lru_cache(maxsize=None)
def _read_wav(path: Path) -> array:
    with wave.open(str(path)) as w:
        if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (SAMPLE_RATE, 2, 1):
            raise ValueError(f"{path}: expected {SAMPLE_RATE} Hz 16-bit mono")
        frames = array("h", w.readframes(w.getnframes()))
    return frames
