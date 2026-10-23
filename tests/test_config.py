"""Config: seeds (explicit, ranges and clock-claimed) and the tempo picked per seed."""

import tempfile
import time
import unittest
from pathlib import Path

from quintet import Config


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
