import unittest
from collections import Counter

from quintet.theory import (
    HARMONY_WEIGHTS,
    M3,
    P4,
    P5,
    A,
    As,
    B,
    Bb,
    C,
    D,
    E,
    Eb,
    F,
    Fs,
    G,
    PitchSet,
    fifths,
    fourths,
    parse_set,
    resolve_notes,
)


class PitchClassTest(unittest.TestCase):
    def test_arithmetic_wraps(self):
        self.assertEqual(C + 7, G)
        self.assertEqual(C - 1, B)
        self.assertEqual(B + 1, C)
        self.assertIs(type(C + 7), type(C))

    def test_enharmonics_equal(self):
        self.assertEqual(As, Bb)

    def test_intervals(self):
        self.assertEqual(C.up(P5), G)
        self.assertEqual(C.down(M3), 8)  # Ab

    def test_circle(self):
        self.assertEqual(C.fifths(1), G)
        self.assertEqual(C.fourths(2), Bb)
        self.assertEqual(C.fifths(12), C)
        self.assertEqual(fifths(C, 4), [C, G, D, A])
        self.assertEqual(fourths(C, 4), [C, F, Bb, Eb])

    def test_repr(self):
        self.assertEqual(repr(Fs), "Fs")


class PitchSetTest(unittest.TestCase):
    def test_qualities(self):
        self.assertEqual(C.maj7s11.pitch_classes, [C, E, Fs, G, B])
        self.assertEqual(C.lydian.pitch_classes, [C, D, E, Fs, G, A, B])
        self.assertEqual(A.min.pitch_classes, [A, C, E])
        self.assertEqual(G.dom7.pitch_classes, [G, B, D, F])

    def test_unknown_quality(self):
        with self.assertRaises(AttributeError) as cm:
            getattr(C, "nope")  # noqa: B009 (the attribute access itself is under test)
        self.assertIn("maj7s11", str(cm.exception))

    def test_transpose_and_circle(self):
        self.assertEqual(C.maj.up(P4), F.maj)
        self.assertEqual(C.maj.fifths(1), G.maj)
        self.assertEqual(C.maj.fourths(2), Bb.maj)
        self.assertEqual(fourths(C.dom7, 4), [C.dom7, F.dom7, Bb.dom7, Eb.dom7])

    def test_pitches(self):
        self.assertEqual(C.maj7s11.pitches(60, 72), [60, 64, 66, 67, 71, 72])
        self.assertEqual(C.maj.pitches(61, 63), [])

    def test_repr_reads_back(self):
        self.assertEqual(repr(Bb.dom7), "As.dom7")
        self.assertEqual(parse_set(repr(Bb.dom7)), Bb.dom7)

    def test_parse_set(self):
        self.assertEqual(parse_set("C.maj7s11"), C.maj7s11)
        self.assertEqual(parse_set("Bb.lydian"), PitchSet(Bb, "lydian"))
        for bad in ("H.maj", "C.nope", "C"):
            with self.assertRaises(ValueError):
                parse_set(bad)


class HarmonyTest(unittest.TestCase):
    def test_extended_chords(self):
        self.assertEqual(C.maj9.pitch_classes, [C, D, E, G, B])
        self.assertEqual(C.min11.pitch_classes, [C, Eb, F, G, Bb])
        self.assertEqual(C.sus9.pitch_classes, [C, D, F, G, Bb])

    def test_core_and_bass(self):
        self.assertEqual(C.maj9.core, [C, E, G, B])
        self.assertEqual(C.sus9.core, [C, F, G, Bb])
        self.assertEqual(C.maj7s11.core, [C, E, G, B])
        self.assertEqual(C.lydian.core, [C, E, G])
        self.assertEqual(G.dom7.core, G.dom7.pitch_classes)
        self.assertEqual(C.maj9.bass, [C, G])
        self.assertEqual(B.m7b5.bass, [B, F])

    def test_parent_scales(self):
        self.assertEqual(C.maj9.scale, C.major)
        self.assertEqual(C.min11.scale, C.dorian)
        self.assertEqual(C.dom7s11.scale.pitch_classes, [C, D, E, Fs, G, A, Bb])
        self.assertEqual(C.lydian.scale, C.lydian)
        for quality in HARMONY_WEIGHTS:  # every random chord's tones belong to its parent scale
            chord = getattr(C, quality)
            self.assertLessEqual(set(chord.pitch_classes), set(chord.scale.pitch_classes), quality)

    def test_resolve_fixed(self):
        self.assertEqual(resolve_notes("Fs.maj9", 3), Fs.maj9)

    def test_resolve_random_is_deterministic_and_varied(self):
        picks = [resolve_notes("random", s) for s in range(600)]
        self.assertEqual(picks[:20], [resolve_notes("random", s) for s in range(20)])
        self.assertEqual(len({p.root for p in picks}), 12)
        qualities = Counter(p.quality for p in picks)
        self.assertEqual(set(qualities), set(HARMONY_WEIGHTS))
        self.assertEqual(max(qualities, key=qualities.get), "lydian")
        for dark in ("dorian", "minor", "phrygian", "locrian"):
            self.assertNotIn(dark, qualities)
        self.assertTrue(all(3 not in p.intervals for p in picks))  # bright or ambiguous, never minor
        self.assertTrue(all(len(p.pitch_classes) == 7 or p.quality.startswith("quartal") for p in picks))

    def test_quartal_sets_are_stacked_fourths(self):
        self.assertEqual(C.quartal.pitch_classes, [C, D, F, G, Bb])
        self.assertEqual(C.quartal_bright.pitch_classes, [C, D, E, G, A])
        for quality, parent in (("quartal", "mixolydian"), ("quartal_bright", "lydian")):
            chord = getattr(C, quality)
            on_circle = {i * 7 % 12 for i in chord.intervals}  # places round the circle of 5ths
            n = len(on_circle)
            chained = any(on_circle == {(p + k) % 12 for k in range(n)} for p in range(12))
            self.assertTrue(chained, quality)  # one unbroken chain of 5ths (4ths downwards)
            self.assertEqual(chord.scale.quality, parent)
            self.assertEqual(chord.bass, [C, G])
            self.assertFalse({3, 4} & {(pc - C) % 12 for pc in chord.core}, quality)  # no 3rd in the core

    def test_resolve_random_chord_on_a_root(self):
        picks = {resolve_notes("D.random", s) for s in range(50)}
        self.assertEqual({p.root for p in picks}, {D})
        self.assertGreater(len(picks), 3)

    def test_resolve_invalid(self):
        for bad in ("H.random", "C.nope", "nope"):
            with self.assertRaises(ValueError):
                resolve_notes(bad, 0)


if __name__ == "__main__":
    unittest.main()
