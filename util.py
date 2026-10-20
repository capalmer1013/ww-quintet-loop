"""Sample loading and sound-manipulation helpers for the woodwind quintet loop generator."""
from __future__ import annotations

import argparse
import sys
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path
from typing import ClassVar

DEFAULT_SAMPLE_ROOT = Path(__file__).resolve().parent / "samples"

DYNAMICS = ["pp", "p", "mp", "mf", "f", "ff"]  # softest to loudest
NOTE_NAMES = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]


@dataclass
class Config:
    """Run-wide settings.

    Precedence, lowest to highest: field defaults < values passed to Config(...) < command line.
    Every field is exposed as a --kebab-case flag automatically; add a field to add a flag.
    The most recently created Config becomes the current one, used by Instrument() when no
    config is passed. Pass argv=[] to ignore the command line (e.g. in tests).
    """

    sample_root: Path = field(default=DEFAULT_SAMPLE_ROOT, metadata={"help": "directory of instrument sample folders"})

    argv: InitVar[list[str] | None] = None

    _current: ClassVar[Config | None] = None

    def __post_init__(self, argv: list[str] | None) -> None:
        self._apply_cli(sys.argv[1:] if argv is None else argv)
        self.sample_root = Path(self.sample_root).expanduser()
        Config._current = self

    def _apply_cli(self, argv: list[str]) -> None:
        parser = argparse.ArgumentParser()
        for f in fields(self):
            current = getattr(self, f.name)
            kwargs = {"dest": f.name, "default": argparse.SUPPRESS, "help": f.metadata.get("help")}
            if isinstance(current, bool):
                kwargs["action"] = argparse.BooleanOptionalAction
            else:
                kwargs["type"] = type(current)
            parser.add_argument("--" + f.name.replace("_", "-"), **kwargs)
        overrides, _ = parser.parse_known_args(argv)
        for name, value in vars(overrides).items():
            setattr(self, name, value)

    @classmethod
    def current(cls) -> Config:
        """The active config, creating a default one (which still reads the CLI) if none exists."""
        return cls._current or cls()

    def instruments(self) -> list[str]:
        return sorted(p.name for p in self.sample_root.iterdir() if p.is_dir())

    def Instrument(self, name: str) -> Instrument:
        return Instrument(name, config=self)


def note_to_midi(note: str) -> int:
    """'C4' -> 60, 'As1' -> 34."""
    return NOTE_NAMES.index(note[:-1]) + (int(note[-1]) + 1) * 12


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
            raise FileNotFoundError(
                f"no instrument {name!r} in {self.config.sample_root}; available: {self.config.instruments()}"
            )
        self.samples = [Sample.from_path(p) for p in sorted(self.root.glob("*/*/*.wav"))]
        self.notes = [s for s in self.samples if s.technique is None]
        self.extended = [s for s in self.samples if s.technique is not None]

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
        ordered = sorted(self.notes, key=lambda s: s.midi)
        return ordered[0].note, ordered[-1].note

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

    def note(self, note: str, dynamic: str = "mf", length: str = "1s") -> Sample:
        """One plain note, falling back to the nearest recorded dynamic, then any length."""
        target = DYNAMICS.index(dynamic)
        for dyn in sorted(DYNAMICS, key=lambda d: (abs(DYNAMICS.index(d) - target), -DYNAMICS.index(d))):
            matches = self.find(note, dyn, length) or self.find(note, dyn)
            if matches:
                return matches[0]
        raise KeyError(f"{self.name} has no sample for {note}")
