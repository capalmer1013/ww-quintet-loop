# ww-quintet-loop

Generate small phasing pieces for woodwind quintet (flute, oboe, clarinet, horn, bassoon). Each
voice cycles its own pattern of notes, drawn from one note set, over its own number of beats, all
on one shared eighth-note pulse. Loops of different lengths drift in and out of phase to make a
slowly shifting chord cloud. Each piece lasts exactly one full
phase cycle, so it loops seamlessly.

- `src/quintet/`: the package: theory, patterns, voices, sample loading, rendering and effects, plus
  the `quintet` command.
- `samples/`: the sample library.
- `tests/`, `docs/`: tests and design notes.

It's a [uv](https://docs.astral.sh/uv/) project for Python 3.10–3.13. Rendering uses numpy, effects
use [pedalboard](https://github.com/spotify/pedalboard), and loudness uses
[pyloudnorm](https://github.com/csteinmetz1/pyloudnorm).

## Running

Install once:

```bash
make sync
```

Then `make run` on its own makes one new piece, seeded from the clock. Or generate a range of seeds:

```bash
make run ARGS="--seeds 1000-1010 --code"
```

This writes `out/piece_1000.wav` … `out/piece_1009.wav`, plus a `.py` file for each piece. Each seed
picks its own key, chord and tempo; each printed line shows them.
Run `make` to list the targets and every flag.

Presets for common jobs (each takes `ARGS` too, and later flags win):

| Command | Makes |
|---|---|
| `make batch N=10` | N new pieces in one run (one startup instead of N) |
| `make lush` | the warmest sound: a little more reverb, a bigger hall |
| `make daw` | a piece plus per-instrument stems and its piece file, for mixing elsewhere |
| `make raw` | humanizing, intonation, mastering and reverb off, for A/B comparisons |

For example, `make lush ARGS="--count 5"` makes five lush pieces.

| Flag | Default | Meaning |
|---|---|---|
| `--notes` | `random` | `random` (key and chord), `C.random` (chord on that key) or a fixed set like `C.maj9`, `Fs.maj7s11`, `Bb.lydian` |
| `--seeds` | `now` | Seed `A`, a range `A-B` with `B` excluded, or `now`: one piece seeded from the current Unix time in hundredths of a second |
| `--count` | `1` | With `--seeds now`: how many new pieces to make (each gets the next free clock seed) |
| `--tempo` | `0` | Beats per minute; `0` = a whole-number tempo from 55 to 75, random per seed |
| `--reverb` | `0.5` | Hall reverb amount (`0` = dry) |
| `--room` | `0.8` | Hall size, 0–1 (`0.8` ≈ 2.6 s decay) |
| `--reverb-ir FILE` | none | An impulse response WAV of a real space (any rate, mono or stereo), used instead of the built-in hall (see Reverb) |
| `--humanize` / `--no-humanize` | on | Play it like people: timing, breaths, varied takes and levels (see Performance) |
| `--intonation` / `--no-intonation` | on | Each note tuned a few cents off, differently every time (see Performance) |
| `--a4 HZ` | 440 | Concert pitch. The samples are recorded at A440, so the default plays them as recorded; `--a4 432` plays everything about 32 cents flat |
| `--master` / `--no-master` | on | Phone-friendly EQ, compression and −16 LUFS loudness (see Mastering) |
| `--saturation` | `0.3` | Gentle tape-style warmth when mastering (`0` = clean) |
| `--max-seconds` | `360` | Longest allowed piece (one full phase cycle) |
| `--output-dir` | `out` | Where files are written |
| `--stems` | off | Also write `piece_<seed>_<instrument>.wav` (mono) for each voice |
| `--code` | off | Also write `piece_<seed>.py`, which reproduces the piece |
| `--sample-root` | `samples/` | Sample library location |

Flags override any defaults set in code. Every field on `quintet.Config` is a flag automatically.
`make run` wraps `uv run quintet`, which you can also call directly.

### Listening on loop

Each file's last frame runs straight into its first, but most players (VLC 3 included) restart the
file to loop it, which leaves a short gap. To avoid that, repeat the piece into one long file:

```bash
make loop FILE=out/piece_1000.wav MINUTES=60
```

This writes `out/piece_1000_loop.flac`. To hear just the join, `make seam FILE=out/piece_1000.wav`
writes the piece's last 10 s followed by its first 10 s. Both also print whether the join is clean.

## Piece files

With `--code`, each piece is also written as a script:

```python
from quintet import *

Config(tempo=60.0, reverb=0.5, room=0.8, master=True, saturation=0.3, humanize=True, intonation=True, a4=440.0)
render('piece_2000', C.lydian,
    flute    = voice([6, 0, 5], beats=4, dynamic='mp'),
    oboe     = voice([2, 3, 4], beats=6),
    clarinet = voice([1, _, _, _, _, _, 3, _, _], beats=9, drift=8),
    horn     = voice([1, _, _, 3], beats=4),
    bassoon  = voice([7, _, _, _, _, 3, _, _, _, 3, _, _, _, _, 0], beats=15, drift=8, dynamic='mp'),
)
```

- Running `uv run python out/piece_2000.py` rebuilds the identical WAV.
- Piece files from before the move to the `quintet` package (`from utils import *`) no longer run.
  Regenerate them with the same seeds: the notes come out the same.
- Flags still apply, e.g. `--stems` or `--tempo 90`.
- Edit the file to change a piece by hand.

## Voices

`voice(pattern, beats, drift=0, dynamic="p", lfo=0, lfo_phase=0.0)` repeats `pattern` every `beats` beats.

- **Cycle-length phasing:** give voices different `beats` (3 against 4 against 7).
- **Different note counts in the same time:** 5 slots over `beats=4` against 4 over 4 gives 5:4.
- **Reich-style drift:** `drift=k` shortens the cycle to `beats * k/(k+1)`. The voice slowly pulls
  ahead and realigns with an undrifted partner after `k+1` of its own cycles.
- **Dynamic:** one of `pp p mp mf f ff`, setting the voice's level.
  - Recordings are capped per instrument (`MAX_LAYERS` in `src/quintet/samples.py`): every
    instrument goes up to `mp`, so the quintet blends instead of turning bright or brassy. A louder
    dynamic is reached by levelling (gain), keeping the softer tone.
  - A note without that recording falls back to the nearest softer one.
- **Volume sine:** `lfo=k` makes the voice's volume ebb and flow on a slow sine, `k` cycles over the
  whole piece, starting at `lfo_phase` (0 = loudest).
  - It swings 12 dB, from −4 dB at its loudest down to −16 dB, so a voice at its quietest is a
    quarter as loud as at its peak, and the peaks don't get too loud.
  - Generated voices get periods of about 10–30 s, chosen not to line up with the voice's own
    cycle, so each repeat of a pattern sounds a little different.
  - Every generated sine starts at its quietest. A piece opens softly with all voices at −16 dB,
    and, as each sine fits a whole number of times, eases back to that level by the end, so the
    loop point matches.
  - It's whole cycles over the piece, so loops stay seamless.
  - `lfo=0` keeps the volume steady.
- **Piece length:** the lowest common multiple of the five cycle lengths, so every voice realigns
  exactly at the end.
- **Metric accents:** stronger beats are slightly louder. The first note of any group is strongest
  (the loop's downbeat most of all, about +1.75 dB). In a longer group, the group start nearest the
  middle is next, like beat 3 of 4; then other group starts; then off-beats. Each level of nesting
  counts half as much.
- **Sounding:** voices are monophonic, so every note lasts until the next event starts.
  - A sample longer than the note is cut, with a fade of 10% of the note (10–150 ms).
  - A note longer than its sample uses the recording that is actually longest (measured from the
    file; the lengths in the file names are only nominal).
  - If it's still too short, the sample's steady middle repeats with 100 ms crossfades and its
    natural release ends the note. This only happens if that middle is at least 0.8 s long and
    needs at most 3 repeats. Otherwise the sample plays once and the rest of the note is silent,
    rather than stuttering.
  - Generation avoids those gaps: a note held longer than its instrument can sustain on that pitch
    is re-articulated (the hold becomes a repeated note on the same pitch).
  - **Long notes** (1.5 s or more) swell `<>`. They start from about −30 dB and stay quiet for the
    first fifth or so (still −11 dB 20% of the way in), then bloom into the voice's full level 40% of
    the way through, and die away. They never go above the voice's level.
  - **Shorter notes** fade in over 0.15 of a beat (150 ms at 60 bpm), so slower tempos get softer
    attacks.

## Legato

Each voice plays in phrases: runs of notes with no rest between them. A phrase may run over the
loop point, so a voice with no rests is one long phrase.

- **Only the phrase's first note is articulated.** It plays its recording from the start, with the
  natural tongued attack and a soft fade-in.
- **Every later note is joined** (`_note_audio` in `src/quintet/render.py`):
  - **A new pitch:** the note skips its recording's attack (up to where it reaches full level, so a
    slow-blooming flute is handled too) and crossfades from the previous note over 80 ms. The line
    moves from pitch to pitch without a re-attack.
  - **The same pitch again:** the same, but the old note fades out a little sooner and the new one
    comes in a little later, so the repeat is heard as a gentle "du" (about a 9 dB, 40 ms dip), not
    tongued.
  - **A renewal (`"3="`):** the same recording continues from its steady middle, phase-aligned by
    cross-correlation, so the note simply carries on.
- **Long notes in a phrase** swell `<>` from and back to about −9 dB (the line's level) instead of
  near silence. Only a phrase's first note grows from silence.
- **Note choice:** a note joined into the next one uses a recording long enough to still be
  sustaining, not releasing, when the next note arrives.

## Performance

On by default (`--no-humanize` turns it off), so the quintet plays rather than sequences. The
constants are at the top of `src/quintet/render.py`.

- **Timing:** each note lands a few milliseconds off the grid (±10 ms typical, ±25 ms at most),
  differently every time round.
- **Ensemble:** each instrument sits slightly ahead of or behind the beat: the flute 6 ms early, the
  horn 10 ms late, which is how horns speak. So the five never attack in exactly the same instant.
- **Phrase ends:** a phrase's last note leans a little into the rest after it.
- **Space after long tones:** a tone held 3 beats or more that runs straight into another note
  ends 0.3–0.6 s early, so the next note starts fresh after a short pause.
- **Breathing:** a voice that plays on without a rest breathes every 4–8 s, a 150–300 ms gap at a
  change of note (never inside a renewed held tone). The next note starts a fresh, articulated
  phrase.
- **Takes:** repeats rotate between the library's different recordings of the same note, so no two
  are identical.
- **Level:** each note's level varies by up to ±1 dB.
- **Intonation** (on by default; `--no-intonation` turns it off): each note is tuned slightly off, typically ±2
  cents and never more than ±4, differently every time. That makes unisons and octaves between
  instruments shimmer instead of sitting perfectly still. A renewed held tone keeps its note's
  tuning.
- **Reproducible and seamless:** everything is seeded from the voice itself, so renders are
  reproducible (piece files still rebuild the same WAV), and it repeats with the piece, so loops
  stay seamless.

## Mix

Each voice sits at a fixed spot in a mild stereo seating (`PAN` in `src/quintet/render.py`, −1 left to
+1 right):

| flute | clarinet | bassoon | horn | oboe |
|---|---|---|---|---|
| −0.35 | −0.2 | −0.05 | +0.1 | +0.35 |

The two highest voices are spread apart, and the horn and bassoon sit near the middle.

Each voice also sits at a depth on the stage (`STAGE_DEPTH`, 0 = front row, 1 = back):

| flute | oboe | clarinet | bassoon | horn |
|---|---|---|---|---|
| 0 | 0 | 0.4 | 0.6 | 1 |

- **Further back is later, darker and wetter:** up to 6 ms later (about 2 m), a high shelf of up
  to −4 dB above 4 kHz, and up to 4 dB more sent to the hall.
- **The horn is at the back**, as its bell faces away from the audience. Its level is trimmed up
  1.5 dB (`INSTRUMENT_TRIM_DB`) so it still carries.
- **Early reflections:** five quiet echoes per voice off alternating side walls, 9–38 ms after the
  direct sound and darkened above 6 kHz. A voice panned towards a wall hears it sooner, and one
  further back hears them closer together. They are part of the room, so `--reverb 0` drops them.

## Mastering

On by default (`--no-master` turns it off), in `src/quintet/effects.py`, using pedalboard:

- **EQ:** a 12 dB/octave high-pass at 60 Hz (rumble), −3 dB at 300 Hz (boxiness), +3.5 dB at
  3.5 kHz, where phone speakers and ears are most sensitive, and a +1.5 dB high shelf at 10 kHz for
  air.
- **Saturation:** `tanh`-shaped, like tape. Quiet passages pass through unchanged and peaks round
  off with a little warmth. `--saturation` sets how much (`0` = clean).
- **Compression:** gentle (2:1), from 8 dB below the target loudness, so quiet passages survive
  small speakers.
- **Loudness:** every piece is normalised to −16 LUFS (the usual level for phones and streaming),
  measured properly with pyloudnorm, with a −1 dBFS limiter.
- **Seamless loops:** each stage first runs over the piece's own ending, so the loop point sounds
  exactly as it does when the file repeats.

## Reverb

The staged mix is convolved with a hall, in `src/quintet/effects.py`:

- **The built-in hall** is decaying noise, with each octave decaying at its own rate: lows ring a
  little longer and highs die first, as in a real hall. `--room` sets its size (`0.8` ≈ 2.6 s).
- **A recorded space:** `--reverb-ir FILE` uses an impulse response WAV instead, at any sample rate,
  mono or stereo (free ones are in the [OpenAIR library](https://www.openair.hosted.york.ac.uk/)).
  `--room` is then ignored.
- **Pre-delay:** the hall starts 25 ms after the direct sound, so attacks stay clear.
- **The hall's own EQ:** 12 dB/octave cuts below 250 Hz and above 7 kHz, so it never muddies the
  bassoon and horn or hisses.
- **Amount:** `--reverb` sets the wet level. Every space is scaled to the same energy, so an amount
  means the same for any of them; the scale is set so an amount is about as wet as it was with the
  earlier algorithmic hall.
- **Seamless loops:** the convolution is circular: the tail rings over the loop point exactly as it
  does when the file repeats.
- **Stems stay dry**, for mixing elsewhere.
- `--reverb 0` gives the dry stage: no hall and no early reflections.

## Patterns

| Element | Meaning |
|---|---|
| `1`, `2`, … | The voice's palette notes, lowest first. Numbers past the end wrap round |
| `"3+"`, `"3-"` | Palette note 3 moved one step up/down the chord's parent scale (a non-chord tone) |
| `"3="` | Note 3 again, renewed seamlessly (generation writes this where a held note outlasts its recording) |
| `0` | Rest |
| `_` | Hold the previous note (or rest) through this slot |
| `[...]` | Divide this slot equally among its elements, to any depth |

- `[1, [2, 3], _, 0]` over 4 beats: note 1, then two half-beat notes, then 2 beats of hold on the
  last note (3), then a rest.
- A leading `_` continues the previous cycle's last note.
- `[1, ["3-", 3], 5]`: note 1, then a passing tone stepping up into note 3, then note 5.

## Harmony

With `--notes random`, each seed picks a key (all 12) and a whole 7-note mode, weighted towards
the warmer ones:

| Mode | On C | Weight |
|---|---|---|
| `lydian` | C D E F♯ G A B | 3 |
| `dorian` | C D E♭ F G A B♭ | 3 |
| `mixolydian` | C D E F G A B♭ | 2 |
| `major` | C D E F G A B | 2 |
| `minor` | C D E♭ F G A♭ B♭ | 2 |
| `phrygian` | C D♭ E♭ F G A♭ B♭ | 1 |

- **Voicing:** the bassoon plays the mode's root and 5th, the horn its triad, and the clarinet,
  oboe and flute all seven notes.
- **Colour from spacing, not crowding:** see the spacing rule below.
- **Chords are still available:** e.g. `--notes C.maj9`, `--notes Fs.maj7s11`, or `--notes D.lydian`
  for a fixed mode.
- **Separate streams:** the harmony and the tempo each come from their own random stream for the
  seed. Fixing one (e.g. `--tempo 60`) doesn't change what the seed picks for the other.
- **Weights:** `HARMONY_WEIGHTS` in `src/quintet/theory.py` sets them.

## Spacing between voices

Notes that sound at the same time follow a soft spacing rule based on the orchestration "low
interval limits": the tighter or more dissonant an interval, the higher it has to sit to sound
clear rather than muddy.

| Interval | Lower note at or above |
|---|---|
| minor 2nd | C5 |
| major 2nd | G4 |
| tritone | C4 |
| minor 3rd, major 7th | C3 |
| major 3rd | B♭2 |
| perfect 4th | A2 |
| minor and major 6ths, minor 7th | F2 |
| perfect 5th | B♭1 |

- **Wide intervals:** an interval wider than an octave counts as its smaller form with the limit an
  octave lower, so a minor 9th is fine from C4. Dissonances end up spread open: in generated
  pieces, minor and major 2nds sound together as 9ths or wider about 30–50 times as often as they
  sound within an octave.
- **Soft rule:** generation nudges notes to fix clashes (keeping parallel 5ths/octaves at zero) but
  tolerates up to 1.5 too-close moments per minute.
- **Where:** `SPACING_FLOOR` and `CLASHES_PER_MINUTE` in `src/quintet/voice.py`; `clashes(voices,
  notes)` lists them for any piece.

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
- **Neighbour tone:** a step away and straight back, `[3, "3+"]` then 3.
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
| oboe | E4 G4 B4 |
| flute | B4 C5 D5 E5 G5 B5 C6 |

The constants are at the top of `src/quintet/voice.py`.

## Generation

`generate(seed, notes)` writes each voice in its instrument's idiom. The `PROFILES` table in
`src/quintet/voice.py` holds these:

- **Melodic walk:** each note moves from the previous one by a weighted repeat, step (next palette
  note), skip (two palette notes) or leap.
- **One shared pulse:** a generated line has one slot per beat, each a note, a hold, a rest or a
  pair of eighths, so every note starts on the same eighth-note grid in every voice. Phasing comes
  from the voices' different loop lengths, not from tuplets.
- **Quick figures:** an occasional run of eighths in the instrument's own style, e.g. a 3-note
  flute run `[1, 2], 3`.
- **Breathing:** rests and holds. On top of the instrument's own rests, a phrase cell often ends on
  a rest (70%), and a voice sometimes sits out a whole cell (25% of cells after the first), so the
  texture has space instead of all five playing at once. On average about 3.7 of the 5 voices sound
  at any moment.
- **Loop length:** every voice's loop lasts 6–10 s (a whole number of beats) at the piece's tempo,
  strung from phrase cells of whole beats (each about the instrument's own cell length). That's long enough not to feel repetitive, short
  enough to hear each loop come round.

| | Moves | Quick figures | Character |
|---|---|---|---|
| flute | mostly steps | 3–4-note scale runs | busiest, few rests |
| oboe | steps | stepwise pairs | lyrical, breathes often |
| clarinet | skips | arpeggios | smooth, sustains often |
| horn | repeated notes, skips | repeated notes | favours root and 5th; sustains often |
| bassoon | leaps, octaves | octave/leap bounces | favours the root |

On top of that:

- 1–2 voices per piece sustain 1–3 long notes (3 beats or more each) across their loop, usually
  (60%) closing it with a 1–2-beat rest. They're
  chosen weighted towards the instruments whose recordings can hold long notes: clarinet, horn and
  flute, rarely the oboe or bassoon.
- No voice drifts: `drift` is only for hand-written pieces.
- Each voice's dynamic runs from `p` up to its instrument's cap, `mp`.
- Each voice gets a volume sine with its own period, starting (and ending) at its quietest.

It redraws, deterministically for that seed, until the piece fits `--max-seconds` and has at least
3 different loop lengths, so the voices genuinely phase. Nearby loop lengths (say 7 against 8 s)
slide past each other slowly, Reich-style. Pieces run about 1–6 minutes (median about 4).

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
  `INSTRUMENT_TRIM_DB` in `src/quintet/render.py` adjusts each instrument by ear; the oboe sits 3 dB
  down so it doesn't stick out.

## Development

| Command | Does |
|---|---|
| `make sync` | install the project and its dependencies |
| `make test` | run the tests (pytest) |
| `make lint` | check the code (ruff) |
| `make format` | format the code (ruff) |

`tests/test_generation_parity.py` pins what 20 seeds generate, so accidental changes to generation
fail the tests. After changing generation on purpose, re-record it with `make fixtures`.
