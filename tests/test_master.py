import math
import random
import unittest
from itertools import accumulate

from utils.master import BLOCK, CEILING_DB, TARGET_LUFS, eq, loudness_lufs, master


def tone_bursts(seconds, seed=1):
    """A quiet stand-in for a piece: alternating loud and soft noise bursts."""
    rng = random.Random(seed)
    n = 44100 * seconds
    return [rng.uniform(-1, 1) * (3000 if (i // 22050) % 2 else 300) for i in range(n)]


def sine_gain_db(hz):
    n = 44100
    x = [math.sin(2 * math.pi * hz * i / 44100) for i in range(n)]
    y = eq(x)
    mid = slice(8000, n - 8000)
    return 10 * math.log10(sum(v * v for v in y[mid]) / sum(v * v for v in x[mid]))


class EqTest(unittest.TestCase):
    def test_response_shape(self):
        self.assertLess(sine_gain_db(40), -12)  # rumble removed
        self.assertLess(sine_gain_db(300), -2)  # mud cut
        self.assertGreater(sine_gain_db(3500), 2.5)  # presence lift
        self.assertAlmostEqual(sine_gain_db(1000), 0, delta=1.5)  # mids roughly untouched


class MasterTest(unittest.TestCase):
    def setUp(self):
        self.left = tone_bursts(12)
        self.right = tone_bursts(12, seed=2)
        self.out = master(self.left, self.right)

    def test_loudness_and_ceiling(self):
        left, right = self.out
        power = [(sum(v * v for v in left[i:i + BLOCK]) + sum(v * v for v in right[i:i + BLOCK]))
                 / (2 * BLOCK * 32767 ** 2) for i in range(0, len(left), BLOCK)]
        self.assertAlmostEqual(loudness_lufs(power), TARGET_LUFS, delta=1.5)
        peak = max(max(map(abs, left)), max(map(abs, right)))
        self.assertLessEqual(peak, 32767 * 10 ** (CEILING_DB / 20) + 1)

    def test_length_and_loop_seam(self):
        left, right = self.out
        self.assertEqual((len(left), len(right)), (len(self.left), len(self.right)))
        # the gain at the very end ramps into the gain at the very start (it wraps)
        g_end = left[-1] / self.left[-1] if self.left[-1] else 1
        g_start = left[0] / self.left[0] if self.left[0] else 1
        self.assertAlmostEqual(g_end, g_start, delta=0.15 * g_start)

    def test_compression_narrows_the_range(self):
        def spread(x):
            loud = max(sum(v * v for v in x[i:i + 22050]) for i in range(0, len(x), 22050))
            soft = min(sum(v * v for v in x[i:i + 22050]) for i in range(0, len(x), 22050))
            return 10 * math.log10(loud / soft)
        self.assertLess(spread(self.out[0]), spread(self.left) - 3)


if __name__ == "__main__":
    unittest.main()
