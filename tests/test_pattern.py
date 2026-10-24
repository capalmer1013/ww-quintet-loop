import copy
import unittest
from fractions import Fraction as Fr

from quintet.pattern import Event, _, _levels, accents, event_paths, expand, leaves, tile


def shape(events):
    return [(e.start, e.beats, e.index) for e in events]


class ExpandTest(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(shape(expand([1, 2, 3, 4], 4)), [(0, 1, 1), (1, 1, 2), (2, 1, 3), (3, 1, 4)])

    def test_nested_and_triplet(self):
        events = expand([1, [2, 3], [4, 5, 6]], 3)
        self.assertEqual(
            shape(events),
            [
                (0, 1, 1),
                (1, Fr(1, 2), 2),
                (Fr(3, 2), Fr(1, 2), 3),
                (2, Fr(1, 3), 4),
                (Fr(7, 3), Fr(1, 3), 5),
                (Fr(8, 3), Fr(1, 3), 6),
            ],
        )

    def test_holds_and_rests(self):
        self.assertEqual(shape(expand([1, _, 0, _], 4)), [(0, 2, 1), (2, 2, None)])

    def test_tiles_span_exactly(self):
        events = expand([1, [2, [3, 4]], _, 0], Fr(7, 3))
        self.assertEqual(events[0].start, 0)
        for a, b in zip(events, events[1:]):
            self.assertEqual(a.start + a.beats, b.start)
        self.assertEqual(events[-1].start + events[-1].beats, Fr(7, 3))

    def test_scale_steps(self):
        third, sixth = Fr(2, 3), Fr(1, 3)
        self.assertEqual(
            shape(expand([1, "3+", ["2-", 2]], 2)),
            [(0, third, 1), (third, third, "3+"), (2 * third, sixth, "2-"), (Fr(5, 3), sixth, 2)],
        )
        self.assertEqual(shape(expand(["3=", "3+=", "3-="], 3)), [(0, 1, "3="), (1, 1, "3+="), (2, 1, "3-=")])
        for bad in ("0+", "3*", "+3", "3", "3=+", "3=="):
            with self.assertRaises(ValueError):
                expand([bad], 1)

    def test_event_paths_line_up_with_events(self):
        pattern = [_, 1, [2, _, "3+"], 0, _]
        self.assertEqual(event_paths(pattern), [None, (1,), (2, 0), (2, 2), (3,)])
        self.assertEqual(len(event_paths(pattern)), len(expand(pattern, 5)))

    def test_leaves_include_holds(self):
        self.assertEqual(
            leaves([1, [_, 2]], 2),
            [((0,), 0, 1, 1), ((1, 0), 1, Fr(1, 2), _), ((1, 1), Fr(3, 2), Fr(1, 2), 2)],
        )

    def test_metric_levels(self):
        self.assertEqual(_levels(4), [0, 3, 1, 3])  # beat 1, then beat 3, then the off-beats
        self.assertEqual(_levels(3), [0, 2, 3])  # middle a touch stronger than the last
        self.assertEqual(_levels(7)[0], 0)
        self.assertEqual(_levels(7).index(1), 4)  # the group start nearest the middle

    def test_accents_follow_the_nesting(self):
        a = accents([1, [2, 3], 4, [5, 6, 7]])
        self.assertEqual(len(a), 7)
        self.assertEqual(max(a), a[0])  # the downbeat is strongest
        self.assertGreater(a[3], a[2])  # beat 3 of 4 beats an off-beat sub-note
        self.assertEqual(accents([_, 1])[0], 0.0)  # a leading hold isn't accented
        pattern = [_, 1, [2, _, "3+"], 0, _]
        self.assertEqual(len(accents(pattern)), len(expand(pattern, 5)))

    def test_hold_survives_copying(self):
        self.assertIs(copy.deepcopy([_])[0], _)

    def test_invalid_elements_report_path(self):
        for bad, path in (
            ([1, 1.5], "pattern[1]"),
            ([1, [2, (3,)]], "pattern[1][1]"),
            ([True], "pattern[0]"),
            ([1, []], "pattern[1]"),
            ([-1], "pattern[0]"),
            (["A4"], "pattern[0]"),
        ):
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
