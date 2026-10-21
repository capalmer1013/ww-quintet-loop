"""Generate phasing woodwind quintet pieces, one per seed. Run with --help for options."""

from .config import Config
from .render import piece_code, render, seconds
from .theory import resolve_notes
from .voice import generate, piece_beats


def main() -> None:
    config = Config()  # defaults live on Config; every field is also a CLI flag
    resolve_notes(config.notes, 0)  # fail fast on a bad --notes
    requested_tempo = config.tempo
    for seed in config.seed_range():
        config.tempo = requested_tempo
        config.tempo = config.piece_tempo(seed)  # what generate, render and piece_code use
        notes = resolve_notes(config.notes, seed)
        voices = generate(seed, notes, config)
        name = f"piece_{seed}"
        paths = render(name, notes, **voices)
        if config.code:
            path = config.output_dir / f"{name}.py"
            path.write_text(piece_code(name, notes, voices, seed))
            paths.append(path)
        length = seconds(piece_beats(voices.values()), config.tempo)
        print(f"{name}  {notes!r:<12} {config.tempo:3g} bpm  {length:6.2f}s  {', '.join(str(p) for p in paths)}")


if __name__ == "__main__":
    main()
