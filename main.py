"""Generate phasing woodwind quintet pieces, one per seed. Run with --help for options."""
from utils import Config, generate, parse_set, piece_beats, piece_code, render, seconds


def main() -> None:
    config = Config()  # defaults live on Config; every field is also a CLI flag
    notes = parse_set(config.notes)
    for seed in config.seed_range():
        voices = generate(seed, notes, config)
        name = f"piece_{seed}"
        paths = render(name, notes, **voices)
        if config.code:
            path = config.output_dir / f"{name}.py"
            path.write_text(piece_code(name, notes, voices, seed))
            paths.append(path)
        length = seconds(piece_beats(voices.values()), config.tempo)
        print(f"{name}  {length:6.2f}s  {', '.join(str(p) for p in paths)}")


if __name__ == "__main__":
    main()
