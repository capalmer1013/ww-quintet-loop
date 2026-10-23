"""Record what 20 seeds generate, for tests/test_generation_parity.py.

Run this (make fixtures) only when generation is changed on purpose; the test exists to catch
changes that weren't.
"""

import json
from pathlib import Path

from quintet import QUINTET, Config, piece_for_seed

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "generation.json"
SEEDS = range(20)


def main() -> None:
    pieces = []
    for seed in SEEDS:
        config = Config(argv=[], tempo=0)
        notes, voices = piece_for_seed(seed, config)
        pieces.append(
            {
                "seed": seed,
                "notes": repr(notes),
                "tempo": config.tempo,
                "voices": {n: voices[n].code() for n in QUINTET},
            }
        )
    OUT.write_text(json.dumps(pieces, indent=1) + "\n")
    print(f"recorded {len(pieces)} pieces in {OUT}")


if __name__ == "__main__":
    main()
