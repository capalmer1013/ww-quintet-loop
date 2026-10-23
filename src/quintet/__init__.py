"""Woodwind quintet phasing pieces: `from quintet import *` gives everything a piece file needs."""

from .config import Config
from .effects import finish, loudness_lufs, master, reverb
from .pattern import Event, _, accents, expand, tile
from .render import (
    hairpin,
    leveled,
    lfo_curve,
    loudness_db,
    mix,
    piece_code,
    render,
    seconds,
    sustain,
    voice_line,
    write_wav,
)
from .samples import (
    DYNAMICS,
    QUINTET,
    SAMPLE_RATE,
    Instrument,
    Sample,
    instrument,
    loopable,
    midi_to_note,
    note_to_midi,
    sustainable_frames,
)
from .theory import *  # noqa: F403  (pitch classes C..B, intervals, PitchSet, fifths, fourths, parse_set, ...)
from .theory import __all__ as _theory_all
from .voice import (
    PROFILES,
    Profile,
    Voice,
    clashes,
    generate,
    palette,
    parallels,
    piece_beats,
    resolve_pitch,
    too_close,
    voice,
)

__all__ = [
    # settings
    "Config",
    # mixing and mastering
    "finish",
    "loudness_lufs",
    "master",
    "reverb",
    # rhythm patterns
    "Event",
    "_",
    "accents",
    "expand",
    "tile",
    # rendering
    "hairpin",
    "leveled",
    "lfo_curve",
    "loudness_db",
    "mix",
    "piece_code",
    "render",
    "seconds",
    "sustain",
    "voice_line",
    "write_wav",
    # instruments and samples
    "DYNAMICS",
    "QUINTET",
    "SAMPLE_RATE",
    "Instrument",
    "Sample",
    "instrument",
    "loopable",
    "midi_to_note",
    "note_to_midi",
    "sustainable_frames",
    # voices and generation
    "PROFILES",
    "Profile",
    "Voice",
    "clashes",
    "generate",
    "palette",
    "parallels",
    "piece_beats",
    "resolve_pitch",
    "too_close",
    "voice",
    # pitch theory
    *_theory_all,
]
