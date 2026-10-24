"""Config: command-line parsing, seeds (explicit, ranges and clock-claimed) and the tempo picked per
seed; and the CLI rejecting bad input before it makes anything."""

import io
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np

from quintet import Config
from quintet.cli import check_reverb_ir, main
from quintet.render import write_wav


class CommandLineTest(unittest.TestCase):
    def test_unknown_flag_is_an_error(self):
        with redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            Config(argv=["--stems", "--stemz"])
        self.assertIn("unrecognized arguments: --stemz", err.getvalue())
        Config(argv=[], tempo=60)

    def test_reads_sys_argv_by_default(self):  # how a piece file run with flags picks them up
        with mock.patch.object(sys, "argv", ["piece_7.py", "--stems", "--tempo", "90"]):
            config = Config(tempo=60, reverb=0.5)
        self.assertEqual((config.stems, config.tempo, config.reverb), (True, 90, 0.5))
        Config(argv=[], tempo=60)

    def test_current_ignores_the_command_line(self):  # so a test runner's own flags are not parsed
        Config._current = None
        with mock.patch.object(sys, "argv", ["pytest", "-q", "--stems"]):
            self.assertFalse(Config.current().stems)
        Config(argv=[], tempo=60)


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

    def test_empty_range_is_an_error(self):
        for seeds in ("5-3", "5-5"):
            with self.assertRaisesRegex(ValueError, "empty"):
                Config(argv=[], tempo=60, seeds=seeds).seed_range()
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


class MainFailsFastTest(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def main(self, *flags):
        with mock.patch.object(sys, "argv", ["quintet", "--output-dir", str(self.out), *flags]):
            try:
                main()
            finally:
                Config(argv=[], tempo=60)

    def test_bad_reverb_ir_before_any_piece(self):
        for bad in (self.out / "missing.wav", Path(__file__)):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "--reverb-ir"):
                self.main("--reverb-ir", str(bad))
        self.assertEqual(list(self.out.iterdir()), [])  # not even a seed claim

    def test_empty_seed_range_before_any_piece(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            self.main("--seeds", "5-3")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_good_reverb_ir_passes(self):
        ir = write_wav(self.out / "ir.wav", np.r_[1.0, np.zeros(999)])
        check_reverb_ir(Config(argv=[], tempo=60, reverb_ir=str(ir)))
        Config(argv=[], tempo=60)

    def test_reverb_ir_at_reverb_0_warns(self):
        config = Config(argv=[], tempo=60, reverb=0, reverb_ir=str(self.out / "missing.wav"))
        with redirect_stderr(io.StringIO()) as err:
            check_reverb_ir(config)  # unused, so not read
        self.assertIn("--reverb-ir is unused at --reverb 0", err.getvalue())
        Config(argv=[], tempo=60)
