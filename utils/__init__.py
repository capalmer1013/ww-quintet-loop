"""Woodwind quintet phasing pieces: `from utils import *` gives everything a piece file needs."""
from .config import Config
from .pattern import _, Event, expand, tile
from .render import hairpin, leveled, loudness_db, mix, piece_code, render, seconds, sustain, voice_line, write_wav
from .samples import DYNAMICS, QUINTET, SAMPLE_RATE, Instrument, Sample, instrument, midi_to_note, note_to_midi
from .theory import *  # noqa: F403  (pitch classes C..B, intervals, PitchSet, fifths, fourths, parse_set)
from .theory import __all__ as _theory_all
from .voice import PROFILES, Profile, Voice, generate, palette, piece_beats, voice

__all__ = [
    "Config", "_", "Event", "hairpin", "leveled", "loudness_db", "PROFILES", "Profile", "expand", "tile", "mix", "piece_code", "render", "seconds", "sustain", "voice_line",
    "write_wav", "DYNAMICS", "QUINTET", "SAMPLE_RATE", "Instrument", "Sample", "instrument",
    "midi_to_note", "note_to_midi", "Voice", "generate", "palette", "piece_beats", "voice",
    *_theory_all,
]
