# Phasing chord-cloud quintet pieces — design

Status: revised design approved in conversation 2026-10-20; awaiting written-spec review.

## Goal

Generate small woodwind quintet pieces in which five voices each cycle their own pattern of
notes, drawn from one note set, over their own time span. The voices drift in and out of phase
(moiré / Reich-style), making a polyrhythmic chord cloud. One seed makes one piece; a seed range
makes many. Each piece can also be written out as a short `.py` file that reproduces it.

This only ever generates woodwind quintets (flute, oboe, clarinet, horn, bassoon). Simplicity over
extensibility.

### Decisions

| Topic | Decision |
|---|---|
| Phasing | Different cycle lengths, different note counts in the same span, and tempo drift — all one mechanism (a pattern stretched over a span) |
| Length | One full phase cycle: every voice realigns at the end, so the file loops seamlessly |
| Harmony | One note set per piece |
| Seeds | `--seeds 1000-1100` makes pieces 1000…1099; `--seeds 1000` makes one |
| Spacing | Voice registers follow the harmonic series loosely: wide at the bottom, closer higher up |
| Code output | `--code` writes a `.py` per piece that reproduces it |
| Dependencies | None. Standard library only. Tests use `unittest` and are not shipped |
| Layout | `main.py` + `utils/` package (+ `samples/`) |

### Non-goals

- Instruments other than the quintet; plugin-style roles or part classes.
- Chord progressions within a piece.
- Polyphony within an instrument.
- Per-note dynamics or extended techniques (one dynamic per voice, plain-note samples only).
- Wrapping release tails across the loop point.

## Layout

```
main.py           CLI entry: generate pieces for the configured seed range
utils/
  __init__.py     public API (from utils import * works)
  config.py       Config
  samples.py      Sample, Instrument, note_to_midi, DYNAMICS
  theory.py       PitchClass, PitchSet, intervals, fifths/fourths, parse_set
  pattern.py      _ (hold), pattern expansion to timed events
  voice.py        voice(), palettes and register spacing, seeded generation
  render.py       wav read/write, monophonic voice rendering, mix, render(), piece code output
samples/          sample library (shipped)
tests/            unittest suite (not shipped)
Makefile          help (default), run, test (not shipped)
docs/             (not shipped)
```

The existing `util.py` is replaced by `utils/`. numpy is removed; `pyproject.toml` declares no
dependencies.

## 1. Theory (`utils/theory.py`)

- `PitchClass(int)`, 0–11, with constants `C Cs Db D Ds Eb E F Fs Gb G Gs Ab A As Bb B`
  (enharmonics equal). `+`/`-` an int wraps mod 12. `pc.up(i)`, `pc.down(i)`.
- Interval constants (semitones): `m2 M2 m3 M3 P4 TT P5 m6 M6 m7 M7`.
- `PitchSet(root, intervals, name)`, frozen; intervals ascending from 0. Qualities are attributes
  of a `PitchClass`:
  - chords: `maj min dim aug sus2 sus4 dom7 maj7 min7 dim7 m7b5 maj7s11` (`maj7s11` = 0 4 6 7 11)
  - scales: `major minor dorian phrygian lydian mixolydian locrian harmonic_minor
    pentatonic_major pentatonic_minor whole_tone`
  - unknown quality → `AttributeError` listing the valid ones.
- `s.up(i)`, `s.down(i)`; `s.fifths(n)` moves the root `n` steps round the circle (negative =
  anticlockwise), `s.fourths(n) == s.fifths(-n)`; the same on `PitchClass`.
- `fifths(start, n)`, `fourths(start, n)` → lists of `n`, for a `PitchClass` or `PitchSet`.
- `s.pitches(low, high)` → sorted MIDI numbers of the set's tones in `[low, high]`.
- `repr` reads back as code (`C.maj7s11`, `Bb.dom7`).
- `parse_set("C.maj7s11")` → `PitchSet`; also accepts `Fs.lydian`, `Bb.dom7`. Invalid →
  `ValueError` naming the bad root or quality. Used for `--notes`.

## 2. Patterns (`utils/pattern.py`)

| Element | Meaning |
|---|---|
| `int` ≥ 1 | index into the voice's palette (1 = its lowest note), wrapping round |
| `0` | rest |
| `_` | hold the previous note (or rest) through this slot |
| `list` | divide this slot's span equally among its elements, recursively |

Anything else → `ValueError` with the element's path, e.g. `pattern[2][1]: 1.5 is not a pattern
element`.

`expand(pattern, span)` → list of `Event(start, beats, index)` with `Fraction` times in beats,
`index` an int or `None` (rest). Events tile `[0, span)` exactly; holds merge into the previous
event. A leading `_` continues the previous cycle's last event; at the very start of the piece it
is a rest.

## 3. Voices (`utils/voice.py`)

### voice()

`voice(pattern, beats, drift=0, dynamic="mf")` → `Voice`.

- The pattern repeats every **cycle span** beats:
  - `drift=0`: span = `beats`.
  - `drift=k` (k ≥ 1): span = `beats * k / (k + 1)`. The voice runs slightly fast and, against a
    voice with the same `beats` and no drift, realigns after `k + 1` of its own cycles (`k` of the
    other's).
- Different `beats` across voices = cycle-length phasing; a pattern with `n` slots over `beats`
  ≠ `n` = tuplets / different note counts in the same time; `drift` = Reich-style drift.
- Spans are `Fraction`s; `beats` is a positive int, `drift` a non-negative int, `dynamic` one of
  `DYNAMICS`. Invalid values → `ValueError`.

### Piece length

Piece length in beats = LCM of the five cycle spans (rational LCM: `lcm(numerators) /
gcd(denominators)` of the reduced fractions). Every voice completes a whole number of cycles, so
all realign at the end and the file loops seamlessly.

### Register spacing (palettes)

- Fundamental `F` = the set's root in MIDI octave 2 (`36 ≤ F < 48`; C → 36).
- Each voice is centred on a partial of `F`: bassoon 2, horn 3, clarinet 4, oboe 6, flute 8,
  i.e. `F + round(12 * log2(p))` semitones (C: C3, G3, C4, G4, C5). Lower neighbours sit an
  octave/fifth apart; upper ones closer, loosely following the harmonic series.
- If a centre is outside the instrument's sampled range it moves by octaves into range.
- Palette = `set.pitches(centre - 5, centre + 7)` within the instrument's range. If that has
  fewer than 3 notes, the window widens a semitone each side until it has 3 (or reaches the range).
- These constants (partials, window) live at the top of `voice.py` and are tuned against the
  Lydian / maj7#11 test piece.

Pattern index `k` → `palette[(k - 1) % len(palette)]`.

### Seeded generation

`generate(seed, notes, config) -> dict[str, Voice]` using `random.Random(seed)` (stdlib).
For each voice, in fixed order flute, oboe, clarinet, horn, bassoon:

1. `n` slots, 2–7.
2. Each slot: a palette index (1…len(palette)); with small probabilities instead a hold (not
   first slot), a rest, or a subdivision into 2–3 sub-slots (one level).
3. `beats` from 2–8.
4. With probability ~0.2, a drift `k` from {8, 12, 16, 24}; at most two drifting voices.
5. `dynamic` from the instrument's available dynamics among `p mp mf`.

If the piece length exceeds `config.max_seconds`, keep drawing whole new voice sets from the same
`Random` until it fits (deterministic for a given seed). Probabilities are constants at the top of
`voice.py`.

## 4. Rendering and output (`utils/render.py`)

### Audio (stdlib only)

- Samples read with `wave` into `array('h')`, converted to float lists, cached by path.
- Each voice renders as a monophonic line (current `Sequence` semantics): a note sounds until its
  sample ends or the next event starts; 10 ms linear fade on a cut; the last note is cut at the
  piece end. Sample length is the shortest recorded length covering the event (existing
  `Instrument.note` behaviour).
- Mix: constant-power pan (flute −0.6, oboe −0.25, bassoon 0, clarinet +0.25, horn +0.6), master
  gain 0.6, scaled down (never up) if the peak exceeds 0.99.
- Output: 16-bit 44.1 kHz WAV; stereo mix, mono stems.

### render()

`render(name, notes, **voices) -> list[Path]` with `voices` = `flute oboe clarinet horn bassoon`
(all five required; missing or unknown names → `ValueError`). Writes to `config.output_dir`:

- `<name>.wav` — stereo mix
- `<name>_<instrument>.wav` per voice when `config.stems`

Tempo comes from `Config.current()`.

### Piece code (`--code`)

Writes `<name>.py` next to the WAV:

```python
"""piece_1000 — seed 1000, C.maj7s11, 63.75 s"""
import sys
sys.path.insert(0, "/abs/path/to/repo")  # directory containing utils/, recorded at generation
from utils import *

Config(tempo=120)
render("piece_1000", C.maj7s11,
    flute    = voice([3, 5, [2, 1], 4], beats=5),
    oboe     = voice([1, 3, 2], beats=3, dynamic="mp"),
    clarinet = voice([2, _, 4, 1, 5], beats=4),
    horn     = voice([1, _, _, 3], beats=4, drift=16, dynamic="p"),
    bassoon  = voice([1, _, 2, _], beats=8),
)
```

Running it (`python3 out/piece_1000.py`) reproduces the WAV byte-for-byte; CLI flags still apply
(`--stems`, `--tempo`, `--output-dir`). Editing it is how a piece is changed by hand.

## 5. Config (`utils/config.py`)

Existing mechanism unchanged (field defaults < `Config(...)` < CLI flags, auto-generated flags).

| Field | Flag | Default |
|---|---|---|
| `sample_root` | `--sample-root` | `samples/` beside `utils/` |
| `tempo` | `--tempo` | `120` |
| `notes` | `--notes` | `C.maj7s11` |
| `seeds` | `--seeds` | `0` (`A` or `A-B`, B exclusive) |
| `max_seconds` | `--max-seconds` | `90` |
| `output_dir` | `--output-dir` | `out` |
| `stems` | `--stems/--no-stems` | off |
| `code` | `--code/--no-code` | off |

Bad `--seeds` / `--notes` → `ValueError` with the expected form.

## 6. main.py

For each seed in the range: `generate`, then `render(f"piece_{seed}", ...)`, plus the code file
when `--code`; prints one line per piece (name, length in seconds, files written).

```bash
python3 main.py --notes C.lydian --seeds 1000-1100 --code
```

## 7. Errors

`ValueError` for bad pattern elements (with path), bad `voice()` arguments, missing/unknown voice
names in `render`, bad `--seeds` / `--notes`. `AttributeError` for unknown qualities. Existing
`FileNotFoundError` / `KeyError` from `Instrument`.

## 8. Testing (`tests/`, `python3 -m unittest`, not shipped)

- `test_theory`: pitch-class arithmetic, enharmonics; each quality's pitch classes (incl.
  `maj7s11`, `lydian`); `up/down/fifths/fourths` incl. wrap; `pitches(low, high)`; reprs;
  `parse_set` valid and invalid.
- `test_pattern`: flat/nested subdivision as exact `Fraction`s incl. triplets; holds within and
  across cycles; leading hold at piece start → rest; rests; invalid elements report their path.
- `test_voice`: span with and without drift; rational LCM (incl. drift voices); palette spacing
  for C.maj7s11 (centres ascending bassoon→flute, adjacent lower pairs ≥ a fifth apart, palettes
  within instrument ranges, ≥ 3 notes each); same seed → identical voices, different seeds differ;
  every generated piece ≤ `max_seconds`.
- `test_render`: mix length = piece beats × 60 / tempo × 44100 frames; stereo; peak ≤ 0.99; flute
  louder left than right; cut/fade/rest behaviour; stems and code files written with the expected
  names; running an emitted `.py` reproduces the same WAV bytes.

## 9. Makefile and README

`Makefile` (default `help`): `help`, `run` (`python3 main.py $(ARGS)`), `test`
(`python3 -m unittest`). README rewritten around `make run ARGS="--notes C.lydian --seeds
1000-1010 --code"`, the voice/pattern notation, theory helpers and Config table.

## 10. First acceptance check

`make run ARGS="--notes C.maj7s11 --seeds 1000-1005 --code"` and the same with `C.lydian`; the user
listens to judge whether the result matches the intended chord-cloud / phasing character. Palette
and generation constants are tuned from that feedback.
