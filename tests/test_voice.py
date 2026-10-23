import tempfile
import time
import unittest
from fractions import Fraction as Fr
from functools import cache
from pathlib import Path

from quintet import (
    QUALITIES,
    QUINTET,
    SAMPLE_RATE,
    B,
    C,
    Config,
    Fs,
    PitchClass,
    _,
    clashes,
    expand,
    generate,
    instrument,
    midi_to_note,
    note_to_midi,
    palette,
    parallels,
    piece_beats,
    resolve_notes,
    resolve_pitch,
    sustainable_frames,
    too_close,
    voice,
)
from quintet.pattern import STEP
from quintet.voice import CLASHES_PER_MINUTE, LFO_DEPTH_DB, LFO_PEAK_DB, LOW_TO_HIGH, SWEET

QUIETEST = 10 ** ((LFO_PEAK_DB - LFO_DEPTH_DB) / 20)
LOUDEST = 10 ** (LFO_PEAK_DB / 20)

Config(argv=[], tempo=60)


class VoiceTest(unittest.TestCase):
    def test_span(self):
        self.assertEqual(voice([1], beats=4).span, 4)
        self.assertEqual(voice([1], beats=4, drift=16).span, Fr(64, 17))

    def test_drift_realigns_after_k_plus_one_cycles(self):
        a, b = voice([1], beats=4), voice([1], beats=4, drift=16)
        self.assertEqual(piece_beats([a, b]), 64)
        self.assertEqual(64 / b.span, 17)

    def test_lcm(self):
        self.assertEqual(piece_beats([voice([1], beats=b) for b in (3, 4, 6)]), 12)
        self.assertEqual(piece_beats([voice([1], beats=3, drift=1), voice([1], beats=1)]), 3)  # 3/2 and 1

    def test_invalid(self):
        for kwargs in ({"beats": 0}, {"beats": 1.5}, {"beats": 4, "drift": -1}, {"beats": 4, "dynamic": "loud"}):
            with self.assertRaises(ValueError):
                voice([1], **kwargs)
        with self.assertRaises(ValueError):
            voice([1, 0.5], beats=2)

    def test_code_round_trips(self):
        v = voice([1, [2, 3], _, 0], beats=5, drift=8, dynamic="mp", lfo=3, lfo_phase=0.25)
        self.assertEqual(v.code(), "voice([1, [2, 3], _, 0], beats=5, drift=8, dynamic='mp', lfo=3, lfo_phase=0.25)")
        self.assertEqual(eval(v.code()), v)


class LfoTest(unittest.TestCase):
    def test_gain_range_and_wrap(self):
        v = voice([1], beats=4, lfo=3, lfo_phase=0.0)
        self.assertAlmostEqual(v.gain(0), LOUDEST)
        self.assertAlmostEqual(v.gain(1 / 6), QUIETEST)  # half a cycle in
        self.assertAlmostEqual(v.gain(0.2), v.gain(1.2))  # whole cycles: seamless loop
        self.assertTrue(all(QUIETEST - 1e-9 <= v.gain(i / 100) <= LOUDEST + 1e-9 for i in range(100)))
        self.assertEqual(voice([1], beats=4).gain(0.3), 1.0)

    def test_invalid(self):
        for kwargs in ({"lfo": -1}, {"lfo": 1.5}, {"lfo_phase": 1.0}, {"lfo_phase": -0.5}):
            with self.assertRaises(ValueError):
                voice([1], beats=4, **kwargs)

    def test_generated_sines_start_and_end_at_their_quietest(self):
        for s in range(10):
            for x in generate(s, resolve_notes("random", s)).values():
                self.assertAlmostEqual(x.gain(0.0), QUIETEST)
                self.assertAlmostEqual(x.gain(1.0), QUIETEST)  # whole cycles: the loop point matches
                self.assertGreater(max(x.gain(i / 200) for i in range(200)), 2 * QUIETEST)  # it still swells

    def test_generated_sines_are_slow_and_out_of_step(self):
        out_of_step = total_voices = 0
        config = Config(argv=[], tempo=60)
        for s in range(40):
            v = generate(s, C.lydian, config)
            total = piece_beats(v.values())
            seconds = float(total)  # 60 bpm: one beat per second
            for x in v.values():
                self.assertGreaterEqual(x.lfo, 1)
                if seconds >= 10:
                    self.assertTrue(10 <= seconds / x.lfo <= 30, (s, seconds, x.lfo))
                total_voices += 1
                out_of_step += int(total / x.span) % x.lfo != 0
        self.assertGreater(out_of_step / total_voices, 0.7)


@cache
def generated(seed: int, notes) -> dict:
    """generate() at 60 bpm, cached: several tests look at the same pieces."""
    return generate(seed, notes, Config(argv=[], tempo=60))


def moves(name, seeds=range(60)):
    """Fraction of consecutive notes in an instrument's generated lines (over C.lydian) that repeat,
    step (1-2 semitones), or leap (a 4th or more)."""
    counts = {"repeat": 0, "step": 0, "leap": 0, "all": 0}
    tones = palette(C.lydian, instrument(name))
    for s in seeds:
        v = generated(s, C.lydian)[name]
        # renewals ("3=") continue a held note rather than repeat it
        notes = [
            resolve_pitch(e.index, tones, C.lydian)
            for e in expand(v.pattern, v.span)
            if e.index and not (isinstance(e.index, str) and e.index.endswith("="))
        ]
        for a, b in zip(notes, notes[1:]):
            d = abs(a - b)
            counts["all"] += 1
            counts["repeat"] += d == 0
            counts["step"] += 1 <= d <= 2
            counts["leap"] += d >= 5
    return {k: counts[k] / counts["all"] for k in ("repeat", "step", "leap")}


class IdiomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = {n: moves(n) for n in QUINTET}

    def test_horn_repeats_most(self):
        self.assertEqual(max(QUINTET, key=lambda n: self.stats[n]["repeat"]), "horn")

    def test_flute_and_oboe_step_more_than_horn(self):
        for name in ("flute", "oboe"):
            self.assertGreater(self.stats[name]["step"], self.stats["horn"]["step"])

    def test_bassoon_leaps_most(self):
        self.assertEqual(max(QUINTET, key=lambda n: self.stats[n]["leap"]), "bassoon")

    def test_indices_stay_in_palette(self):
        for s in range(30):
            for name, v in generate(s, C.lydian).items():
                size = len(palette(C.lydian, instrument(name)))
                for e in expand(v.pattern, v.span):
                    if e.index:
                        k = e.index if isinstance(e.index, int) else int(STEP.fullmatch(e.index).group(1))
                        self.assertTrue(1 <= k <= size)


class PaletteTest(unittest.TestCase):
    def test_spacing_for_each_set(self):
        for notes in (C.maj7s11, C.lydian, Fs.maj7s11, B.lydian):
            palettes = {n: palette(notes, instrument(n)) for n in QUINTET}
            for name, tones in palettes.items():
                inst = instrument(name)
                self.assertGreaterEqual(len(tones), 3, (notes, name))
                self.assertTrue(set(tones) <= inst.playable, (notes, name))
                self.assertTrue(all(t % 12 in notes.pitch_classes for t in tones))
            lows = [min(palettes[n]) for n in LOW_TO_HIGH]
            self.assertEqual(lows, sorted(lows), notes)
            # the two lowest voices sit far apart: bassoon's lowest at least a fifth under horn's
            self.assertGreaterEqual(min(palettes["horn"]) - min(palettes["bassoon"]), 7, notes)

    def test_palettes_stay_in_each_instruments_sweet_range(self):
        for quality in QUALITIES:
            for root in range(12):
                notes = getattr(PitchClass(root), quality)
                for name in QUINTET:
                    low, high = (note_to_midi(n) for n in SWEET[name])
                    tones = palette(notes, instrument(name))
                    self.assertGreaterEqual(len(tones), 3, (notes, name))
                    self.assertTrue(low <= min(tones) and max(tones) <= high, (notes, name, tones))


class VoicingTest(unittest.TestCase):
    def test_colour_notes_stay_up_top(self):
        for notes in (C.maj9, Fs.maj7s11, B.lydian, C.sus9):
            pcs = lambda name, notes=notes: {m % 12 for m in palette(notes, instrument(name))}
            self.assertLessEqual(pcs("bassoon"), set(notes.bass), notes)
            self.assertLessEqual(pcs("horn"), set(notes.core), notes)
        upper = {m % 12 for n in ("clarinet", "oboe", "flute") for m in palette(C.maj9, instrument(n))}
        self.assertIn(2, upper)  # the 9th (D) is voiced, but only above the horn


class EveryChordTest(unittest.TestCase):
    def test_quartal_sets_keep_the_3rd_out_of_horn_and_bassoon(self):
        for root in range(12):
            for quality in ("quartal", "quartal_bright"):
                notes = getattr(PitchClass(root), quality)
                for name in ("horn", "bassoon"):
                    above_root = {(m - root) % 12 for m in palette(notes, instrument(name))}
                    self.assertFalse({3, 4} & above_root, (root, quality, name))

    def test_every_palette_note_has_a_soft_sample(self):
        for quality in QUALITIES:
            for root in range(12):
                notes = getattr(PitchClass(root), quality)
                for name in QUINTET:
                    inst = instrument(name)
                    for m in palette(notes, inst):
                        inst.note(midi_to_note(m), inst.max_layer, 1.0, max_dynamic=inst.max_layer)  # raises if missing


class NonChordToneTest(unittest.TestCase):
    def test_resolve_pitch(self):
        tones = [60, 64, 67, 71]  # C E G B
        self.assertEqual(resolve_pitch(2, tones, C.maj9), 64)
        self.assertEqual(resolve_pitch("2+", tones, C.maj9), 65)  # E up a scale step: F
        self.assertEqual(resolve_pitch("3+", tones, C.maj9), 69)  # G -> A
        self.assertEqual(resolve_pitch("1-", tones, C.maj9), 59)  # C -> B
        self.assertEqual(resolve_pitch("2+", tones, C.maj9, playable={60, 64}), 64)  # unplayable: stays

    def test_generated_non_chord_tones_resolve_by_step(self):
        # modes have no non-chord tones (every step is in the mode), so use chords
        chords = ("maj9", "min9", "maj7s11", "dom9", "min69", "dom7s11", "maj69", "min11", "sus9")
        seen = 0
        for s in range(60):
            notes = getattr(PitchClass(s), chords[s % len(chords)])
            for name, v in generate(s, notes).items():
                inst = instrument(name)
                tones = palette(notes, inst)
                events = [e for e in expand(v.pattern, v.span) if e.index]
                for i, e in enumerate(events):
                    if isinstance(e.index, str) and e.index[-1] in "+-":  # "3=" is a renewal, not a step
                        seen += 1
                        here = resolve_pitch(e.index, tones, notes, inst.playable)
                        after = resolve_pitch(events[(i + 1) % len(events)].index, tones, notes, inst.playable)
                        self.assertIn(here % 12, notes.scale.pitch_classes)
                        self.assertLessEqual(abs(after - here), 2, (s, name, v.pattern))  # left by step
        self.assertGreater(seen, 20)


class ParallelsTest(unittest.TestCase):
    def piece(self, **override):
        rest = {n: voice([0], beats=2) for n in QUINTET}
        return {**rest, **override}

    def test_finds_parallel_and_contrary_perfects(self):
        # bassoon C2->G2 under flute C5->G5 : octaves moving in parallel
        v = self.piece(bassoon=voice([1, 2], beats=2), flute=voice([2, 5], beats=2))
        found = parallels(v, C.maj9)
        self.assertTrue(found)
        self.assertEqual({f[1:3] for f in found}, {("flute", "bassoon")})

    def test_held_notes_do_not_count(self):
        v = self.piece(bassoon=voice([1, _], beats=2), flute=voice([2, 5], beats=2))
        self.assertEqual(parallels(v, C.maj9), [])

    def test_generated_pieces_have_none(self):
        for s in range(40):
            notes = resolve_notes("random", s)
            self.assertEqual(parallels(generate(s, notes), notes), [], s)


class RearticulationTest(unittest.TestCase):
    def test_renewals_mark_holds_the_recording_cannot_carry(self):
        renewed = 0
        for s in range(20):
            for x in generate(s, resolve_notes("random", s)).values():
                events = [e.index for e in expand(x.pattern, x.span)]
                for i, idx in enumerate(events):
                    if isinstance(idx, str) and idx.endswith("="):
                        renewed += 1
                        before = events[i - 1]
                        base = before if isinstance(before, int) else int(STEP.fullmatch(before).group(1))
                        self.assertEqual(int(idx[:-1]), base)  # renews the note before it
        self.assertGreater(renewed, 10)

    def test_no_note_outlasts_what_its_instrument_can_sustain(self):
        for s in range(20):
            notes = resolve_notes("random", s)
            v = generate(s, notes)
            for name, x in v.items():
                inst = instrument(name)
                tones = palette(notes, inst)
                for e in expand(x.pattern, x.span):
                    if not e.index:
                        continue
                    m = resolve_pitch(e.index, tones, notes, inst.playable)
                    longest = inst.note(midi_to_note(m), x.dynamic, 1e9, max_dynamic=inst.max_layer)
                    cap = sustainable_frames(round(longest.seconds * SAMPLE_RATE)) / SAMPLE_RATE
                    self.assertLessEqual(float(e.beats), cap + 1e-6, (s, name))  # 60 bpm: beats = seconds


class TimeSeedTest(unittest.TestCase):
    def test_now_claims_distinct_increasing_seeds(self):
        out = Path(tempfile.mkdtemp())
        config = Config(argv=[], tempo=60, seeds="now", output_dir=out)
        before = time.time_ns() // 10**7
        seeds = [next(iter(config.seed_range())) for _ in range(5)]  # faster than the 10 ms tick: would collide
        self.assertEqual(len(set(seeds)), 5)
        self.assertGreaterEqual(min(seeds), before)
        self.assertTrue(all(isinstance(s, int) for s in seeds))
        self.assertTrue(all((out / f"piece_{s}.wav").exists() for s in seeds))  # each claimed
        Config(argv=[], tempo=60)

    def test_count_claims_that_many_new_seeds_lazily(self):
        out = Path(tempfile.mkdtemp())
        config = Config(argv=[], tempo=60, seeds="now", count=3, output_dir=out)
        seeds = config.seed_range()
        first = next(iter(seeds))
        self.assertEqual(len(list(out.iterdir())), 1)  # only the first is claimed so far
        rest = list(seeds)
        self.assertEqual(len(rest), 2)
        self.assertEqual(len({first, *rest}), 3)
        with self.assertRaises(ValueError):
            list(Config(argv=[], tempo=60, seeds="5-8", count=3).seed_range())
        Config(argv=[], tempo=60)

    def test_explicit_seeds_unchanged(self):
        self.assertEqual(Config(argv=[], tempo=60, seeds="5-8").seed_range(), range(5, 8))
        self.assertEqual(Config(argv=[], tempo=60, seeds="42").seed_range(), range(42, 43))
        with self.assertRaises(ValueError):
            Config(argv=[], tempo=60, seeds="soon").seed_range()
        Config(argv=[], tempo=60)


class SpacingTest(unittest.TestCase):
    def test_too_close(self):
        self.assertTrue(too_close(60, 61))  # a minor 2nd at middle C: too close
        self.assertFalse(too_close(72, 73))  # fine up at C5
        self.assertFalse(too_close(60, 73))  # the same clash spread as a minor 9th from C4
        self.assertTrue(too_close(40, 53))  # but a minor 9th that low is still muddy
        self.assertTrue(too_close(50, 56))  # a tritone below C4
        self.assertFalse(too_close(62, 68))
        self.assertFalse(too_close(36, 43))  # a low 5th is fine
        self.assertTrue(too_close(40, 44))  # a major 3rd below B-flat 2 is muddy
        self.assertFalse(too_close(50, 50) or too_close(50, 62) or too_close(30, 60))

    def test_generated_pieces_keep_clashes_rare(self):
        for s in range(15):
            config = Config(argv=[], tempo=60)
            notes = resolve_notes("random", s)
            v = generate(s, notes, config)
            minutes = float(piece_beats(v.values())) / 60
            self.assertLessEqual(len(clashes(v, notes, config)), int(CLASHES_PER_MINUTE * minutes), s)
            self.assertEqual(parallels(v, notes, config), [])


class TempoTest(unittest.TestCase):
    def test_random_per_seed(self):
        config = Config(argv=[], tempo=0)
        tempos = [config.piece_tempo(s) for s in range(200)]
        self.assertEqual(tempos[:10], [config.piece_tempo(s) for s in range(10)])
        self.assertEqual((min(tempos), max(tempos)), (60, 85))
        self.assertTrue(all(t == int(t) for t in tempos))
        with self.assertRaises(ValueError):
            config.bpm()
        Config(argv=[], tempo=60)

    def test_fixed(self):
        self.assertEqual(Config(argv=[], tempo=66).piece_tempo(5), 66)


class GenerateTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(generate(1000, C.maj7s11), generate(1000, C.maj7s11))

    def test_seeds_differ(self):
        pieces = [generate(s, C.maj7s11) for s in range(1000, 1010)]
        self.assertGreater(len({repr(p) for p in pieces}), 5)

    def test_leaves_space_between_phrases(self):
        config = Config(argv=[], tempo=62)
        sounding = []
        for s in range(20):
            for x in generate(s, C.lydian, config).values():
                events = expand(x.pattern, x.span)
                sounding.append(float(sum(e.beats for e in events if e.index is not None) / x.span))
        self.assertLess(5 * sum(sounding) / len(sounding), 4.2)  # voices sounding at once, of 5

    def test_every_note_lands_on_a_shared_eighth_note_pulse(self):
        for s in range(20):
            config = Config(argv=[], tempo=0)
            config.tempo = config.piece_tempo(s)
            for name, x in generate(s, resolve_notes("random", s), config).items():
                self.assertEqual(x.drift, 0, (s, name))
                self.assertEqual(len(x.pattern), x.beats, (s, name))  # one slot per beat
                for e in expand(x.pattern, x.span):
                    if isinstance(e.index, str) and e.index.endswith("="):
                        continue  # a renewal carries on the same note seamlessly: no new attack
                    self.assertEqual((e.start * 2).denominator, 1, (s, name, x.pattern))
        Config(argv=[], tempo=60)

    def test_fits_max_seconds(self):
        config = Config(argv=[], tempo=60, max_seconds=120)
        for s in range(20):
            v = generate(s, C.lydian, config)
            self.assertLessEqual(piece_beats(v.values()) * 60 / Fr(config.tempo), 120)
            self.assertEqual(set(v), set(QUINTET))
            self.assertGreaterEqual(len({x.span for x in v.values()}), 3)
            self.assertTrue(all(x.dynamic in ("p", "mp") for x in v.values()))

    def test_loops_last_8_to_13_seconds_at_any_tempo(self):
        for tempo in (50, 60, 70):
            config = Config(argv=[], tempo=tempo)
            for s in range(15):
                v = generate(s, resolve_notes("random", s), config)
                for x in v.values():
                    self.assertTrue(8 <= x.span * 60 / tempo <= 13, (tempo, s, x.span))
                self.assertLessEqual(piece_beats(v.values()) * 60 / tempo, 480)
        Config(argv=[], tempo=60)

    def test_sustainers(self):
        for s in range(30):
            v = generate(s, C.lydian)
            # a sustained tone may be re-attacked where the recordings can't hold it: measure same-pitch runs
            longest = {}
            for n, x in v.items():
                runs, last = [], None
                for e in expand(x.pattern, x.span):
                    if e.index and e.index == last:
                        runs[-1] += e.beats
                    else:
                        runs.append(e.beats if e.index else 0)
                    last = e.index
                longest[n] = max(runs)
            self.assertGreaterEqual(sum(b >= 3 for b in longest.values()), 1, s)  # 3+ beats
        Config(argv=[], tempo=60)


if __name__ == "__main__":
    unittest.main()
