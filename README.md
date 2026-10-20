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
make run ARGS="--seeds 1000-1010 --code"
```

This writes `out/piece_1000.wav` … `out/piece_1009.wav`, plus a `.py` file for each piece. Each seed
picks its own key, chord and tempo; each printed line shows them.
Run `make` to list the targets, and `make run ARGS="--help"` for every flag.

| Flag | Default | Meaning |
|---|---|---|
| `--notes` | `random` | `random` (key and chord), `C.random` (chord on that key) or a fixed set like `C.maj9`, `Fs.maj7s11`, `Bb.lydian` |
| `--seeds` | `0` | Seed `A`, or a range `A-B` with `B` excluded. One piece per seed |
| `--tempo` | `0` | Beats per minute; `0` = a whole-number tempo from 50 to 70, random per seed |
| `--reverb` | `0.3` | Hall reverb amount (`0` = dry) |
| `--room` | `0.8` | Hall size, 0–1 (`0.8` ≈ 2.6 s decay) |
| `--max-seconds` | `360` | Longest allowed piece (one full phase cycle) |
| `--output-dir` | `out` | Where files are written |
| `--stems` | off | Also write `piece_<seed>_<instrument>.wav` (mono) for each voice |
| `--code` | off | Also write `piece_<seed>.py`, which reproduces the piece |
| `--sample-root` | `samples/` | Sample library location |

Flags override any defaults set in code. Every field on `utils.Config` is a flag automatically.

## Piece files

With `--code`, each piece is also written as a script:

```python
from utils import *

Config(tempo=60.0, reverb=0.3, room=0.8)
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

`voice(pattern, beats, drift=0, dynamic="p", lfo=0, lfo_phase=0.0)` repeats `pattern` every `beats` beats.

- **Cycle-length phasing:** give voices different `beats` (3 against 4 against 7).
- **Different note counts in the same time:** 5 slots over `beats=4` against 4 over 4 gives 5:4.
- **Reich-style drift:** `drift=k` shortens the cycle to `beats * k/(k+1)`. The voice slowly pulls
  ahead and realigns with an undrifted partner after `k+1` of its own cycles.
- **Dynamic:** one of `pp p mp mf f ff`, setting the voice's level.
  - Recordings are capped per instrument (`MAX_LAYERS` in `utils/samples.py`): flute, oboe,
    clarinet and bassoon go up to `mf`, and the horn only to `mp`, so it blends instead of turning
    brassy. A louder dynamic is reached by levelling (gain), keeping the softer tone.
  - A note without that recording falls back to the nearest softer one.
- **Volume sine:** `lfo=k` makes the voice's volume ebb and flow on a slow sine, `k` cycles over the
  whole piece, starting at `lfo_phase` (0 = loudest).
  - The dip is 6 dB.
  - Generated voices get periods of about 10–30 s, chosen not to line up with the voice's own
    cycle, so each repeat of a pattern sounds a little different.
  - It's whole cycles over the piece, so loops stay seamless.
  - `lfo=0` keeps the volume steady.
- **Piece length:** the lowest common multiple of the five cycle lengths, so every voice realigns
  exactly at the end.
- **Sounding:** voices are monophonic, so every note lasts until the next event starts.
  - A sample longer than the note is cut, with a fade of 10% of the note (10–150 ms).
  - A note longer than its sample is sustained: the sample's attack plays first, then its steady
    middle repeats with 100 ms crossfades, and its natural release ends the note.
  - **Long notes** (1.5 s or more) swell `<>`: they rise from about −30 dB to full level 40% of
    the way through the note, then die away.
  - **Shorter notes** fade in over 0.15 of a beat (150 ms at 60 bpm), so slower tempos get softer
    attacks.

## Reverb

The stereo mix goes through a Freeverb-style hall reverb, written in plain Python:

- **Design:** the mixed signal (one channel) feeds 6 echo-building filters with gentle
  high-frequency damping, then 2 smoothing filters per side for a wide stereo image. A 20 ms
  pre-delay keeps the dry notes clear.
- **Seamless loops:** the reverb is fed the piece's own ending before its start, so the tail rings
  over the loop point exactly as it does when the file repeats.
- **Speed:** it runs at half the sample rate, adding about 10 s to a 2-minute piece.
- **Stems stay dry**, for mixing elsewhere.
- `--reverb 0` gives exactly the dry mix.

## Patterns

| Element | Meaning |
|---|---|
| `1`, `2`, … | The voice's palette notes, lowest first. Numbers past the end wrap round |
| `"3+"`, `"3-"` | Palette note 3 moved one step up/down the chord's parent scale (a non-chord tone) |
| `0` | Rest |
| `_` | Hold the previous note (or rest) through this slot |
| `[...]` | Divide this slot equally among its elements, to any depth |

- `[1, [2, 3], _, 0]` over 4 beats: note 1, then two half-beat notes, then 2 beats of hold on the
  last note (3), then a rest.
- A leading `_` continues the previous cycle's last note.
- `[1, ["3-", 3], 5]`: note 1, then a passing tone stepping up into note 3, then note 5.

## Harmony

With `--notes random`, each seed picks a key (all 12) and an extended chord. The weights lean
towards the lush and consonant:

| Chord | On C | Weight |
|---|---|---|
| `maj9` | C E G B D | 3 |
| `maj69` | C E G A D | 3 |
| `min9` | C E♭ G B♭ D | 3 |
| `min11` | C E♭ G B♭ F | 2 |
| `sus9` | C F G B♭ D | 2 |
| `maj7s11` | C E F♯ G B | 2 |
| `min69` | C E♭ G A D | 1.5 |
| `dom9` | C E G B♭ D | 1.5 |
| `dom7s11` | C E F♯ G B♭ | 1 |

- **Separate streams:** the harmony and the tempo each come from their own random stream for the
  seed. Fixing one (e.g. `--tempo 60`) doesn't change what the seed picks for the other.
- **Weights:** `HARMONY_WEIGHTS` in `utils/theory.py` sets them.

## Non-chord tones and voice leading

Each chord has a parent scale that supplies its non-chord tones (`PitchSet.scale`):

| Chords | Parent scale |
|---|---|
| `maj9`, `maj69` | major |
| `maj7s11` | lydian |
| `min9`, `min11`, `min69` | dorian |
| `sus9`, `dom9` | mixolydian |
| `dom7s11` | lydian dominant |

Generated lines use them in three classical figures. Each instrument's profile sets how often
(`passing`, `neighbour`, `suspension`):

- **Passing tone:** a skip of a 3rd between chord tones is filled with the scale step between them
  on the weak half of the slot, e.g. `[2, "2+"]` then 3.
- **Neighbour tone:** a step away and straight back, `[3, "3+", 3]`.
- **Suspension:** a sustained note starts on the step above a chord tone, is held, then resolves
  down by step onto it, `["3+", _, _, 3, _, _]`. This is mostly the horn, oboe and clarinet. With
  one chord per piece there's no preparation in strict classical terms; it sounds like a held
  appoggiatura.

Generated pieces have no parallel perfect 5ths or octaves:

- **The rule:** no two voices may move at the same moment from a 5th, octave or unison apart into
  the same interval again, whether in similar or contrary motion.
- **Enforcement:** `generate` checks the whole looping timeline. It nudges offending notes to a
  neighbouring palette note, never touching a non-chord-tone figure, and moves on to another
  candidate if the parallels can't be cleared.
- **Checking a piece:** `parallels(voices, notes)` lists any parallels in a set of voices, including
  hand-written ones.

## Palettes and spacing

Each voice draws only from the set's notes within its own register band:

1. Take a fundamental on the set's root, near C2.
2. Centre the voices on its partials 2, 3, 4, 6 and 8, from bassoon up to flute.
3. Each voice's band runs halfway to its neighbours' centres.

Low voices end up an octave or a fifth apart, and higher ones closer together, loosely following
the harmonic series.

Voicing keeps the colour notes up top, as in classical scoring, to limit dissonance:

- The bassoon plays only the root and 5th.
- The horn plays only core chord tones (root, 3rd or sus, 5th, 7th or 6th).
- The 9ths, 11ths and 13ths go to the clarinet, oboe and flute.
- Palettes only use pitches the instrument has recorded at or below its cap.

For `C.maj9` that gives:

| Voice | Palette |
|---|---|
| bassoon | C2 G2 C3 |
| horn | E3 G3 B3 |
| clarinet | B3 C4 D4 |
| oboe | D4 E4 G4 B4 |
| flute | B4 C5 D5 E5 G5 B5 C6 |

The constants are at the top of `utils/voice.py`.

## Generation

`generate(seed, notes)` writes each voice in its instrument's idiom. The `PROFILES` table in
`utils/voice.py` holds these:

- **Melodic walk:** each note moves from the previous one by a weighted repeat, step (next palette
  note), skip (two palette notes) or leap.
- **Quick figures:** an occasional subdivision in the instrument's own style.
- **Breathing:** rests and holds.
- **Loop length:** every voice's loop lasts 10–16 s at the piece's tempo, strung from several
  phrase cells (each about the instrument's own cell length) so the lines are long and don't
  repeat too often.

| | Moves | Quick figures | Character |
|---|---|---|---|
| flute | mostly steps | 3–4-note scale runs | busiest, few rests |
| oboe | steps | stepwise pairs | lyrical, breathes often |
| clarinet | skips | arpeggios | smooth, sustains often |
| horn | repeated notes, skips | repeated notes | favours root and 5th; sustains often |
| bassoon | leaps, octaves | octave/leap bounces | favours the root |

On top of that:

- 1–2 voices per piece sustain 3–5 long notes (2 beats or more each) across their loop. They're
  chosen weighted towards horn and clarinet.
- Up to two voices drift, but only where the loop still lasts at least 10 s.
- Each voice's dynamic runs from `p` up to its instrument's cap: `p`–`mf` for the woodwinds and
  bassoon, and `p`–`mp` for the horn.
- Each voice gets a volume sine with its own period and starting point.

It redraws, deterministically for that seed, until the piece fits `--max-seconds` and has at least
3 different loop lengths, so the voices genuinely phase. Long, nearby loop lengths (say 12 against
15 s) slide past each other slowly, Reich-style. Pieces run about 1–6 minutes (median about 3.7).

## Theory helpers

```python
C + 7 == G;  As == Bb
C.maj7s11, C.lydian, G.dom7, D.min7, A.pentatonic_minor     # PitchSet
C.maj.up(P4) == F.maj;  C.maj.fifths(1) == G.maj;  C.maj.fourths(2) == Bb.maj
fifths(C, 4) == [C, G, D, A];  fourths(C.dom7, 3) == [C.dom7, F.dom7, Bb.dom7]
C.maj7s11.pitches(60, 72) == [60, 64, 66, 67, 71, 72]       # MIDI numbers in range
```

- Chords: `maj min dim aug sus2 sus4 dom7 maj7 min7 dim7 m7b5`
- Extended chords: `maj9 maj69 min9 min11 sus9 min69 dom9 maj7s11 dom7s11`. `s.core` gives a
  chord's tones without its colour notes, and `s.bass` its root and 5th.
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
