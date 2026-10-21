import unittest
from fractions import Fraction as Fr

from quintet import (
    QUINTET,
    B,
    C,
    Config,
    Fs,
    _,
    expand,
    generate,
    instrument,
    midi_to_note,
    palette,
    parallels,
    piece_beats,
    resolve_notes,
    resolve_pitch,
    voice,
)
from quintet.voice import LFO_DEPTH_DB, LFO_PEAK_DB, LOW_TO_HIGH

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
        from quintet import _  # noqa: F401  (used by eval)

        v = voice([1, [2, 3], _, 0], beats=5, drift=8, dynamic="mp", lfo=3, lfo_phase=0.25)
        self.assertEqual(v.code(), "voice([1, [2, 3], _, 0], beats=5, drift=8, dynamic='mp', lfo=3, lfo_phase=0.25)")
        self.assertEqual(eval(v.code()), v)


class LfoTest(unittest.TestCase):
    def test_gain_range_and_wrap(self):
        v = voice([1], beats=4, lfo=3, lfo_phase=0.0)
        self.assertAlmostEqual(v.gain(0), 10 ** (LFO_PEAK_DB / 20))  # loudest
        self.assertAlmostEqual(v.gain(1 / 6), 10 ** ((LFO_PEAK_DB - LFO_DEPTH_DB) / 20))  # quietest, half a cycle in
        self.assertAlmostEqual(v.gain(0.2), v.gain(1.2))  # whole cycles: seamless loop
        low, high = 10 ** ((LFO_PEAK_DB - LFO_DEPTH_DB) / 20), 10 ** (LFO_PEAK_DB / 20)
        self.assertTrue(all(low - 1e-9 <= v.gain(i / 100) <= high + 1e-9 for i in range(100)))
        self.assertEqual(voice([1], beats=4).gain(0.3), 1.0)

    def test_invalid(self):
        for kwargs in ({"lfo": -1}, {"lfo": 1.5}, {"lfo_phase": 1.0}, {"lfo_phase": -0.5}):
            with self.assertRaises(ValueError):
                voice([1], beats=4, **kwargs)

    def test_generated_sines_are_slow_and_out_of_step(self):
        out_of_step = total_voices = 0
        for s in range(40):
            v = generate(s, C.lydian)
            total = piece_beats(v.values())
            seconds_ = float(total)  # 60 bpm: one beat per second
            for x in v.values():
                self.assertGreaterEqual(x.lfo, 1)
                if seconds_ >= 10:
                    self.assertTrue(10 <= seconds_ / x.lfo <= 30, (s, seconds_, x.lfo))
                total_voices += 1
                out_of_step += int(total / x.span) % x.lfo != 0
        self.assertGreater(out_of_step / total_voices, 0.7)


def moves(name, seeds=range(60)):
    """Fraction of consecutive notes in an instrument's generated lines (over C.lydian) that repeat,
    step (1-2 semitones), or leap (a 4th or more)."""
    counts = {"repeat": 0, "step": 0, "leap": 0, "all": 0}
    tones = palette(C.lydian, instrument(name))
    for s in seeds:
        v = generate(s, C.lydian)[name]
        notes = [tones[(e.index - 1) % len(tones)] for e in expand(v.pattern, v.span) if e.index]
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
                self.assertTrue(all(1 <= e.index <= size for e in expand(v.pattern, v.span) if e.index))


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


class VoicingTest(unittest.TestCase):
    def test_colour_notes_stay_up_top(self):
        for notes in (C.maj9, Fs.maj7s11, B.lydian, C.sus9):
            pcs = lambda name, notes=notes: {m % 12 for m in palette(notes, instrument(name))}
            self.assertLessEqual(pcs("bassoon"), set(notes.bass), notes)
            self.assertLessEqual(pcs("horn"), set(notes.core), notes)
        upper = {m % 12 for n in ("clarinet", "oboe", "flute") for m in palette(C.maj9, instrument(n))}
        self.assertIn(2, upper)  # the 9th (D) is voiced, but only above the horn


class EveryChordRendersTest(unittest.TestCase):
    def test_every_palette_note_has_a_soft_sample(self):
        from quintet.theory import QUALITIES, PitchClass

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
        seen = 0
        for s in range(60):
            notes = resolve_notes("random", s)
            for name, v in generate(s, notes).items():
                inst = instrument(name)
                tones = palette(notes, inst)
                events = [e for e in expand(v.pattern, v.span) if e.index]
                for i, e in enumerate(events):
                    if isinstance(e.index, str):
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
    def test_no_note_outlasts_what_its_instrument_can_sustain(self):
        from quintet import sustainable_frames

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
                    cap = sustainable_frames(round(longest.seconds * 44100)) / 44100
                    self.assertLessEqual(float(e.beats), cap + 1e-6, (s, name))  # 60 bpm: beats = seconds


class TimeSeedTest(unittest.TestCase):
    def test_now_claims_distinct_increasing_seeds(self):
        import tempfile
        import time
        from pathlib import Path

        out = Path(tempfile.mkdtemp())
        config = Config(argv=[], tempo=60, seeds="now", output_dir=out)
        before = time.time_ns() // 10**7
        seeds = [config.seed_range()[0] for _ in range(5)]  # faster than the 10 ms tick: would collide
        self.assertEqual(len(set(seeds)), 5)
        self.assertGreaterEqual(min(seeds), before)
        self.assertTrue(all(isinstance(s, int) for s in seeds))
        self.assertTrue(all((out / f"piece_{s}.wav").exists() for s in seeds))  # each claimed
        Config(argv=[], tempo=60)

    def test_explicit_seeds_unchanged(self):
        self.assertEqual(Config(argv=[], tempo=60, seeds="5-8").seed_range(), range(5, 8))
        self.assertEqual(Config(argv=[], tempo=60, seeds="42").seed_range(), range(42, 43))
        with self.assertRaises(ValueError):
            Config(argv=[], tempo=60, seeds="soon").seed_range()
        Config(argv=[], tempo=60)


class TempoTest(unittest.TestCase):
    def test_random_per_seed(self):
        config = Config(argv=[], tempo=0)
        tempos = [config.piece_tempo(s) for s in range(200)]
        self.assertEqual(tempos[:10], [config.piece_tempo(s) for s in range(10)])
        self.assertEqual((min(tempos), max(tempos)), (50, 70))
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

    def test_fits_max_seconds(self):
        config = Config(argv=[], tempo=60, max_seconds=120)
        for s in range(20):
            v = generate(s, C.lydian, config)
            self.assertLessEqual(piece_beats(v.values()) * 60 / Fr(config.tempo), 120)
            self.assertEqual(set(v), set(QUINTET))
            self.assertGreaterEqual(len({x.span for x in v.values()}), 3)
            self.assertTrue(all(x.dynamic in ("p", "mp", "mf") for x in v.values()))
            self.assertIn(v["horn"].dynamic, ("p", "mp"))

    def test_loops_last_6_to_10_seconds_at_any_tempo(self):
        for tempo in (50, 60, 70):
            config = Config(argv=[], tempo=tempo)
            for s in range(15):
                v = generate(s, resolve_notes("random", s), config)
                for x in v.values():
                    self.assertTrue(6 <= x.span * 60 / tempo <= 10, (tempo, s, x.span))
                self.assertLessEqual(piece_beats(v.values()) * 60 / tempo, 360)
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
            self.assertGreaterEqual(sum(b >= Fr(5, 2) for b in longest.values()), 1, s)  # 3+ beats, less any drift
        Config(argv=[], tempo=60)


if __name__ == "__main__":
    unittest.main()
