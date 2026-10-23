# Phasing chord-cloud quintet pieces — design

Status: implemented 2026-10-20.

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
- Extended techniques (plain-note samples only).
- Phrase-level swells (tried in section 11, removed in section 14).
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

- Fundamental `F` = the set's root nearest C2 (G1 31 … F♯2 42).
- Voice centres sit on partials of `F`: bassoon 2, horn 3, clarinet 4, oboe 6, flute 8,
  i.e. `F + round(12 * log2(p))` (C: C3, G3, C4, G4, C5).
- Each voice owns the band from halfway to the centre below to halfway to the centre above
  (bassoon reaches an octave below its centre, flute an octave above), so bands are wide at the
  bottom and narrow on top, loosely following the harmonic series.
- Palette = the set's tones in the band that the instrument has plain-note samples for. If that
  has fewer than 3 notes, the band widens a semitone each side until it does (or covers the range).
- These constants live at the top of `voice.py` and are tuned against the Lydian / maj7#11 test.

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

If the piece length exceeds `config.max_seconds`, or fewer than 4 voices have distinct cycle spans,
keep drawing whole new voice sets from the same `Random` until it fits (deterministic for a given seed). Probabilities are constants at the top of
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

## 11. Swells and sustained notes (added 2026-10-20 after the first listening test)

The first pieces sounded too "square": every voice held one dynamic, and notes stopped at the end
of their samples.

- **Swells:** `voice(..., swell=m, phase=x)`.
  - The voice's level follows a raised-cosine `<>` lasting `m` of its cycles, starting at phase `x`
    (0 = quiet point, 0.5 = peak).
  - Gain runs from −9 dB to 0 dB. It is applied per 512-frame block, folded into the pan gains in
    `mix()`, and applied separately for stems.
  - Each note's sample layer is the peak dynamic stepped down by `round((1 - level) * 2)`.
  - `render` raises `ValueError` if `m` does not divide the voice's cycle count, because the loop
    would not be seamless.
  - Generation gives every voice a swell: `m` is a divisor of its cycle count giving 4–12 s
    (else the one nearest 8 s), phase is random to 2 decimals, and the peak is drawn from
    `mp mf f`.
- **Sustain:** a note longer than its sample plays:
  1. the attack (the first 0.3 s, or the first quarter of the sample),
  2. the middle, repeated with 100 ms equal-power crossfades,
  3. the release (the last 0.6 s, or the last 35% of the sample),

  trimmed to exactly the note length. A note shorter than its sample is cut with a fade of 10% of
  the note, clamped to 10–150 ms.
- **Sustaining voices:** each piece has 1–2. A sustaining voice has 2–3 notes of 3–6 one-beat slots
  each (a note plus holds), plus an optional one-beat rest; its `beats` is the slot count.

## 12. Levelling (added 2026-10-20)

The library's recording levels are not calibrated. At the same dynamic the bassoon was 10–14 dB
louder than the flute, and pitches on one instrument varied by about 4 dB.

- `leveled(sample, dynamic)` scales each sample so that the RMS of its loudest 0.3 s equals
  `LEVEL_REF_DB` (−24 dBFS) + `DYNAMIC_DB[dynamic]` + `INSTRUMENT_TRIM_DB[instrument]`.
- The dynamic offsets are `pp` −12, `p` −8, `mp` −4, `mf` 0, `f` +3, `ff` +6 dB.
- Levelling uses the requested dynamic, so a fallback sample (e.g. clarinet `mf`) plays at the
  level asked for.
- The result is cached per (sample, dynamic).

## 13. Instrument idioms, horn tone, tempo and attacks (added 2026-10-20)

- **Idioms:** `PROFILES` in `voice.py` gives each instrument its own character.
  - **Melodic walk:** a note moves from the previous one with these weights (repeat / step / skip /
    leap): flute 10/50/25/15, oboe 15/60/20/5, clarinet 10/25/45/20, horn 50/15/30/5,
    bassoon 25/25/15/35. Bassoon octave leaps are weighted ×3.
  - **Anchor notes:** tones weighted ×2 — horn root and 5th, bassoon root.
  - **Quick figures:** run (flute), pair (oboe), arpeggio (clarinet), repeat (horn), bounce
    (bassoon).
  - **Rhythm:** each profile also sets its rest and hold chances, slot range and beat range.
  - **Sustainers:** chosen weighted by `Profile.sustain` (horn and clarinet 3, oboe and bassoon 2,
    flute 1).
- **Horn tone:** `Profile.top_layer` caps the recorded dynamic used. The horn uses at most `mf`,
  because its `ff` samples measure about 35% brighter. Levelling still uses the requested dynamic,
  so a horn can be loud without sounding brassy.
- **Tempo:** the defaults become `--tempo 60` and `--max-seconds 180`, the same room for phase
  cycles in beats. The swell target is now 6–16 s.
- **Attacks:** every note fades in (sin²) over `ATTACK_BEATS` = 0.08 beats, capped at a quarter of
  the note. (Raised to 0.15 beats, 150 ms at 60 bpm, after listening.)

## 14. Per-note hairpins replace phrase swells; quiet dynamics (added 2026-10-20)

Listening showed that the phrase-level swells (section 11) made notes appear out of nowhere at full
volume. They are removed entirely: `Voice.swell` and `Voice.phase`, the block gains in `mix()`, and
`swelled()`.

- **Long notes:** any note of `LONG_NOTE_SECONDS` = 1.5 s or more is shaped `<>` by `hairpin()`.
  The gain curve is sin² warped so that it peaks at 40% of the note, with a floor of −30 dB at both
  ends.
- **Short notes:** these keep the tempo-scaled attack fade.
- **Dynamics:** generated voices use `p` or `mp`, and `Voice`'s default dynamic is now `p`.
- **Layer cap:** `MAX_LAYER = "mp"` is the loudest recorded dynamic ever used. `Instrument.note`
  takes `max_dynamic` and falls back only to softer layers. This replaces the horn-only
  `top_layer`.
- **Note cache:** each finished note (levelled, cut or sustained, then shaped) is cached by
  (sample, dynamic, frames, tempo), because cycling voices repeat identical notes.

## 15. Reverb (added 2026-10-20)

*Superseded by pedalboard's reverb; see `2026-10-20-proper-project-design.md`.*

Post-processing to sound less MIDI-like, still standard library only (`utils/reverb.py`).

- **Signal path:** a Freeverb-style reverb with mono in and stereo out.
  1. The dry stereo mix is averaged to mono, decimated to 22.05 kHz, and scaled by `INPUT_GAIN`.
  2. It is pre-delayed 20 ms.
  3. It feeds 6 parallel comb filters (Freeverb tunings halved). Each takes a 2-tap FIR lowpass in
     its feedback, `DAMPING` = 0.4, with feedback = 0.7 + 0.28 × room.
  4. The summed combs go through 2 series allpass filters per channel (gain 0.5), with the right
     channel's delays offset for width.
  5. The wet signal is linearly interpolated back to 44.1 kHz, wrapping at the loop point, and
     added to the dry mix as `amount × WET_SCALE × wet`. At amount 1, wet is about 0.7× the dry
     level on real pieces.
- **Speed:** every feedback delay is at least one block long, so blocks are computed with list
  comprehensions rather than per-sample loops.
- **Seamless loops:** the input is pre-rolled with 2 × RT60 of the piece's own ending (indexed
  modulo the piece length), and only the last `n` frames are kept. One rendered loop therefore
  equals a loop that follows another, which a test checks.
- **Config:** `reverb` (amount, default 0.3; 0 = dry and byte-identical to before) and `room`
  (0–1, default 0.8, RT60 ≈ 2.6 s). Piece files record `tempo`, `reverb` and `room` in their
  `Config(...)` call.
- **Stems** stay dry.
- **Cost:** about +10 s per 2-minute piece (11 s → 21 s).

## 16. Volume sines (added 2026-10-20)

Each voice can have a slow sine on its volume: `voice(..., lfo=k, lfo_phase=x)`.

- **Shape:** `k` whole cycles over the piece, so loops stay seamless, starting at phase `x`
  (0 = loudest).
- **Gain:** `10^(-LFO_DEPTH_DB * (1 - cos 2π(pos·k + x)) / 2 / 20)`, a 6 dB dip.
- **Mixing:** the gain is applied per 512-frame block, folded into the pan gains in `mix()`. Stems
  get it via `with_gains()`.
- **Generation:** `k` gives a period of 10–30 s and is preferably not a divisor of the voice's
  cycle count, so the sine is out of step with the pattern and each repeat sounds different. The
  phase is random to 2 decimals.
- **Difference from the removed phrase swells (section 11):** volume only (sample layers never
  change), shallower, and deliberately unaligned with the voice's cycle.

## 17. Random key, chord and tempo; voicing (added 2026-10-20)

- **Harmony:** `--notes` defaults to `random`. `resolve_notes(spec, seed)` handles three forms:
  - `random`: picks a root uniformly and a quality from `HARMONY_WEIGHTS`:
    maj9 3, maj69 3, min9 3, min11 2, sus9 2, maj7s11 2, min69 1.5, dom9 1.5, dom7s11 1.
  - `<root>.random`: fixes the root and picks the quality.
  - `<root>.<quality>`: fixed, as before.
  - Very dissonant chords (minor-major 7th, augmented, altered dominants) are excluded.
- **Tempo:** `--tempo` defaults to 0, meaning random per seed. `Config.piece_tempo(seed)` returns a
  whole number in `TEMPO_RANGE` = 50–70. `main.py` sets `config.tempo` per piece before
  generating. `Config.bpm()` raises while the tempo is still 0, so a library call can't render at
  an undefined tempo. Piece files record the chosen tempo.
- **Separate streams:** harmony and tempo use their own `random.Random(f"{seed}:harmony")` and
  `random.Random(f"{seed}:tempo")` streams, so fixing one doesn't change the seed's pick for the
  other. The lines still depend on both: palette sizes follow the chord, and the tempo decides
  which candidate fits `--max-seconds`.
- **Voicing** (`VOICING` in `voice.py`):
  - The bassoon plays `PitchSet.bass` (root and 5th).
  - The horn plays `PitchSet.core` (root, 3rd or sus, 5th, 7th or 6th; a scale's core is its
    triad).
  - The clarinet, oboe and flute play every tone.
  - Classical practice: colour notes stay out of the low register, where they sound muddy.
- **Playable pitches:** palettes are limited to `Instrument.playable`, the pitches with a
  plain-note sample at or below `MAX_LAYER` (now in `samples.py`). A test checks every quality on
  every root for every instrument.

## 18. Per-instrument layer caps (added 2026-10-20)

`MAX_LAYER` becomes `MAX_LAYERS` (`samples.py`):

| Instrument | Cap |
|---|---|
| flute, oboe, clarinet, bassoon | `mf` |
| horn | `mp`, so it blends |

- `Instrument.max_layer` caps both `Instrument.note` (via `max_dynamic`) and `Instrument.playable`.
- Generation draws each voice's dynamic from `p` up to its instrument's cap.
- The clarinet has no `mp` or `mf` recordings, so it plays its `p` recordings, levelled up to the
  requested dynamic.

## 19. Non-chord tones and voice leading (added 2026-10-20)

- **Notation:** a pattern element may be `"k+"` or `"k-"`, meaning palette note k moved one step of
  `PitchSet.scale` (the parent scale in `PARENT_SCALES`) up or down. `resolve_pitch` turns it into
  a pitch. A step the instrument can't play at its layer cap stays on note k. Integers are
  unchanged, so old piece files render byte-identically (checked on `piece_6000`).
- **Figures** (probabilities per `Profile`):
  - **Passing:** a slot `a` followed by `b` a 3rd away becomes `[a, "a±"]` when the scale step is a
    playable non-chord tone strictly between them.
  - **Neighbour:** `b` becomes `[b, "b±", b]`.
  - **Suspension** (sustaining voices): a held note `k` becomes `"k+"` for its first half, then `k`.
  - All non-chord tones are left by step (tested).
  - About two thirds of random pieces contain some.
- **Voice leading:** `parallels()` finds simultaneous motion in two voices from interval class
  {0, 7} (unison/octave or 5th, by absolute distance mod 12) to the same class, in similar or
  contrary motion. The timeline wraps at the loop point. Holds and rests never count.
- **Repair:** `_repair()` greedily nudges the offending event's leaf to a neighbouring palette
  index, using `event_paths()` to map events to pattern leaves. It skips non-chord tones and their
  neighbouring events, and keeps an edit only if the parallel count drops. It is limited to
  `REPAIR_STEPS` = 60; an unrepairable candidate is redrawn. Generation for 30 pieces takes about
  0.5 s, and most candidates need no repair.
- **Deep copy:** `_` survives `copy.deepcopy` as the same object, because the repair copies
  patterns.

## 20. Longer loops (added 2026-10-20)

Each voice's loop was 2–8 s, so it repeated too often.

- **Loop length:** every voice's cycle is now `CYCLE_SECONDS` = 10–16 s, rounded to whole beats at
  the piece's tempo (9–13 beats at 50 bpm, 12–18 at 70).
- **Moving voices:** a cycle is several equal phrase cells. Each cell is about the profile's old
  `beats` range in length, written by the old cycle generator (`_cell`), and the walk carries on
  across cells.
- **Sustaining voices:** 3–5 notes split the cycle at random, each held at least 2 beats, with an
  optional one-beat closing rest.
- **Drift:** applied only when the drifted cycle still lasts at least 10 s.
- **Generation order:** cycle lengths are drawn first, and the LCM check runs before any pattern is
  written, because most draws are rejected. `MAX_ATTEMPTS` is now 100,000. 100 pieces generate in
  about 3 s.
- **Phasing minimum:** `MIN_DISTINCT_SPANS` drops to 3. At 50 bpm no four lengths in 9–13 beats
  realign within 6 minutes.
- **Piece length:** `--max-seconds` defaults to 360. Pieces run 1–6 minutes, median about 3.7.

## 21. Loop length split the difference (added 2026-10-20)

- **Why:** at 10–16 s the loops were hard to hear; at 2–8 s they had been too obvious.
- **Change:** `CYCLE_SECONDS` = 6–10 s (median about 7.9) and `SUSTAIN_NOTES` = 2–4. Each
  sustained note lasts at least `SUSTAIN_MIN_BEATS` = 3, so a short loop holds fewer, still-long
  notes.
- **Result:** pieces still run 1–6 minutes, median about 4, because more combinations of shorter
  loops realign within `--max-seconds`. Loops hold about 6 notes (median).

## 22. Milder panning (added 2026-10-20)

The seating changes from ±0.6 (with the horn far right) to a milder layout:

| flute | clarinet | bassoon | horn | oboe |
|---|---|---|---|---|
| −0.35 | −0.2 | −0.05 | +0.1 | +0.35 |

The high voices are spread apart and the horn and bassoon sit near the centre. It is still
constant-power panning.

## 23. No stuttering sustains (added 2026-10-20)

Problem: the bassoon in `piece_8` looped a 0.16 s middle of a 0.39 s recording 7 times to fill a
1.4 s note. The library's nominal lengths are also unreliable: `bassoon_G2_p_1.5s.wav` is actually
0.42 s.

- **Sample choice:** for a duration, `Instrument.note` uses actual lengths (`Sample.seconds`, read
  from the WAV header). It takes the shortest recording that covers the note at the nearest
  dynamic. If none covers it at any allowed dynamic, it takes the actually-longest recording,
  breaking ties by dynamic distance.
- **Looping:** `loopable()` allows a sustain loop only when the steady middle is at least
  `MIN_LOOP_SECONDS` = 0.8 s and the stretch needs at most `MAX_LOOP_REPEATS` = 3 repeats.
  Otherwise the sample plays once with its natural release and the note's remainder is silence.
  The hairpin or attack is applied over the sounding part.
- **Effect:** across the test pieces, about a third of the notes longer than their sample still
  loop (worst case 2.5 repeats of a 0.85 s middle). The rest now play once, then rest.
- **Compatibility:** existing piece files keep their patterns but may pick different recordings for
  long notes, so they are no longer byte-identical with earlier renders.

## 24. Deeper volume sines (added 2026-10-20)

`LFO_DEPTH_DB` goes from 6 to 12 dB, so at its quietest a voice is a quarter of its loudest
amplitude. Everything else in section 16 is unchanged.

## 25. Lower sine peaks (added 2026-10-20)

The sine's loudest point was too loud. `LFO_PEAK_DB` = −4 lowers the whole curve: gain is
`10^((LFO_PEAK_DB − LFO_DEPTH_DB · dip) / 20)`, from −4 to −16 dB. Voices with `lfo=0` stay at 0 dB.

## 26. Re-articulation, metric accents, mastering (added 2026-10-20)

- **Re-articulation:** `_rearticulate()` runs after repair.
  - `sustainable_frames(length)` is the longest note a recording can play: its length, plus
    `MAX_LOOP_REPEATS` loops of its middle when that middle is long enough.
  - A hold that would carry a note past its pitch's limit (for the actually-longest recording)
    becomes a repeated note on the same pitch. A single slot that is itself too long splits into
    equal repeated notes.
  - Silent note time drops from 9.1% to 0%.
  - Sustainer weights become flute 2.5, oboe 0.5, clarinet 3, horn 3, bassoon 1.
- **Metric accents:** `accents(pattern)` gives a dB value per event.
  - `_levels(n)` splits n slots into groups of 2 (one 3 if n is odd). Level 0 is the first slot,
    level 1 the group start nearest the middle, level 2 other group starts, level 3 everything
    else. A lone 3-group is `[0, 2, 3]`.
  - The dB sums `ACCENT_DB = (1.0, 0.6, 0.3, 0)` down the nesting, halved per level (at most about
    1.75 dB).
  - It is applied per note in `_note_audio`, which is cached.
- **Mastering** (`master.py`, `--master`, default on):
  - **EQ:** applied to each recording before levelling. It is linear, so this equals EQ'ing the
    mix at a fraction of the cost. It uses cascaded moving averages; measured response: −11 dB at
    60 Hz, −3 dB at 250–330 Hz, +3.5 to +4 dB at 3–4.5 kHz.
  - **Dynamics:** on 10 ms blocks.
    1. Pre-gain to `TARGET_LUFS` = −16.
    2. A 2:1 compressor from 8 dB below the target (20 ms attack, 300 ms release, circular
       envelope).
    3. Makeup back to the target.
    4. A −1 dBFS limiter: each block's gain is at most its own and its neighbours' peak limits,
       ramped linearly, so no sample exceeds the ceiling.
  - **Loudness:** approximately EBU R128 gating, without K-weighting.
  - **Stems** are not mastered.
- **Measured on `piece_9000`:** −35.7 → −14.9 LUFS, peak −16.8 → −1.0 dBFS, loud-to-quiet spread
  7.1 → 3.8 dB.

## 27. Moved to a proper project (2026-10-20)

The standard-library constraint is dropped. See `2026-10-20-proper-project-design.md`:

- a `src/quintet/` package managed by uv, with the `quintet` command;
- numpy rendering;
- pedalboard reverb, EQ, compression and limiting, with true LUFS from pyloudnorm.

The stdlib reverb (section 15) and mastering (section 26) are replaced. Generation is unchanged:
`tests/test_generation_parity.py` checks that 20 seeds generate the same pieces as before the move.

## 28. Long notes start quieter (added 2026-10-20)

Long-note hairpins felt tame. Instead of boosting the peak (rejected: the loudest point was already
loud enough), the rise is held back: the rising half of the sin² shape is raised to
`HAIRPIN_RISE_POWER` = 3. The note is −26 dB at 10% and −11 dB at 20% (it used to be about −6 dB at
10%), then reaches its full level at 40% as before. The peak and the fade are unchanged.

## 29. Volume sines start at their quietest (added 2026-10-20)

Generated voices use `lfo_phase = LFO_START_PHASE` = 0.5 instead of a random phase. Every voice's
sine starts at its trough (−16 dB). Because each sine fits a whole number of times into the piece,
it also ends there, so the piece opens softly and eases back down at the end without fading out,
and the loop point matches. The voices still drift apart in between, because their periods differ.
The random draw for the phase is gone, which changes later sine-period picks but no notes
(checked on all 100 fixture voices). The fixture was re-recorded with the new `make fixtures`
(`scripts/record_generation.py`).

## 30. Modes and a soft spacing rule (added 2026-10-20)

- **Why:** `sus9`, `maj69` and `min11` are all one pentatonic set, so about 38% of random pieces had
  no semitones or tritones at all. Random harmony becomes whole modes:
  `HARMONY_WEIGHTS = {lydian 3, dorian 3, mixolydian 2, major 2, minor 2, phrygian 1}` (no
  locrian). Modes have no non-chord tones, so those figures don't occur; chords remain available
  by name.
- **Spacing rule:**
  - `too_close(p, q)` applies `SPACING_FLOOR`, a low-interval-limit table per interval in
    semitones: m2 C5, M2 G4, m3 C3, M3 B♭2, P4 A2, TT C4, P5 B♭1, m6 to m7 F2, M7 C3. Intervals
    wider than an octave use the smaller form's limit minus 12; octaves, unisons and two octaves
    or more are free.
  - `clashes()` checks each note onset against the note every other voice is sounding at that
    moment.
- **Repair:** `_repair` minimises (parallels, clashes above `CLASHES_PER_MINUTE` × minutes)
  lexicographically, with `REPAIR_STEPS` = 150. Per-voice timelines are cached and only the
  nudged voice is rebuilt; the clash search uses float times.
- **Result:** across 30 pieces, a median of 0 and a maximum of 1.36 clashes per minute. Close
  2nds are rare (m2: 14 close against 473 spread), and tritones and M7s stay common where the
  register allows.

## 31. Legato phrasing (added 2026-10-20)

Every note used to play its recording from the start, tongued attack and all, so everything sounded
detached.

- **Phrases** are maximal runs of note events without a rest, computed over the tiled piece with
  wrap-around, so a phrase can span the loop point. Only a phrase's first note is articulated.
- **Joins** inside a phrase (`voice_line` / `_note_audio`):
  - **legato** (a new pitch): skip `max(LEGATO_SKIP_SECONDS = 60 ms, attack end)`, where attack end
    is the first 10 ms frame within 4 dB of the recording's loudest. Equal-power crossfade of
    `LEGATO_CROSSFADE_SECONDS` = 80 ms: the previous note renders 80 ms past its end, fading out.
  - **repeat** (the same pitch written again): the previous note fades out over 40 ms; the new one
    starts 30 ms in and rises over 80 ms. The start point is phase-aligned by normalised
    cross-correlation (`ALIGN_WINDOW` and `ALIGN_SEARCH` = 1024 frames). Result: an 8–10 dB dip of
    about 40 ms.
  - **renew** (`"3="`, new notation, written by `_rearticulate` for holds a recording can't carry):
    reuse the previous note's recording, start at `max(loop_bounds attack, attack end)`
    phase-aligned, and use a linear crossfade of `RENEW_CROSSFADE_SECONDS` = 150 ms (amplitudes add
    when aligned).
- **Hairpins:** a long note's floor is `HAIRPIN_LEGATO_FLOOR_DB` = −9 on a joined side and −30 on a
  phrase edge.
- **Recording choice:** a note with a join after it requests `beats + RELEASE_SECONDS` of
  recording, so it is still sustaining at the join.
- **Measured across instruments:** legato within 0.2–3.5 dB of level through the join; repeats dip
  8–10 dB; renewals within 0.5–2.9 dB.
- **Fixture:** re-recorded; the only change is renewals written as `"k="`, which was checked on all
  100 voices.

## 32. Humanised performance (added 2026-10-20)

To make it sound less robotic, `--humanize` (default on) varies the performance at render time;
generation and piece-file contents don't change. Every stream is `np.random.default_rng(crc32(key))`,
where the key is (instrument, pattern, beats, drift, dynamic, purpose). It is stable across runs, and
it indexes events over the whole tiled piece, so the variation differs each time round within a
piece but repeats with the loop.

- **Timing:** onset = grid + `ENSEMBLE_MS[instrument]` (flute −6, oboe +4, clarinet 0, horn +10,
  bassoon +6) + a normal(σ 10 ms) offset clipped to ±25 ms, in 2 ms steps. Each note ends where the
  next event starts.
- **Phrase ends:** a note followed by a rest is stretched by min(10% of the note, 0.2 s, half the
  rest).
- **Breaths** (`_breaths`): a phrase running past a uniform(4, 8) s target breathes at the next
  change of note (not before a renewal). The gap is uniform(0.15, 0.3) s, capped at half the
  previous note, taken off the previous note's end. That join becomes a phrase start (articulated).
- **Takes:** `Instrument.takes()` lists note()'s pick plus other recordings of the same pitch and
  dynamic at least as long. Each pitch rotates through them in order. Renewals keep the previous
  recording.
- **Level:** a normal(σ 0.5 dB) offset clipped to ±1 dB, in 0.25 dB steps, added to the accent.
- **Loop wrapping:** `_add_looped` writes note audio round the loop point in either direction, any
  number of times.

## 33. Intonation, tempo range, flags in make help (added 2026-10-20)

- **Intonation** (`--intonation`, default off): each note is retuned by a normal(σ 2 cents) offset,
  clipped to ±4 cents in 0.5-cent steps. It is seeded (purpose "intonation") and varies per event
  over the piece; a renewal copies its note's value. `retuned()` resamples with `np.interp` at
  `2^(cents/1200)`. A test checks ±4 cents to within 0.3 cents with an FFT peak.
- **Tempo:** `TEMPO_RANGE` becomes 55–75 bpm. The fixture was re-recorded, because tempos and the
  cycle lengths derived from them change.
- **Flags:** `make help` lists every quintet flag with its default. `tests/test_makefile.py` fails if
  any `Config` field (or the `--no-` form of a boolean) is missing from it.

## 34. Preset make targets and --count (added 2026-10-20)

- **`--count N`** (default 1): with `--seeds now`, makes N pieces. `seed_range()` yields seeds
  lazily: the first from the clock, then `claim_time_seed(after=previous)`, each claimed only when
  reached, so an interrupted run leaves no unused claims. With an explicit `--seeds`, `--count` is
  an error.
- **Presets:** `batch N=10` (`--count $(N)`); `lush` (`--intonation --reverb 0.45 --room 0.9`); `daw`
  (`--stems --code`); `raw` (`--no-humanize --no-master --reverb 0`). All append `$(ARGS)`, so
  later flags override.
- The user's own `loop` and `seam` targets (`scripts/loop.py`) were kept as they were.

## 34. Concert pitch (added 2026-10-20)

- **`--a4 HZ`** (default 440, the recordings' own pitch): every note is retuned by
  `1200·log2(a4/440)` cents (−31.8 at 432), added to its intonation offset in `voice_line`. Tempo is
  unchanged: each note is resampled before it is cut to length. At 440 the shift is 0 and nothing is resampled.

## 35. Every instrument capped at mp again (added 2026-10-20)

- `MAX_LAYERS` puts every instrument, not just the horn, at `mp`, as `MAX_LAYER` did before §18.
  The `mf` recordings sounded too bright against the soft quintet.
- Generated dynamics follow the cap, so every voice is now `p` or `mp`.
- Explicit louder dynamics still work: they level the `mp` (or softer) recording up with gain.
- `Instrument.playable` shrinks to pitches recorded at `mp` or softer.

## 36. A quieter, lower oboe (added 2026-10-20)

- `INSTRUMENT_TRIM_DB["oboe"]` is −3 dB, so it sits behind the others instead of on top.
- `SWEET["oboe"]` tops out at Cs6 instead of D6, away from the piercing top. A5 or C6 would be
  better, but the oboe has few `mp`-or-softer recordings around C5–Ds5 (and none of C6's
  neighbours below Cs6 help), so some chords would leave it fewer than three notes.

## 37. Intonation on by default (added 2026-10-20)

- `--intonation` defaults to on; `--no-intonation` turns it off.
- `make lush` no longer passes `--intonation`; `make raw` adds `--no-intonation`.

## 38. Space after long tones (added 2026-10-20)

- With `--humanize`, a tone held `SUSTAIN_MIN_BEATS` (3) beats or more, counting its renewals, that
  runs straight into another note ends `PHRASE_GAP_SECONDS` (0.3–0.6 s, seeded) early, capped at
  half its last event. The next note is re-articulated, as after a breath.
- It goes through `_breaths`, so it repeats with the piece and also covers the loop point.
- A long tone that already ends on a rest is unchanged (the rest is the pause).

## 39. More space in generated lines (added 2026-10-20)

Before this, about 4.6 of the 5 voices sounded at any moment (each 85–95% of the time): a wall of
notes. Now about 3.7 do.

- `P_CELL_END_REST` (0.7): a moving line's phrase cell of 3+ slots ends on a rest.
- `P_SILENT_CELL` (0.25): a cell after the first is a single rest, so the voice sits out a phrase.
- Sustaining voices: `P_SUSTAIN_REST` rises from 0.3 to 0.6 and the closing rest is
  `SUSTAIN_REST_BEATS` (1–2) beats, as long as two sustained notes still fit.
- A test keeps the average below 4.2 voices at once (seeds 0–19, C lydian, 62 bpm).

## 40. A staged room: depth, reflections, a convolution hall, air and warmth (added 2026-10-20)

- **`--reverb` defaults to 0.5** (was 0.3); `make lush` uses 0.7 so it stays the wetter preset.
- **Stage depth** (`STAGE_DEPTH` in `render.py`): flute and oboe 0, clarinet 0.4, bassoon 0.6,
  horn 1. `effects.place` delays a voice by up to `DEPTH_DELAY_MS` (6 ms) and darkens it with a
  4 kHz high shelf of up to −4 dB; `send_gain` sends up to 4 dB more of it to the hall.
- **Horn +1.5 dB** (`INSTRUMENT_TRIM_DB`), so it carries from the back.
- **Early reflections** (`effects.reflections`): five taps at 9–38 ms, −14 to −21 dB, alternating
  walls, skewed by pan and squeezed by depth, lowpassed at 6 kHz as one bus. Part of the room:
  only with `--reverb` above 0.
- **`mix` returns `(dry, early, send)`**, and `finish(dry, config, early, send)` adds the room.
- **Convolution hall** (`effects.impulse_response`), replacing pedalboard's `Reverb`: octave-band
  noise, each band decaying at `HALL_DECAY_RATIO` times an RT60 of 0.6–3.1 s from `--room`, with a
  12 ms onset. `--reverb-ir` loads a recorded impulse response instead (resampled, mono doubled).
  Either is high-passed at 250 Hz and low-passed at 7 kHz (12 dB/octave), pre-delayed 25 ms and
  scaled to unit energy per channel. Each side of the hall hears half of the other
  (`REVERB_CROSSFEED`).
- **Circular convolution** by FFT (a 5-smooth length), so the tail wraps over the loop point
  exactly; a hall longer than the piece is folded onto it. About 1.5–3.5 s for a 150–340 s piece.
- **`REVERB_WET_SCALE` 0.2:** on seeds 7, 12 and 31 an amount's wet-to-dry loudness is within
  about 2 LU of the old hall's.
- **Mastering:** a +1.5 dB high shelf at 10 kHz joins the EQ, then `--saturation` (default 0.3)
  applies `tanh(d·x)/d` with `d = 3 × amount`, before the compressor. Piece files record
  `saturation` (and `reverb_ir` when set).

## 41. One shared eighth-note pulse (added 2026-10-20)

Before this, only 57% of generated onsets fell on an eighth-note grid: each cycle was split into
equal (often fractional) phrase cells, each cut into 2–6 slots at random, giving notes every 0.8,
1.25 or 1.75 beats, plus triplet figures and `[b, n, b]` neighbours. Nothing shared a pulse, and
pieces sounded like random notes. Now 100% do.

- **`_pattern` writes one slot per beat** (`len(pattern) == beats`), so phasing comes only from
  cycle lengths. Phrase cells are whole beats drawn from `Profile.beats`, at least two per cycle,
  with no cell shorter than the profile's minimum (the last absorbs the remainder). A silent cell
  is `[0, _, ...]`.
- **`_cell(walk, size, first)`:** each beat is a hold, rest, figure or note by the profile's
  per-beat `hold`, `rest` and `split`. `Profile.slots` is gone. A closing rest
  (`P_CELL_END_REST`) is reserved before filling, so a neighbour or passing tone is never cut off
  before it resolves.
- **Figures are eighths** (`_eighths`): pairs per beat, an odd last note taking the whole beat,
  capped by `_Walk.figure(most)` to the cell's room.
- **Neighbours** are `[b, n]` then `b` on the next beat; **passing tones** stay `[a, passing]`.
- **No drift in generation:** `DRIFT_CHANCE`, `DRIFTS` and `MAX_DRIFTING` are gone. `Voice.drift`
  and `voice(..., drift=k)` stay for hand-written pieces.
- **Renewals** (`"k="`) may still split a beat finer when a recording can't hold a note, but they
  carry on the same note seamlessly, with no new attack, so they don't affect rhythm.
- Density is about the same: 3.72 voices sounding at once (was 3.75), 0.4–0.7 onsets per beat
  per instrument. The generation fixture is re-recorded.

## 42. Longer loops again, an 8-minute cap (added 2026-10-21)

- **Why:** with every voice on one pulse (section 41) the patterns are clear, and 6–10 s loops
  came round too soon.
- **Change:** `CYCLE_SECONDS` = 8–13 s and `--max-seconds` defaults to 480 (was 360).
- **Why the cap moved:** with whole-beat loops and no drift, three different loop lengths of
  8–13 s can't all realign within 360 s at some tempos (55, 61–65, 68, 69 bpm). The old 10–16 s
  would need about 600 s.
- **Result:** over 60 seeds every tempo fits; pieces run 0.8–8 min, median about 5.5.
- **Oboe −4.5 dB** (`INSTRUMENT_TRIM_DB`, was −3): with clearer lines it still stuck out.

## 43. Cut-only levelling (added 2026-10-21)

- **Why:** levelling boosted most recordings to reach its target: flute by a median 12.5 dB (up to
  24.7), horn 10 (up to 18), some oboe and bassoon ones up to about 14. Samples should only ever be
  turned down.
- **`LEVEL_REF_DB` = −61** (was −24): with `ff`, the biggest metric accent (`2 × ACCENT_DB[0]`, a
  bound on the nested sum) and `LEVEL_LIMIT_DB` on top, every usable recording's gain is at most
  0 dB; the quietest flute recordings need −60.2, so about 1 dB is spare. A test checks every
  recording.
- **`INSTRUMENT_TRIM_DB` rebased to cuts**, same balance: horn 0, flute, clarinet and bassoon −1.5,
  oboe −6.
- **`master()` scales the mix to full-scale peak first**, so pyloudnorm's absolute gate (−70 LUFS)
  still hears its quiet passages. Seed 7 at 64 bpm masters identically: −15.98 LUFS and −5.22 dBFS
  peak before and after, the difference 88 dB down (16-bit rounding).
- **Stems and `--no-master` mixes are written as 32-bit float** (`write_wav(..., floating=True)`):
  they now peak around −60 dBFS, which 16 bits would coarsen. The mastered mix stays 16-bit.

## 44. Quartal harmony, fewer minor modes (added 2026-10-21)

- **Why:** the minor modes (46% of random picks) and the horn spelling out each mode's triad
  sounded too much like textbook Western harmony. Lydian stays the favourite; the variation
  should come from tonal ambiguity.
- **`HARMONY_WEIGHTS`:** lydian 4, `quartal` 2, `quartal_bright` 2, mixolydian 1.5, dorian 1.5,
  major 1. Minor and phrygian leave the random menu (still usable by name). A minor 3rd now
  appears in about 12% of picks.
- **Quartal sets** (`QUALITIES`): chains of perfect 5ths, i.e. stacked 4ths. `quartal` (0, 2, 5,
  7, 10) has the root mid-stack; `quartal_bright` (0, 2, 4, 7, 9) has it at the bottom.
- **Their voicing** (`CORES`): the horn's core is the 3rd-free stack, (0, 2, 5, 7) and (0, 2, 7,
  9); the bassoon keeps root and 5th; modes keep the horn on their triad. Parent scales
  (`PARENT_SCALES`): mixolydian and lydian.
- **Tests:** random picks never include minor, phrygian or locrian and keep minor 3rds under 20%;
  both sets are unbroken chains of 5ths with no 3rd in their core; on every root the horn's and
  bassoon's palettes for a quartal set hold no 3rd. The generation fixture is re-recorded.
- `LfoTest.test_generated_sines_are_slow_and_out_of_step` now passes its own 60 bpm config, so it
  no longer depends on which test ran before it.

## 45. A wetter, longer hall by default (added 2026-10-22)

- **Why:** the default room sounded too dry.
- **`--reverb` defaults to 0.75** (was 0.5): about 3.5 dB more hall.
- **`--room` defaults to 0.9** (was 0.8): RT60 about 2.85 s (was 2.6).
- **`make lush`** moves to `--reverb 1.0 --room 1.0` (RT60 about 3.1 s), so it stays the wetter preset.

## 46. Firmer compression, peaks at −3 dBFS (added 2026-10-22)

- **Why:** at −16 LUFS the mastered pieces peaked at only −4 to −6 dBFS, so the −1 dB limiter never
  engaged; the mix wanted a little more compression and peaks at −3 dBFS.
- **More compression on its own lowers the peaks** at a fixed loudness, so the target rises too
  and the limiter sets the ceiling.
- **`COMP_RATIO` 3** (was 2), **`COMP_BELOW_TARGET` 10 dB** (was 8), **`TARGET_LUFS` −13** (was
  −16), **`CEILING_DB` −3** (was −1).
- **Measured** over seeds 7, 8 and 9: −12.3 to −12.6 LUFS (the limiter adds a little), peaks −3.0
  to −3.8 dBFS, short-term loudness range 2.3–4.4 LU (was 3.4–6.0).

## 47. Dorian off the random menu, for now (added 2026-10-22)

- **`HARMONY_WEIGHTS`** drops dorian (was 1.5): lydian 4, `quartal` 2, `quartal_bright` 2,
  mixolydian 1.5, major 1. No random pick has a minor 3rd now.
- `--notes D.dorian` still works by name; put it back in `HARMONY_WEIGHTS` to restore it.
- **Tests:** random picks never include dorian, minor, phrygian or locrian, and none holds a minor
  3rd. The generation fixture is re-recorded.

## 48. A wider tempo range (added 2026-10-22)

- **`TEMPO_RANGE`** is 60–85 bpm (was 55–75), still a whole number, random per seed: faster at the
  top, and nothing below 60 now that the hall is longer and the mix more compressed.
- Loop lengths stay 8–13 s, so a faster piece fits more beats into each loop.
