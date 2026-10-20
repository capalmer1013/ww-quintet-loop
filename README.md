# ww-quintet-loop

Generate woodwind quintet loops (flute, oboe, clarinet, horn, bassoon) from a bundled sample library.

- `main.py` — entry point that generates loops.
- `util.py` — classes and functions for loading and manipulating samples.
- `samples/` — the sample library (shipped with the repo).

Requires Python 3.10+. No third-party dependencies yet.

## Running

```bash
python3 main.py
```

Show every command-line option:

```bash
python3 main.py --help
```

## Sample library layout

```
samples/<instrument>/notes/<dynamic>/<instrument>_<note>_<dynamic>_<length>.wav
samples/<instrument>/extended/<technique>/<instrument>_<note>_<technique>_<dynamic>_<length>.wav
```

| Field | Values |
|---|---|
| instrument | `flute`, `oboe`, `clarinet`, `horn`, `bassoon` |
| note | Pitch and octave; sharps use `s` (`As1` = A♯1, `C4` = middle C) |
| dynamic | `pp`, `p`, `mp`, `mf`, `f`, `ff` (extended samples may also use `crescendo`, `cresc-decresc`) |
| length | `0.25s`, `0.5s`, `1s`, `1.5s`, `long`, `very-long`, `phrase` |
| technique | e.g. `staccato`, `fluttertonguing`, `major-trill`, `mute`, `glissando`, `phrase` |

Examples:

- `samples/horn/notes/mf/horn_A2_mf_0.25s.wav`
- `samples/bassoon/extended/staccato/bassoon_C4_staccato_mf_phrase.wav`

- `notes/` holds single notes played normally at a fixed dynamic.
- `extended/` holds everything else: other techniques, recorded phrases, and crescendo or swell samples.

Not every instrument has every dynamic. For example, the clarinet has no `mf` or `mp`, and the oboe and horn have only one `pp` sample each. `Instrument.note()` falls back to the nearest dynamic that exists.

## Configuration

All settings live on `util.Config`. The highest-priority source wins:

1. Field defaults on `Config`, in `util.py`.
2. Values passed to `Config(...)` in your script.
3. Command-line flags.

Each `Config` field automatically becomes a `--kebab-case` flag, so adding a field adds its flag and `--help` entry. Unknown flags are ignored, so your script can parse its own arguments too.

| Field | Flag | Default |
|---|---|---|
| `sample_root` | `--sample-root` | `samples/` next to `util.py` |

```bash
python3 main.py --sample-root ~/music/other_samples
```

To ignore the command line (useful in tests or a REPL), pass `argv=[]`:

```python
Config(sample_root="./samples", argv=[])
```

## Loading instruments

### Global config

The most recently created `Config` becomes the current one, and `Instrument()` uses it. If you never create one, a default `Config` is created automatically, and it still reads command-line flags.

```python
from util import Config, Instrument

Config(sample_root="./samples")  # optional
oboe = Instrument("oboe")
```

### Explicit config

```python
c = Config(sample_root="./samples")
oboe = c.Instrument("oboe")
```

`Config.instruments()` lists the instrument folders under `sample_root`. Asking for a missing instrument raises `FileNotFoundError`, and the error lists the instruments that are available.

### Querying samples

```python
horn = Instrument("horn")

horn.notes        # plain-note Samples
horn.extended     # extended-technique Samples
horn.dynamics     # dynamics with plain-note samples, softest first
horn.techniques   # extended techniques available
horn.range        # ("As1", "F5")

horn.find(note="A3", dynamic="p")              # plain notes matching every given field
horn.find(technique="mute")                    # extended samples
horn.note("A3", dynamic="pp", length="0.5s")   # one Sample, with fallback
```

`note()` tries the requested dynamic, then the nearest dynamics. For each dynamic it tries the requested length first, then any length. It raises `KeyError` if the instrument has no sample for that note.

Each `Sample` has `path`, `instrument`, `note`, `dynamic`, `length`, `technique` (`None` for plain notes) and `midi` (e.g. `C4` → 60). Audio is not loaded yet; a `Sample` points to its file.
