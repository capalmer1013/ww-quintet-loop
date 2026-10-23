"""Generation is pinned: 20 seeds must still give the recorded tempo, notes and voices, note for
note, so an accidental change to the music fails here. After a deliberate change, re-record the
fixture with `make fixtures`."""

import json
from pathlib import Path

import pytest

from quintet import QUINTET, Config, piece_for_seed

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "generation.json").read_text())


@pytest.mark.parametrize("piece", RECORDED, ids=lambda p: f"seed{p['seed']}")
def test_generation_matches_the_recording(piece):
    config = Config(argv=[], tempo=0)
    notes, voices = piece_for_seed(piece["seed"], config)
    assert config.tempo == piece["tempo"]
    assert repr(notes) == piece["notes"]
    assert {n: voices[n].code() for n in QUINTET} == piece["voices"]
