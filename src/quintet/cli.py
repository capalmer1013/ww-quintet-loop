"""Generate phasing woodwind quintet pieces, one per seed. Run with --help for options."""

from .config import PIECE_NAME, Config
from .render import piece_code, render, seconds
from .theory import resolve_notes
from .voice import piece_beats, piece_for_seed


def main() -> None:
    """Make one piece per seed in --seeds (or --count clock seeds), printing a line for each."""
    config = Config()  # defaults live on Config; every field is also a CLI flag
    resolve_notes(config.notes, 0)  # fail fast on a bad --notes
    requested_tempo = config.tempo  # 0 = random: piece() overwrites config.tempo per seed
    for seed in config.seed_range():
        try:
            piece(config, seed, requested_tempo)
        except BaseException:  # including Ctrl-C: release this seed's claim if nothing was written
            claimed = config.output_dir / f"{PIECE_NAME.format(seed=seed)}.wav"
            if claimed.exists() and claimed.stat().st_size == 0:
                claimed.unlink()
            raise


def piece(config: Config, seed: int, requested_tempo: float) -> None:
    """Generate, render and report one piece."""
    config.tempo = requested_tempo  # piece_for_seed reads config.tempo: undo the previous seed's
    notes, voices = piece_for_seed(seed, config)  # also sets the tempo render and piece_code use
    name = PIECE_NAME.format(seed=seed)
    paths = render(name, notes, **voices)
    if config.code:
        path = config.output_dir / f"{name}.py"
        path.write_text(piece_code(name, notes, voices, seed))
        paths.append(path)
    length = seconds(piece_beats(voices.values()), config.tempo)
    print(f"{name}  {notes!r:<12} {config.tempo:3g} bpm  {length:6.2f}s  {', '.join(str(p) for p in paths)}")


if __name__ == "__main__":
    main()
