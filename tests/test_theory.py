import unittest

from utils.theory import (A, B, Bb, C, D, E, Eb, F, Fs, G, M3, P4, P5, As, PitchSet, fifths, fourths,
                          parse_set)


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
            C.nope
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


if __name__ == "__main__":
    unittest.main()
