"""Run-wide settings: code defaults overridden by command-line flags."""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path
from typing import ClassVar

DEFAULT_SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "samples"  # the repository's samples/
TEMPO_RANGE = (55, 75)  # bpm, inclusive, when the tempo is random per seed
TIME_SEEDS_PER_SECOND = 100  # --seeds now: the Unix time in hundredths of a second
PIECE_NAME = "piece_{seed}"


@dataclass
class Config:
    """Precedence, lowest to highest: field defaults < values passed to Config(...) < command line.

    Every field is exposed as a --kebab-case flag automatically; add a field to add a flag.
    The most recently created Config becomes the current one. Pass argv=[] to ignore the CLI.
    """

    sample_root: Path = field(default=DEFAULT_SAMPLE_ROOT, metadata={"help": "directory of instrument sample folders"})
    tempo: float = field(default=0.0, metadata={"help": "beats per minute; 0 = random 55-75 per seed"})
    notes: str = field(
        default="random",
        metadata={
            "help": "note set: random (key and mode), C.random (a mode on C), or e.g. C.lydian, C.maj9, Fs.maj7s11"
        },
    )
    seeds: str = field(
        default="now",
        metadata={"help": "seed, range A-B (B exclusive), or now (one piece seeded from the time); one piece per seed"},
    )
    reverb: float = field(default=0.5, metadata={"help": "hall reverb amount (0 = dry)"})
    room: float = field(default=0.8, metadata={"help": "hall size, 0-1 (0.8 is about a 2.6 s decay)"})
    reverb_ir: str = field(
        default="", metadata={"help": "impulse response WAV of a real space, used instead of the built-in hall"}
    )
    master: bool = field(
        default=True, metadata={"help": "EQ, compress and loudness-normalise the mix for small speakers"}
    )
    saturation: float = field(default=0.3, metadata={"help": "gentle tape-style warmth when mastering (0 = clean)"})
    humanize: bool = field(
        default=True, metadata={"help": "play it like people: timing, breaths, varied takes and levels"}
    )
    intonation: bool = field(
        default=True, metadata={"help": "let each note's tuning drift a few cents, differently each time"}
    )
    a4: float = field(
        default=440.0, metadata={"help": "concert pitch in Hz; the samples are at 440, 432 is about 32 cents flat"}
    )
    count: int = field(default=1, metadata={"help": "with --seeds now: how many new pieces to make"})
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

    def seed_range(self) -> Iterable[int]:
        """'1000' -> range(1000, 1001); '1000-1100' -> range(1000, 1100); 'now' -> `count` seeds from the
        clock, each claimed only when it is reached (so a run stopped early leaves no unused claims)."""
        if self.seeds == "now":
            return self._claimed_seeds()
        if self.count != 1:
            raise ValueError("--count only applies to --seeds now; give a range (--seeds A-B) instead")
        start, sep, end = self.seeds.partition("-")
        try:
            return range(int(start), int(end) if sep else int(start) + 1)
        except ValueError:
            raise ValueError(f"--seeds must be A, A-B or now, got {self.seeds!r}") from None

    def _claimed_seeds(self) -> Iterator[int]:
        if self.count < 1:
            raise ValueError(f"--count must be at least 1, got {self.count}")
        seed = self.claim_time_seed()
        yield seed
        for _ in range(self.count - 1):
            seed = self.claim_time_seed(after=seed)
            yield seed

    def claim_time_seed(self, after: int | None = None) -> int:
        """The current Unix time in hundredths of a second (or the first seed after `after`), as a
        seed. The seed is claimed by creating its output file exclusively, so runs started in the same
        instant (say, in parallel from a script) each move on to the next free seed instead of sharing one."""
        seed = time.time_ns() // (10**9 // TIME_SEEDS_PER_SECOND) if after is None else after + 1
        self.output_dir.mkdir(parents=True, exist_ok=True)
        while True:
            path = self.output_dir / f"{PIECE_NAME.format(seed=seed)}.wav"
            try:
                os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return seed
            except FileExistsError:
                seed += 1
