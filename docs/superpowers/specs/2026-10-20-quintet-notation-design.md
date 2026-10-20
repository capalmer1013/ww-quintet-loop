# Quintet notation, harmony and generated parts — design

Status: approved in conversation 2026-10-20; awaiting written-spec review.

## Goal

Write woodwind quintet loops very concisely. The user defines a chord progression; each
instrument picks notes from the current chord within its own range and plays a pattern locked
to the loop length. Parts are generated from a seed by default and any part can be overridden
with a nested-list pattern in the style of python-music (PyLoops / musc v2). The end user can
ask for any number of loops and gets reproducible WAV files.

### Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Authorship | Parts generated per role by default; any part overridable with a pattern |
| Harmony | A progression list of pitch sets, one per bar, nestable like rhythms |
| Integers | musc style: 1-based into the current set, wrapping by octave; `0` rest, `_` hold |
| Variation | Seeded randomness; loop `i` uses `seed + i` |
| Output | Stereo mix per loop; `--stems` adds one mono WAV per instrument |
| Layout | `util/` package, re-exported so `from util import ...` is unchanged |

### Non-goals

- Polyphony within an instrument (they are monophonic; chords are spread across the quintet).
- Wrapping release tails from the loop end into the loop start.
- Pattern-level dynamics or articulations (extended techniques); one dynamic per part.
- Sharp/flat modifiers on degrees (use a different set instead).
- Real-time playback.

## Layout

```
util/
  __init__.py   re-exports the public API (from util import * works)
  config.py     Config (existing, plus new fields)
  samples.py    Sample, Instrument, note_to_midi, DYNAMICS (existing code, moved)
  theory.py     PitchClass, PitchSet, interval constants, fifths/fourths
  pattern.py    _ (hold), pattern expansion to timed events, progression expansion
  parts.py      Role, Part, role pattern libraries, seeded generation, register mapping
  render.py     Sequence, fade_out, write_wav, read cache (existing), pan/mix
  quintet.py    Quintet
main.py         example script: a progression, Quintet(...).render()
tests/          pytest suite
Makefile        help (default), run, test
```

`util.py` is removed; its contents move into the package unchanged except where noted.

## 1. Theory (`util/theory.py`)

### Pitch classes and intervals

- `PitchClass(int)` with value 0–11. Constants for every name:
  `C Cs Db D Ds Eb E F Fs Gb G Gs Ab A As Bb B` (enharmonics are equal: `As == Bb`).
- `PitchClass + int` / `- int` returns a `PitchClass` (mod 12).
- Interval constants (ints, semitones): `m2 M2 m3 M3 P4 TT P5 m6 M6 m7 M7`.
- `pc.up(interval)`, `pc.down(interval)` → `PitchClass`.

### Pitch sets

`PitchSet(root: PitchClass, intervals: tuple[int, ...], name: str)`, frozen. Intervals are
semitones above the root, ascending, starting with 0.

- Chord qualities as `PitchClass` attributes: `maj min dim aug sus2 sus4 dom7 maj7 min7 dim7 m7b5`.
- Scale qualities as attributes: `major minor dorian phrygian lydian mixolydian locrian
  harmonic_minor pentatonic_major pentatonic_minor blues`.
- Unknown attribute → `AttributeError` listing valid qualities.
- `s.up(interval)`, `s.down(interval)` → same quality, transposed root.
- `s.fifths(n)` → moves the root `n` steps clockwise round the circle (`n * 7` semitones);
  negative `n` goes anticlockwise. `s.fourths(n)` is `s.fifths(-n)`.
- `PitchClass` has the same `fifths(n)` / `fourths(n)`.
- `s.pitch(degree, root_midi)` → MIDI int: degree 1 is `root_midi`; degree `k` steps through the
  set, wrapping up an octave every `len(intervals)` steps; negative degrees go below
  (`-1` is the top set tone an octave below the root). Degree `0` is invalid here (it is a rest
  in patterns).
- `repr` reads back as code: `C.maj7`, `Bb.dom7`.

### Circle generators

- `fifths(start, n)` → list of `n` items starting at `start`, each a fifth above the last.
  `start` may be a `PitchClass` or a `PitchSet`.
  `fifths(C, 4) == [C, G, D, A]`.
- `fourths(start, n)` likewise by fourths: `fourths(C.dom7, 4) == [C.dom7, F.dom7, Bb.dom7, Eb.dom7]`.

## 2. Patterns and progressions (`util/pattern.py`)

### Pattern elements

| Element | Meaning |
|---|---|
| `int` ≠ 0 | degree into the set sounding at that moment (1-based, wraps by octave, negative below) |
| `0` | rest |
| `_` | hold: extend the previous note (or rest) through this slot |
| `str` like `"A4"`, `"Cs5"` | absolute pitch, ignores the current set |
| `list` | group: divide this slot's span equally among its elements, recursively |

Anything else (float, tuple, bool, unknown string) → `ValueError` naming the element and its
path, e.g. `pattern[2][1]: 1.5 is not a pattern element`.

### Timing

- A pattern spans `bars` bars (default 1) and repeats to fill the loop.
- Expansion produces `Event(start: Fraction, beats: Fraction, value)` with `value` an int degree,
  an absolute pitch string, or `None` for a rest. Holds merge into the preceding event before
  output, so events never overlap and tile the span exactly.
- A `_` at the start of a repetition continues the last event of the previous repetition. At the
  very start of the loop there is nothing to hold, so it becomes a rest.
- All times are `fractions.Fraction` in beats; conversion to frames happens only in rendering.

### Progressions

- A progression is a list of `PitchSet`s, one per bar; a nested list divides that bar among its
  sets, using the same subdivision rule as patterns (`[C.maj, [G.dom7, G.sus4]]` = bar 2 split).
- Expansion produces `(start, beats, PitchSet)` spans. Loop length is `len(progression)` bars.
- Each pattern event takes the set sounding at its **start**; a note held across a chord change
  keeps its pitch.
- Empty progression or non-`PitchSet` element → `ValueError`.

## 3. Parts and roles (`util/parts.py`)

### Roles

| Instrument | Role | Register anchor (fraction of sampled MIDI range) | Default dynamic |
|---|---|---|---|
| bassoon | `bass` | 0.25 | mf |
| horn | `pad` | 0.40 | p |
| clarinet | `arpeggio` | 0.50 | mp |
| oboe | `counter` | 0.60 | mf |
| flute | `melody` | 0.65 | mf |

The anchor is `low + fraction * (high - low)` over the instrument's sampled range
(`Instrument.range`).

Each role has a library of 4–8 one-bar template patterns, for example:

- `bass`: `[1, _, 5, _]`, `[1, 0, [1, 5], -3]`, `[1, _, _, 5]`
- `pad`: `[2, _, _, _]`, `[3, _, 2, _]`, `[4, _, _, 3]`
- `arpeggio`: `[[1, 2], [3, 4], [3, 2], [1, 2]]`, `[[1, 3, 5], [3, 1, 3]]`
- `counter`: `[0, 3, [2, 0], 4]`, `[3, _, [4, 3], 2]`
- `melody`: `[5, [4, 3], 2, _]`, `[[5, 6], 5, [4, 3], 2]`

(Exact libraries are tuned during implementation; tests assert properties, not contents.)

### Register mapping

For each event: degree 1 maps to the set's root in the octave nearest the role anchor; the degree
is then resolved with `PitchSet.pitch`. A result outside the instrument's sampled range is
moved by octaves until it fits. Absolute pitches are folded into range the same way.

### Part

`Part(pattern=None, role=None, bars=1, dynamic=None)`. `None` fields fall back to the
instrument's role defaults; `pattern=None` means generate.

### Seeded generation

For loop seed `s`, each part gets `numpy.random.default_rng([s, k])`, where `k` is the
instrument's fixed index in `flute oboe clarinet horn bassoon` (not Python's salted `hash`), so
changing one part's override does not change the others. Generation:

1. pick a template from the role library;
2. with probability `variation` per leaf, apply one mutation: swap the degree for an adjacent
   chord tone (±1), split the slot into two copies, or (melody/counter/arpeggio only) turn it
   into a rest. Holds and rests are not mutated.

`variation=0` returns templates unchanged. Same seed → identical pattern.

### Overrides

On a `Quintet`, `q.flute = [...]` sets that part's pattern (role, register, dynamic kept);
`q.flute = Part(...)` replaces the part spec. An overridden pattern is used for every loop.

## 4. Quintet, rendering and output

### Config additions (`util/config.py`)

| Field | Flag | Default |
|---|---|---|
| `loops: int` | `--loops` | `1` |
| `seed: int` | `--seed` | `0` |
| `variation: float` | `--variation` | `0.3` |
| `beats_per_bar: int` | `--beats-per-bar` | `4` |
| `output_dir: Path` | `--output-dir` | `out` (relative to the working directory) |
| `stems: bool` | `--stems/--no-stems` | `False` |

`tempo` and `sample_root` are unchanged. Tempo is not a `Quintet` argument, so the CLI always
wins.

### Quintet (`util/quintet.py`)

```python
Config(tempo=96)
q = Quintet([C.maj7, A.min7, D.min7, G.dom7])
q.flute = [3, [2, 1], 5, _]
q.render()
```

- `Quintet(progression, config=None)`; instruments are loaded once via `Instrument(name, config)`.
- Part attributes: `flute oboe clarinet horn bassoon`.
- `q.loop(seed) -> np.ndarray` of shape `(frames, 2)`, float32, nothing written.
- `q.render() -> list[Path]` writes `config.loops` loops: loop `i` uses seed `config.seed + i`
  and is written to `output_dir/loop_{seed:04d}.wav`; with `stems`, also
  `output_dir/loop_{seed:04d}_{instrument}.wav` (mono).

Each part compiles to the existing monophonic `Sequence` (held notes sound through their holds
and are cut by the next event; 10 ms fade on cuts; last note cut at the loop end). Sample length
is chosen from the event duration as `Sequence.add` already does.

### Mixing (`util/render.py`)

- Constant-power pan: flute −0.6, oboe −0.25, bassoon 0, clarinet +0.25, horn +0.6.
- Fixed master gain 0.6. If the mix still peaks above 0.99, scale that loop down to 0.99
  (never up), so loops stay level-consistent.
- `write_wav` gains stereo support (2-D array → 2 channels).

### main.py

A short example: defines a progression, builds a `Quintet`, calls `render()`, prints the written
paths. All control comes from flags: `python3 main.py --loops 8 --seed 3 --stems --tempo 90`.

## 5. Errors

- `ValueError` with element path for bad pattern elements; for empty progressions, non-`PitchSet`
  progression elements, `bars < 1`, unknown role, unknown instrument attribute on `Quintet`.
- `AttributeError` listing valid qualities for unknown chord/scale names.
- Existing `KeyError` from `Instrument.note` if no sample exists (should not occur after range
  folding).

## 6. Testing

pytest (dev dependency in `pyproject.toml`), run with `make test`. Tests use the real `samples/`.

- `tests/test_theory.py`: pitch-class arithmetic and enharmonics; every chord/scale quality's
  pitch classes; `up/down`; `fifths/fourths` on classes and sets incl. wrap; `PitchSet.pitch` for
  positive, wrapping and negative degrees; reprs.
- `tests/test_pattern.py`: flat and nested subdivision times (incl. triplets) as exact
  `Fraction`s; holds within and across repetitions; leading hold at loop start → rest; rests;
  absolute pitch strings; `bars=2`; invalid elements report their path; progression expansion and
  set-at-event-start lookup.
- `tests/test_parts.py`: every generated pitch for every role and many seeds lies in the
  instrument's sampled range; same seed → same pattern, different seeds → different patterns
  (across a sample of seeds); `variation=0` → template unchanged; overrides replace generation.
- `tests/test_render.py`: loop frames = bars × beats_per_bar × 60 / tempo × 44100; output shape
  `(frames, 2)`; peak ≤ 0.99; flute part is louder in the left channel than the right; existing
  `Sequence` cut/fade/rest behaviour; `render()` writes the expected filenames incl. stems.

## 7. Makefile and docs

Root `Makefile`, `help` as default target:

- `help` — list targets
- `run` — `python3 main.py $(ARGS)`
- `test` — `python3 -m pytest`

README updated: running via `make run ARGS="..."`, the notation, theory helpers, Quintet, Config
table with the new fields.
