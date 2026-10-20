import math
import random
import unittest

from utils.reverb import decay_seconds, reverb


def rms(a):
    return math.sqrt(sum(x * x for x in a) / len(a)) if a else 0.0


def notes(n, seed=1):
    """Bursts of noise a quarter second long, every second: a stand-in for a piece."""
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) if (i // 11025) % 4 == 0 else 0.0 for i in range(n)]


class ReverbTest(unittest.TestCase):
    def test_dry_when_off(self):
        x = notes(44100)
        self.assertEqual(reverb(x, x, 0, 0.8), (x, x))

    def test_length_and_silence(self):
        x = notes(44101)  # odd length
        left, right = reverb(x, x, 0.5, 0.5)
        self.assertEqual((len(left), len(right)), (44101, 44101))
        zeros = [0.0] * 30000
        self.assertEqual(reverb(zeros, zeros, 1, 0.8), (zeros, zeros))

    def test_impulse_decays(self):
        n = 44100 * 8
        x = [0.0] * n
        x[0] = 1.0
        left, _ = reverb(x, x, 1, 0.8)
        wet = left[1:]
        windows = [rms(wet[i:i + 22050]) for i in range(22050, n - 22050, 22050)]
        self.assertGreater(windows[0], 0)
        self.assertTrue(all(b < a for a, b in zip(windows, windows[1:])), windows)
        # about 60 dB down after the decay time
        t = round(decay_seconds(0.8) * 44100)
        self.assertLess(rms(wet[t:t + 4410]) / rms(wet[2205:6615]), 10 ** (-40 / 20))

    def test_tail_wraps_over_the_loop_point(self):
        x = notes(44100 * 3)
        once, _ = reverb(x, x, 1, 0.8)
        twice, _ = reverb(x + x, x + x, 1, 0.8)
        # the reverb of one loop matches a loop that follows another, including its first second
        diff = rms([a - b for a, b in zip(once, twice[len(x):])])
        self.assertLess(diff, 0.01 * rms(once))

    def test_stereo_width(self):
        x = notes(44100 * 2)
        left, right = reverb(x, x, 1, 0.8)
        self.assertGreater(rms([a - b for a, b in zip(left, right)]), 0.1 * rms(left))

    def test_bigger_room_rings_longer(self):
        self.assertGreater(decay_seconds(1.0), decay_seconds(0.8))
        self.assertGreater(decay_seconds(0.8), decay_seconds(0.2))

    def test_invalid(self):
        x = notes(1000)
        for amount, room in ((-0.1, 0.5), (0.5, 1.5), (0.5, -0.1)):
            with self.assertRaises(ValueError):
                reverb(x, x, amount, room)


if __name__ == "__main__":
    unittest.main()
