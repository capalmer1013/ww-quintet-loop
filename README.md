# ww-quintet-loop

Generates short phasing pieces for woodwind quintet (flute, oboe, clarinet, horn, bassoon) and
renders them to WAV from a bundled sample library. Each voice loops its own pattern over its own
length, so the loops drift in and out of phase, Reich-style, into a slowly shifting chord cloud.
A piece lasts exactly one full phase cycle, so it loops seamlessly.

## Setup

- **Requires** [uv](https://docs.astral.sh/uv/). Python 3.10–3.13 is supported; uv uses 3.12
  (`.python-version`).
- **Install:** `make sync`
- **Samples** are bundled in `samples/<instrument>/notes/<dynamic>/` (44.1 kHz mono WAVs). Point
  `--sample-root` elsewhere to use another copy.
- Run `make` (or `make help`) to list every target and flag.

## Usage

```bash
make run                                          # one new piece, seeded from the clock
make run ARGS="--seeds 1000-1010 --code"          # seeds 1000-1009, each with its .py file
make run ARGS="--notes D.quartal --tempo 70"      # a fixed harmony and tempo
make lush ARGS="--count 5"                        # five pieces with the lush preset
make loop FILE=out/piece_1000.wav MINUTES=60      # an hour of one piece, gapless
```

Each piece prints its seed, harmony, tempo, length and output files.

| Target | Does |
|---|---|
| `make run` | Generate pieces; flags go in `ARGS="..."` |
| `make batch N=10` | N new pieces in one run (default 10) |
| `make lush` | Warmest sound: `--reverb 1.0 --room 1.0` |
| `make daw` | Also write per-instrument stems and a piece file (`--stems --code`) |
| `make raw` | Humanizing, intonation, mastering and reverb off, for A/B comparisons |
| `make loop FILE=… MINUTES=60` | Repeat a piece into one long `<name>_loop.flac` (most players leave a gap when looping a file) |
| `make seam FILE=…` | Write `<name>_seam.wav`: the last 10 s then the first 10 s, to hear the loop point |

- Presets take `ARGS` too; later flags win.
- `loop` and `seam` also print how clean the join is.

## Configuration

Every field of `Config` (`src/quintet/config.py`) is a flag. Booleans also have a `--no-…` form.

| Flag | Default | Description |
|---|---|---|
| `--seeds` | `now` | `A`, a range `A-B` (B excluded), or `now`: one seed from the clock (Unix time in 1/100 s) |
| `--count` | `1` | With `--seeds now`: how many new pieces |
| `--notes` | `random` | The note set; see below |
| `--tempo` | `0` | BPM; `0` = a whole-number tempo from 60 to 85, random per seed |
| `--max-seconds` | `480` | Longest allowed piece (one full phase cycle) |
| `--reverb` | `0.75` | Hall amount; `0` = dry (no hall, no early reflections) |
| `--room` | `0.9` | Hall size 0–1 (`0.9` ≈ 2.85 s decay, `1` ≈ 3.1 s) |
| `--reverb-ir` | none | Impulse response WAV of a real space (any rate, mono or stereo) instead of the built-in hall; `--room` is then ignored |
| `--master` | on | Phone-friendly EQ, compression, −13 LUFS, −3 dBFS peaks |
| `--saturation` | `0.3` | Tape-style warmth when mastering; `0` = clean |
| `--humanize` | on | Timing, breaths, varied takes and levels |
| `--intonation` | on | Each note tuned a few cents off, differently each time |
| `--a4` | `440` | Concert pitch in Hz; samples are A440, so `432` is about 32 cents flat |
| `--stems` | off | Also write one mono WAV per instrument |
| `--code` | off | Also write a `.py` that rebuilds each piece |
| `--output-dir` | `out` | Where files are written |
| `--sample-root` | repo's `samples/` | Sample library location |

**`--notes` forms**

- `random`: a random key (all 12) and a random harmony.
- `<root>.random`, e.g. `D.random`: a random harmony on that root.
- `<root>.<quality>`, e.g. `C.lydian`, `Fs.maj7s11`, `Bb.quartal`. Roots: `C Cs Db D Ds Eb E F Fs
  Gb G Gs Ab A As Bb B` (`s` = sharp).

**Harmonies `random` picks from** (by weight; `HARMONY_WEIGHTS` in `src/quintet/theory.py`):

| Harmony | On C | Weight |
|---|---|---|
| `lydian` | C D E F♯ G A B | 4 |
| `quartal` | C D F G B♭ (stacked 4ths, root mid-stack) | 2 |
| `quartal_bright` | C D E G A (stacked 4ths, root at the bottom) | 2 |
| `mixolydian` | C D E F G A B♭ | 1.5 |
| `major` | C D E F G A B | 1 |

**Also usable by name** (`QUALITIES` in `src/quintet/theory.py`):

- Chords: `maj min dim aug sus2 sus4 dom7 maj7 min7 dim7 m7b5 maj7s11`
- Extended: `maj9 maj69 min9 min11 sus9 min69 dom9 dom7s11`
- Scales: `minor dorian phrygian locrian harmonic_minor pentatonic_major pentatonic_minor
  whole_tone lydian_dominant`

The harmony and the tempo come from separate random streams per seed, so fixing one doesn't
change what a seed picks for the other.

## Output files

All in `--output-dir` (default `out/`), 44.1 kHz:

| File | When | Format |
|---|---|---|
| `piece_<seed>.wav` | always | Stereo; 16-bit when mastered, 32-bit float with `--no-master` |
| `piece_<seed>_<instrument>.wav` | `--stems` | Mono, 32-bit float, dry (no hall) and unmastered |
| `piece_<seed>.py` | `--code` | A script that rebuilds the piece |

- Unmastered files sit well below full scale (levelling only ever turns samples down); turn them
  up where you play or mix them.

## How it works

- **Loops and phasing:** each voice repeats a pattern on a shared eighth-note pulse, with loops of
  8–13 s; at least 3 different loop lengths per piece, and the piece runs to their lowest common multiple.
- **Harmony:** one note set per piece; each voice draws only from it, within its own register band.
- **Voicing:** bassoon on root and 5th, horn on core tones, colour notes (9ths, 11ths) up top; a soft
  spacing rule and no parallel 5ths or octaves.
- **Lines:** written in each instrument's idiom, with passing tones, neighbours, suspensions, rests,
  legato phrasing and slow per-voice volume sines.
- **Sample levelling:** every recording is scaled (only ever down) to a target level per dynamic;
  all instruments stay at or below `mp` recordings to blend.
- **Performance:** small timing offsets, breaths, rotating takes, ±1 dB level and a few cents of
  intonation, all seeded so renders are reproducible.
- **Staging:** mild stereo seating, stage depth (further back is later, darker, wetter) and early
  reflections.
- **Hall:** circular convolution with a decaying-noise hall (or `--reverb-ir`), 25 ms pre-delay,
  filtered to 250 Hz–7 kHz, so its tail wraps over the loop point.
- **Mastering:** 60 Hz high-pass, −3 dB at 300 Hz, +3.5 dB at 3.5 kHz, +1.5 dB shelf at 10 kHz,
  tanh saturation, 3:1 compression from 10 dB below target, −13 LUFS, −3 dBFS limiter.
- **Seamless loops:** every stateful stage first runs over the piece's own ending, so the loop
  point sounds like the rest.

Full design and the reasoning behind each choice:
[`docs/superpowers/specs/2026-10-20-phasing-quintet-design.md`](docs/superpowers/specs/2026-10-20-phasing-quintet-design.md).

## Piece files

`--code` writes `piece_<seed>.py`, which rebuilds the identical WAV. Edit it to change a piece by
hand:

```python
from quintet import *

Config(tempo=60.0, reverb=0.75, room=0.9, master=True, saturation=0.3, humanize=True, intonation=True, a4=440.0)
render('piece_2000', C.lydian,
    flute    = voice([6, 0, 5], beats=4, dynamic='mp'),
    oboe     = voice([2, 3, 4], beats=6),
    clarinet = voice([1, _, _, _, _, _, 3, _, _], beats=9, drift=8),
    horn     = voice([1, _, _, 3], beats=4),
    bassoon  = voice([7, _, _, _, _, 3, _, _, _, 3, _, _, _, _, 0], beats=15, drift=8, dynamic='mp'),
)
```

- Run it with `uv run python out/piece_2000.py`; flags still apply (e.g. `--stems`, `--tempo 90`).
- `voice(pattern, beats, drift=0, dynamic="p", lfo=0, lfo_phase=0.0)`: `pattern` repeats every
  `beats` beats; `drift=k` shortens the cycle to `beats * k/(k+1)`; `dynamic` is one of
  `pp p mp mf f ff`; `lfo=k` adds a volume sine with `k` cycles over the piece.
- Pattern elements: `1`, `2`, … palette notes (lowest first); `0` rest; `_` hold; `[...]` splits
  the slot evenly; `"3+"`/`"3-"` note 3 a scale step up/down; `"3="` note 3 renewed seamlessly.

## Development

| Target | Does |
|---|---|
| `make test` | Run the tests (pytest) |
| `make lint` | Check the code (ruff) |
| `make format` | Format the code (ruff) |
| `make fixtures` | Re-record the generation parity fixture |

- `tests/test_generation_parity.py` pins what 20 seeds generate, so an accidental change to
  generation fails the tests. Run `make fixtures` only after changing generation on purpose.
