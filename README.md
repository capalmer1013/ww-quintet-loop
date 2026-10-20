# ww-quintet-loop

Generate small phasing pieces for woodwind quintet (flute, oboe, clarinet, horn, bassoon). Each
voice cycles its own pattern of notes, drawn from one note set, over its own time span. The voices
drift in and out of phase to make a polyrhythmic chord cloud. Each piece lasts exactly one full
phase cycle, so it loops seamlessly.

- `main.py`: generates one piece per seed.
- `utils/`: theory, patterns, voices, sample loading and rendering.
- `samples/`: the sample library.

These three are everything needed to run it. Python 3.10+ only, with no dependencies.
`tests/`, `docs/` and the `Makefile` are for development.

## Running

```bash
make run ARGS="--notes C.lydian --seeds 1000-1010 --code"
```

This writes `out/piece_1000.wav` … `out/piece_1009.wav`, plus a `.py` file for each piece.
Run `make` to list the targets, and `make run ARGS="--help"` for every flag.

| Flag | Default | Meaning |
|---|---|---|
| `--notes` | `C.maj7s11` | Note set: `<root>.<quality>`, e.g. `C.lydian`, `Fs.maj7s11`, `Bb.dom7` |
| `--seeds` | `0` | Seed `A`, or a range `A-B` with `B` excluded. One piece per seed |
| `--tempo` | `60` | Beats per minute |
| `--max-seconds` | `180` | Longest allowed piece (one full phase cycle) |
| `--output-dir` | `out` | Where files are written |
| `--stems` | off | Also write `piece_<seed>_<instrument>.wav` (mono) for each voice |
| `--code` | off | Also write `piece_<seed>.py`, which reproduces the piece |
| `--sample-root` | `samples/` | Sample library location |

Flags override any defaults set in code. Every field on `utils.Config` is a flag automatically.

## Piece files

With `--code`, each piece is also written as a script:

```python
from utils import *

Config(tempo=120.0)
render('piece_2000', C.lydian,
    flute    = voice([6, 0, 5], beats=4, dynamic='mp'),
    oboe     = voice([2, 3, 4], beats=6),
    clarinet = voice([1, _, _, _, _, _, 3, _, _], beats=9, drift=8),
    horn     = voice([1, _, _, 3], beats=4),
    bassoon  = voice([7, _, _, _, _, 3, _, _, _, 3, _, _, _, _, 0], beats=15, drift=8, dynamic='mp'),
)
```

- Running `python3 out/piece_2000.py` rebuilds the identical WAV.
- Flags still apply, e.g. `--stems` or `--tempo 90`.
- Edit the file to change a piece by hand.

## Voices

`voice(pattern, beats, drift=0, dynamic="p")` repeats `pattern` every `beats` beats.

- **Cycle-length phasing:** give voices different `beats` (3 against 4 against 7).
- **Different note counts in the same time:** 5 slots over `beats=4` against 4 over 4 gives 5:4.
- **Reich-style drift:** `drift=k` shortens the cycle to `beats * k/(k+1)`. The voice slowly pulls
  ahead and realigns with an undrifted partner after `k+1` of its own cycles.
- **Dynamic:** one of `pp p mp mf f ff`, setting the voice's level.
  - No recording louder than `mp` is ever used. A louder dynamic is reached by levelling (gain),
    keeping the soft tone.
  - A note without that recording falls back to the nearest softer one.
- **Piece length:** the lowest common multiple of the five cycle lengths, so every voice realigns
  exactly at the end.
- **Sounding:** voices are monophonic, so every note lasts until the next event starts.
  - A sample longer than the note is cut, with a fade of 10% of the note (10–150 ms).
  - A note longer than its sample is sustained: the sample's attack plays first, then its steady
    middle repeats with 100 ms crossfades, and its natural release ends the note.
  - **Long notes** (1.5 s or more) swell `<>`: they rise from about −30 dB to full level 40% of
    the way through the note, then die away.
  - **Shorter notes** fade in over 0.08 of a beat (80 ms at 60 bpm), so slower tempos get softer
    attacks.

## Patterns

| Element | Meaning |
|---|---|
| `1`, `2`, … | The voice's palette notes, lowest first. Numbers past the end wrap round |
| `0` | Rest |
| `_` | Hold the previous note (or rest) through this slot |
| `[...]` | Divide this slot equally among its elements, to any depth |

- `[1, [2, 3], _, 0]` over 4 beats: note 1, then two half-beat notes, then 2 beats of hold on the
  last note (3), then a rest.
- A leading `_` continues the previous cycle's last note.

## Palettes and spacing

Each voice draws only from the set's notes within its own register band:

1. Take a fundamental on the set's root, near C2.
2. Centre the voices on its partials 2, 3, 4, 6 and 8, from bassoon up to flute.
3. Each voice's band runs halfway to its neighbours' centres.

Low voices end up an octave or a fifth apart, and higher ones closer together, loosely following
the harmonic series. For `C.maj7s11` that gives:

| Voice | Palette |
|---|---|
| bassoon | C2–C3 |
| horn | E3–G3 |
| clarinet | B3–E4 |
| oboe | E4–G4 |
| flute | B4–C6 |

The constants are at the top of `utils/voice.py`.

## Generation

`generate(seed, notes)` writes each voice in its instrument's idiom. The `PROFILES` table in
`utils/voice.py` holds these:

- **Melodic walk:** each note moves from the previous one by a weighted repeat, step (next palette
  note), skip (two palette notes) or leap.
- **Quick figures:** an occasional subdivision in the instrument's own style.
- **Breathing:** rests and holds.
- **Cycle length:** the instrument's own range of beats.

| | Moves | Quick figures | Character |
|---|---|---|---|
| flute | mostly steps | 3–4-note scale runs | busiest, few rests |
| oboe | steps | stepwise pairs | lyrical, breathes often |
| clarinet | skips | arpeggios | smooth, sustains often |
| horn | repeated notes, skips | repeated notes | favours root and 5th; sustains often |
| bassoon | leaps, octaves | octave/leap bounces | favours the root |

On top of that:

- 1–2 voices per piece sustain 2–3 long notes (3–6 beats each). They're chosen weighted towards
  horn and clarinet.
- Up to two voices drift.
- Each voice's dynamic is `p` or `mp`.

It redraws, deterministically for that seed, until the piece fits `--max-seconds` and has at least
4 different cycle lengths, so the voices genuinely phase.

## Theory helpers

```python
C + 7 == G;  As == Bb
C.maj7s11, C.lydian, G.dom7, D.min7, A.pentatonic_minor     # PitchSet
C.maj.up(P4) == F.maj;  C.maj.fifths(1) == G.maj;  C.maj.fourths(2) == Bb.maj
fifths(C, 4) == [C, G, D, A];  fourths(C.dom7, 3) == [C.dom7, F.dom7, Bb.dom7]
C.maj7s11.pitches(60, 72) == [60, 64, 66, 67, 71, 72]       # MIDI numbers in range
```

- Chords: `maj min dim aug sus2 sus4 dom7 maj7 min7 dim7 m7b5 maj7s11`
- Scales: `major minor dorian phrygian lydian mixolydian locrian harmonic_minor
  pentatonic_major pentatonic_minor whole_tone`
- Intervals: `m2 M2 m3 M3 P4 TT P5 m6 M6 m7 M7`

## Sample library

```
samples/<instrument>/notes/<dynamic>/<instrument>_<note>_<dynamic>_<length>.wav
samples/<instrument>/extended/<technique>/<instrument>_<note>_<technique>_<dynamic>_<length>.wav
```

- Notes use `s` for sharp (`As1` = A♯1).
- Dynamics are `pp p mp mf f ff`.
- Lengths are `0.25s 0.5s 1s 1.5s long very-long`.
- Pieces use only `notes/`. For each note, the sample used is the shortest recording that covers
  the note's duration.
- Not every instrument has every dynamic; for example, the clarinet has no `mf` or `mp`.
- **Levelling:** the recordings' levels differ by up to about 14 dB between instruments, so every
  sample is scaled until its loudest 0.3 s reaches a target for the dynamic it's playing:
  `mf` = −24 dBFS RMS, `pp` −12 dB, `p` −8 dB, `mp` −4 dB, `f` +3 dB, `ff` +6 dB.
  `INSTRUMENT_TRIM_DB` in `utils/render.py` adjusts each instrument by ear.

## Development

```bash
make test
```
