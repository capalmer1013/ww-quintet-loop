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
