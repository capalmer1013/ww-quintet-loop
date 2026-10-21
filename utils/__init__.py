"""Woodwind quintet phasing pieces: `from utils import *` gives everything a piece file needs."""
from .config import Config
from .pattern import _, Event, expand, tile
from .render import hairpin, leveled, loopable, loudness_db, mix, piece_code, render, seconds, sustain, voice_line, write_wav
from .master import eq, loudness_lufs, master
from .reverb import decay_seconds, reverb
from .samples import DYNAMICS, QUINTET, SAMPLE_RATE, Instrument, Sample, instrument, midi_to_note, note_to_midi
from .theory import *  # noqa: F403  (pitch classes C..B, intervals, PitchSet, fifths, fourths, parse_set)
from .theory import __all__ as _theory_all
from .voice import PROFILES, Profile, Voice, generate, palette, parallels, piece_beats, resolve_pitch, voice

__all__ = [
    "Config", "_", "Event", "hairpin", "leveled", "loopable", "loudness_db", "PROFILES", "Profile", "expand", "tile", "mix", "piece_code", "render", "seconds", "sustain", "voice_line",
    "write_wav", "reverb", "decay_seconds", "master", "eq", "loudness_lufs", "DYNAMICS", "QUINTET", "SAMPLE_RATE", "Instrument", "Sample", "instrument",
    "midi_to_note", "note_to_midi", "Voice", "generate", "palette", "parallels", "piece_beats", "resolve_pitch",
    "voice",
    *_theory_all,
]
