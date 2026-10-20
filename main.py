"""Generate woodwind quintet loops from the sample library."""
from util import Config, Instrument

QUINTET = ["flute", "oboe", "clarinet", "horn", "bassoon"]


def main() -> None:
    config = Config()  # defaults live on Config; CLI flags like --sample-root override them
    for name in QUINTET:
        inst = Instrument(name)
        low, high = inst.range
        print(f"{inst!r}  range {low}-{high}  dynamics {inst.dynamics}")
    print(f"sample root: {config.sample_root}")


if __name__ == "__main__":
    main()
