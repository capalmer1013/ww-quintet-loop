"""Run-wide settings: code defaults overridden by command-line flags."""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path
from typing import ClassVar

DEFAULT_SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "samples"  # the repository's samples/
TEMPO_RANGE = (50, 70)  # bpm, inclusive, when the tempo is random per seed


@dataclass
class Config:
    """Precedence, lowest to highest: field defaults < values passed to Config(...) < command line.

    Every field is exposed as a --kebab-case flag automatically; add a field to add a flag.
    The most recently created Config becomes the current one. Pass argv=[] to ignore the CLI.
    """

    sample_root: Path = field(default=DEFAULT_SAMPLE_ROOT, metadata={"help": "directory of instrument sample folders"})
    tempo: float = field(default=0.0, metadata={"help": "beats per minute; 0 = random 50-70 per seed"})
    notes: str = field(
        default="random",
        metadata={"help": "note set: random (key and chord), C.random (chord), or e.g. C.maj9, Fs.maj7s11, Bb.lydian"},
    )
    seeds: str = field(default="0", metadata={"help": "seed or range A-B (B exclusive); one piece per seed"})
    reverb: float = field(default=0.3, metadata={"help": "hall reverb amount (0 = dry)"})
    room: float = field(default=0.8, metadata={"help": "hall size, 0-1 (0.8 is about a 2.6 s decay)"})
    master: bool = field(
        default=True, metadata={"help": "EQ, compress and loudness-normalise the mix for small speakers"}
    )
    max_seconds: float = field(default=360.0, metadata={"help": "longest allowed piece (one full phase cycle)"})
    output_dir: Path = field(default=Path("out"), metadata={"help": "where pieces are written"})
    stems: bool = field(default=False, metadata={"help": "also write one mono WAV per instrument"})
    code: bool = field(default=False, metadata={"help": "also write a .py file that reproduces each piece"})

    argv: InitVar[list[str] | None] = None

    _current: ClassVar[Config | None] = None

    def __post_init__(self, argv: list[str] | None) -> None:
        self._apply_cli(sys.argv[1:] if argv is None else argv)
        self.sample_root = Path(self.sample_root).expanduser()
        self.output_dir = Path(self.output_dir).expanduser()
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

    def bpm(self) -> float:
        """The tempo to render at; raises if it is still 0 (random), which main.py resolves per seed."""
        if not self.tempo:
            raise ValueError("tempo 0 means random per seed: use piece_tempo(seed), or set Config(tempo=...)")
        return self.tempo

    def piece_tempo(self, seed: int) -> float:
        """This config's tempo, or for tempo 0 a whole-number tempo in TEMPO_RANGE drawn from the
        seed's own tempo stream (so the seed's lines and harmony are unaffected)."""
        return self.tempo or float(random.Random(f"{seed}:tempo").randint(*TEMPO_RANGE))

    def seed_range(self) -> range:
        """'1000' -> range(1000, 1001); '1000-1100' -> range(1000, 1100)."""
        start, sep, end = self.seeds.partition("-")
        try:
            return range(int(start), int(end) if sep else int(start) + 1)
        except ValueError:
            raise ValueError(f"--seeds must be A or A-B, got {self.seeds!r}") from None
