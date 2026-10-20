import unittest
from fractions import Fraction as Fr

from utils.pattern import Event, _, expand, tile


def shape(events):
    return [(e.start, e.beats, e.index) for e in events]


class ExpandTest(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(shape(expand([1, 2, 3, 4], 4)), [(0, 1, 1), (1, 1, 2), (2, 1, 3), (3, 1, 4)])

    def test_nested_and_triplet(self):
        events = expand([1, [2, 3], [4, 5, 6]], 3)
        self.assertEqual(shape(events), [
            (0, 1, 1), (1, Fr(1, 2), 2), (Fr(3, 2), Fr(1, 2), 3),
            (2, Fr(1, 3), 4), (Fr(7, 3), Fr(1, 3), 5), (Fr(8, 3), Fr(1, 3), 6),
        ])

    def test_holds_and_rests(self):
        self.assertEqual(shape(expand([1, _, 0, _], 4)), [(0, 2, 1), (2, 2, None)])

    def test_tiles_span_exactly(self):
        events = expand([1, [2, [3, 4]], _, 0], Fr(7, 3))
        self.assertEqual(events[0].start, 0)
        for a, b in zip(events, events[1:]):
            self.assertEqual(a.start + a.beats, b.start)
        self.assertEqual(events[-1].start + events[-1].beats, Fr(7, 3))

    def test_invalid_elements_report_path(self):
        for bad, path in (([1, 1.5], "pattern[1]"), ([1, [2, (3,)]], "pattern[1][1]"), ([True], "pattern[0]"),
                          ([1, []], "pattern[1]"), ([-1], "pattern[0]"), (["A4"], "pattern[0]")):
            with self.assertRaises(ValueError) as cm:
                expand(bad, 1)
            self.assertTrue(str(cm.exception).startswith(path + ":"), cm.exception)


class TileTest(unittest.TestCase):
    def test_repeats(self):
        self.assertEqual(shape(tile([1, 2], 2, 4)), [(0, 1, 1), (1, 1, 2), (2, 1, 1), (3, 1, 2)])

    def test_leading_hold_continues_previous_cycle(self):
        self.assertEqual(shape(tile([_, 2], 2, 4)), [(0, 1, None), (1, 2, 2), (3, 1, 2)])

    def test_must_be_whole_cycles(self):
        with self.assertRaises(ValueError):
            tile([1], 3, 4)

    def test_event_type(self):
        self.assertIsInstance(tile([1], 1, 1)[0], Event)


if __name__ == "__main__":
    unittest.main()
