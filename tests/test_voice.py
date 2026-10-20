import unittest
from fractions import Fraction as Fr

from utils import QUINTET, Config, C, Fs, B, expand, generate, instrument, palette, piece_beats, voice
from utils.voice import LOW_TO_HIGH

Config(argv=[])


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
        from utils import _  # noqa: F401  (used by eval)
        v = voice([1, [2, 3], _, 0], beats=5, drift=8, dynamic="mp")
        self.assertEqual(v.code(), "voice([1, [2, 3], _, 0], beats=5, drift=8, dynamic='mp')")
        self.assertEqual(eval(v.code()), v)


def moves(name, seeds=range(60)):
    """Fraction of consecutive note pairs in an instrument's generated lines that repeat, step
    (one palette note), or leap (three or more)."""
    counts = {"repeat": 0, "step": 0, "leap": 0, "all": 0}
    for s in seeds:
        v = generate(s, C.lydian)[name]
        notes = [e.index for e in expand(v.pattern, v.span) if e.index]
        for a, b in zip(notes, notes[1:]):
            d = abs(a - b)
            counts["all"] += 1
            counts["repeat"] += d == 0
            counts["step"] += d == 1
            counts["leap"] += d >= 3
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
                self.assertTrue(set(tones) <= inst.pitches, (notes, name))
                self.assertTrue(all(t % 12 in notes.pitch_classes for t in tones))
            lows = [min(palettes[n]) for n in LOW_TO_HIGH]
            self.assertEqual(lows, sorted(lows), notes)
            # the two lowest voices sit far apart: bassoon's lowest at least a fifth under horn's
            self.assertGreaterEqual(min(palettes["horn"]) - min(palettes["bassoon"]), 7, notes)


class GenerateTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(generate(1000, C.maj7s11), generate(1000, C.maj7s11))

    def test_seeds_differ(self):
        pieces = [generate(s, C.maj7s11) for s in range(1000, 1010)]
        self.assertGreater(len({repr(p) for p in pieces}), 5)

    def test_fits_max_seconds(self):
        config = Config(argv=[], max_seconds=120)
        for s in range(20):
            v = generate(s, C.lydian, config)
            self.assertLessEqual(piece_beats(v.values()) * 60 / Fr(config.tempo), 120)
            self.assertEqual(set(v), set(QUINTET))
            self.assertGreaterEqual(len({x.span for x in v.values()}), 4)
            self.assertTrue(all(x.dynamic in ("p", "mp") for x in v.values()))

    def test_sustainers(self):
        for s in range(30):
            v = generate(s, C.lydian)
            longest = {n: max(e.beats for e in expand(x.pattern, x.span) if e.index) for n, x in v.items()}
            self.assertGreaterEqual(sum(b >= Fr(5, 2) for b in longest.values()), 1, s)  # 3+ beats, less any drift
        Config(argv=[])


if __name__ == "__main__":
    unittest.main()
