import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from pedalboard.io import AudioFile

from quintet import (
    SAMPLE_RATE,
    C,
    Config,
    _,
    hairpin,
    instrument,
    leveled,
    loopable,
    loudness_db,
    midi_to_note,
    mix,
    palette,
    piece_code,
    render,
    sustain,
    voice,
    voice_line,
)
from quintet.pattern import ACCENT_DB
from quintet.render import (
    ATTACK_BEATS,
    DYNAMIC_DB,
    INSTRUMENT_TRIM_DB,
    LEVEL_LIMIT_DB,
    LEVEL_REF_DB,
    PAN,
    STAGE_DEPTH,
)
from quintet.samples import DYNAMICS
from quintet.voice import LFO_PEAK_DB

# 4 beats at 240 bpm = 1 s
PIECE = dict(
    flute=voice([1, 2], beats=2),
    oboe=voice([1, 0], beats=1),
    clarinet=voice([1, _, 2], beats=4),
    horn=voice([1], beats=4, dynamic="mp"),
    bassoon=voice([1, 2, 3, 4], beats=2),
)


def read(path):
    with AudioFile(str(path)) as f:
        return f.read(f.frames)  # (channels, frames)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = Config(argv=[], tempo=240, output_dir=self.tmp, stems=True)

    def test_mix_and_stems(self):
        paths = render("t", C.maj7s11, **PIECE)
        self.assertEqual(
            [p.name for p in paths],
            ["t.wav", "t_flute.wav", "t_oboe.wav", "t_clarinet.wav", "t_horn.wav", "t_bassoon.wav"],
        )
        mixed = read(paths[0])
        self.assertEqual(mixed.shape, (2, SAMPLE_RATE))  # 1 s stereo
        self.assertLessEqual(float(np.abs(mixed).max()), 10 ** (-1 / 20) + 1e-3)  # mastered: -1 dBFS ceiling
        self.assertEqual(read(paths[1]).shape[0], 1)

    def test_flute_is_panned_left(self):
        Config(argv=[], tempo=240, output_dir=self.tmp, reverb=0, master=False)
        solo = {n: voice([0], beats=4) for n in PIECE} | {"flute": voice([1], beats=4)}
        left, right = read(render("solo", C.maj7s11, **solo)[0])
        self.assertGreater(np.abs(left).sum(), 1.5 * np.abs(right).sum())

    def test_mild_seating(self):
        self.assertTrue(all(abs(p) <= 0.4 for p in PAN.values()))
        self.assertTrue(abs(PAN["horn"]) <= 0.1 and abs(PAN["bassoon"]) <= 0.1)

    def test_stage_puts_the_horn_at_the_back(self):
        self.assertEqual(max(STAGE_DEPTH, key=STAGE_DEPTH.get), "horn")
        self.assertTrue(STAGE_DEPTH["flute"] == STAGE_DEPTH["oboe"] == 0)
        tone = np.sin(np.arange(SAMPLE_RATE) * 2 * np.pi * 440 / SAMPLE_RATE).astype(np.float32)
        lines = {n: tone for n in PIECE}
        voices = {n: voice([1], beats=4) for n in PIECE}
        for solo in ("flute", "horn"):
            dry, early, send = mix({n: tone if n == solo else 0 * tone for n in lines}, voices)
            self.assertEqual(dry.shape, (2, SAMPLE_RATE))
            self.assertTrue(np.any(early))
            ratio = np.abs(send).sum() / np.abs(dry).sum()
            if solo == "flute":
                np.testing.assert_allclose(send, dry)
            else:
                self.assertGreater(ratio, 1.5)  # the back of the stage is wetter

    def test_line_cuts_and_rests(self):
        line = voice_line(instrument("horn"), voice([1, 0], beats=2), C.maj7s11, 2, 240)  # 0.25 s note, 0.25 s rest
        quarter = SAMPLE_RATE // 4
        self.assertEqual(len(line), 2 * quarter)
        self.assertAlmostEqual(float(line[quarter - 1]), 0, places=4)  # faded to silence at the cut
        self.assertTrue(np.any(line[:quarter]))
        self.assertFalse(np.any(line[quarter:]))

    def test_sustain_extends_smoothly(self):
        sample = instrument("oboe").note("A4", "mf", "1s").load()
        n = 6 * SAMPLE_RATE
        out = sustain(sample, n)
        self.assertEqual(len(out), n)
        self.assertLessEqual(np.abs(np.diff(out)).max(), 1.5 * np.abs(np.diff(sample)).max())  # no clicks
        tail = len(sample) // 4
        np.testing.assert_allclose(out[-tail:], sample[-tail:], atol=1e-6)  # the natural release ends it

    def test_loopable_only_when_it_will_not_stutter(self):
        second = SAMPLE_RATE
        self.assertTrue(loopable(3 * second, 6 * second))  # 2.1 s loop, ~1.5 repeats
        self.assertFalse(loopable(3 * second, 12 * second))  # would need ~4.5 repeats
        self.assertFalse(loopable(second, 2 * second))  # 0.4 s loop: too short

    def test_unloopable_long_note_plays_once_then_rests(self):
        line = voice_line(instrument("oboe"), voice([1, _, _, _], beats=16), C.maj7s11, 16, 120)  # 8 s note
        self.assertEqual(len(line), 8 * SAMPLE_RATE)
        self.assertTrue(np.any(line[:SAMPLE_RATE]))
        self.assertFalse(np.any(line[6 * SAMPLE_RATE :]))  # the oboe's longest recording is ~2 s: no stutter loop

    def test_long_notes_get_the_actually_longest_samples(self):
        bassoon = instrument("bassoon")
        chosen = bassoon.note("G2", "mf", 1.4, max_dynamic="mf")
        candidates = [s for d in ("pp", "p", "mp", "mf") for s in bassoon.find("G2", d)]
        if any(s.seconds >= 1.4 for s in candidates):
            self.assertGreaterEqual(chosen.seconds, 1.4)
        else:
            self.assertEqual(chosen.seconds, max(s.seconds for s in candidates))
        self.assertGreater(chosen.seconds, 0.39)  # not the 0.39 s "0.5s" file piece_8 used

    def test_instruments_are_level_matched(self):
        for dyn in ("p", "mf", "f"):
            for name in ("flute", "oboe", "clarinet", "horn", "bassoon"):
                inst = instrument(name)
                for m in palette(C.lydian, inst):
                    sample = inst.note(midi_to_note(m), dyn, 1.0)
                    level = LEVEL_REF_DB + DYNAMIC_DB[dyn] + INSTRUMENT_TRIM_DB[name]
                    self.assertAlmostEqual(loudness_db(leveled(sample, dyn)), level, delta=0.5, msg=(name, m, dyn))

    def test_levelling_only_ever_turns_a_recording_down(self):
        # the loudest a note can be asked for: ff, the biggest metric accent (each level of nesting
        # adds half the one above, so under 2x the top) and the most humanize adds
        most = DYNAMIC_DB["ff"] + 2 * ACCENT_DB[0] + LEVEL_LIMIT_DB
        for name in ("flute", "oboe", "clarinet", "horn", "bassoon"):
            inst = instrument(name)
            usable = DYNAMICS[: DYNAMICS.index(inst.max_layer) + 1]
            for sample in (s for s in inst.notes if s.dynamic in usable or s.midi in inst.gap_filled):
                gain = LEVEL_REF_DB + most + INSTRUMENT_TRIM_DB[name] - loudness_db(sample.load())
                self.assertLessEqual(gain, 0, (name, sample.path.name))

    def test_layers_capped_at_mp(self):
        for name in ("flute", "oboe", "clarinet", "horn", "bassoon"):
            inst = instrument(name)
            with mock.patch.object(inst, "note", wraps=inst.note) as note:
                for dyn in ("p", "mp", "mf", "ff"):
                    voice_line(inst, voice([1, 0, [2, 0], 4, 0], beats=2, dynamic=dyn), C.lydian, 2, 60)
            picks = [inst.note(*c.args, **c.kwargs) for c in note.call_args_list]
            # louder only where a gap-filled pitch has no soft recording at all
            used = {s.dynamic for s in picks if s.midi not in inst.gap_filled}
            self.assertTrue(used <= {"pp", "p", "mp"}, (name, used))
            if "mp" in inst.dynamics:
                self.assertIn("mp", used)

    def test_gap_filled_pitches_borrow_the_nearest_louder_layer_at_the_soft_level(self):
        # the horn's gap was only ever recorded at ff
        for name, gap, layer in (
            ("oboe", ("C5", "Cs5", "D5", "Ds5"), "mf"),
            ("horn", ("Cs5", "Ds5", "E5", "F5"), "ff"),
        ):
            inst = instrument(name)
            self.assertEqual({midi_to_note(m) for m in inst.gap_filled}, set(gap))
            self.assertTrue(inst.gap_filled <= inst.playable)
            for note in gap:
                sample = inst.note(note, "p", 1.0, max_dynamic=inst.max_layer)
                self.assertEqual(sample.dynamic, layer, (name, note))
                level = LEVEL_REF_DB + DYNAMIC_DB["p"] + INSTRUMENT_TRIM_DB[name]
                self.assertAlmostEqual(loudness_db(leveled(sample, "p")), level, delta=0.5, msg=(name, note))
        flute = instrument("flute")  # not gap-filled: its unrecorded top note stays unplayable
        self.assertEqual(flute.gap_filled, frozenset())
        with self.assertRaises(KeyError):
            flute.note("F7", "p", 1.0, max_dynamic=flute.max_layer)

    def test_hairpin_shape(self):
        shaped = hairpin(np.ones(1000, dtype=np.float32))
        self.assertLess(shaped[0], 0.04)
        self.assertLess(shaped[-1], 0.04)
        self.assertEqual(int(np.argmax(shaped)), 400)  # peaks at 40% of the note
        self.assertGreater(shaped[400], 0.99)  # at the voice's level, no boost

    def test_hairpin_starts_quiet_and_blooms_late(self):
        n = 4 * SAMPLE_RATE
        shaped = hairpin(np.ones(n, dtype=np.float32))
        db = lambda share: 20 * np.log10(shaped[int(share * n)])
        self.assertLess(db(0.1), -15)  # still quiet a tenth of the way in
        self.assertLess(db(0.2), -5)
        self.assertGreater(db(0.35), -1.5)  # then blooms into the peak
        self.assertLessEqual(float(shaped.max()), 1.0 + 1e-6)

    def test_long_notes_swell(self):
        # a 2 s note then a 1 s rest (a note with no rest would join itself across the loop point)
        line = voice_line(instrument("flute"), voice([1, _, 0], beats=3), C.maj7s11, 3, 60)
        n, peak = 2 * SAMPLE_RATE, lambda a: float(np.abs(a).max())
        middle = peak(line[n // 3 : n // 2])
        self.assertLess(peak(line[: n // 20]), middle / 3)  # starts from near silence
        self.assertLess(peak(line[n - n // 20 : n]), middle / 3)  # and dies away

    def test_short_notes_fade_in_with_tempo(self):
        for tempo in (60, 120):
            line = voice_line(instrument("flute"), voice([1, 0], beats=2), C.maj7s11, 2, tempo)  # 1 s, 0.5 s
            k = round(ATTACK_BEATS * 60 / tempo * SAMPLE_RATE)
            self.assertAlmostEqual(float(line[0]), 0, places=4)
            self.assertLess(np.abs(line[: k // 8]).max(), np.abs(line[k : 2 * k]).max() / 4)

    def boundary(self, pattern):
        """RMS just around the change of note at 1 s, against the steady part of the note after it."""
        line = voice_line(instrument("clarinet"), voice(pattern, beats=3), C.lydian, 3, 60)
        rms = lambda a, b: float(np.sqrt(np.mean(np.square(line[int(a * SAMPLE_RATE) : int(b * SAMPLE_RATE)]))))
        return rms(0.98, 1.06) / rms(1.2, 1.35), line

    def test_legato_has_no_gap_between_notes(self):
        legato, _ = self.boundary([1, 3, 0])  # two notes, then a rest
        articulated, _ = self.boundary([[1, 0], 3, 0])  # the first note ends early: the second is articulated
        self.assertGreater(legato, 0.6)
        self.assertGreater(legato, 2 * articulated)

    def test_repeated_pitch_dips_slightly_and_renewal_is_seamless(self):
        legato, _ = self.boundary([1, 3, 0])
        repeat, _ = self.boundary([1, 1, 0])
        renew, _ = self.boundary([1, "1=", 0])
        self.assertLess(repeat, legato)  # the repeat is heard
        self.assertGreater(repeat, 0.2)  # but not as a gap
        self.assertGreater(renew, 0.7)  # a renewal just carries on

    def test_phrase_continues_over_the_loop_point(self):
        line = voice_line(instrument("clarinet"), voice([1, 3], beats=2), C.lydian, 2, 60)  # no rest at all
        self.assertEqual(len(line), 2 * SAMPLE_RATE)
        tail = float(np.abs(line[:200]).max()) / float(np.abs(line).max())
        self.assertGreater(tail, 0.01)  # the last note's tail sounds at the start

    def test_volume_sine_in_stems(self):
        Config(argv=[], tempo=60, output_dir=self.tmp, stems=True, reverb=0, master=False)
        silent = {n: voice([0], beats=4) for n in PIECE}

        def horn_peaks(label, horn):  # peak of each 1 s note in the horn stem of a 4 s piece
            render(label, C.maj7s11, **dict(silent, horn=horn))
            stem = read(self.tmp / f"{label}_horn.wav")[0]
            return [float(np.abs(stem[i * SAMPLE_RATE : (i + 1) * SAMPLE_RATE]).max()) for i in range(4)]

        steady = horn_peaks("steady", voice([1, 1, 1, 1], beats=4))
        swaying = horn_peaks("swaying", voice([1, 1, 1, 1], beats=4, lfo=1))  # loud, quiet at 2 s, loud
        self.assertAlmostEqual(swaying[0] / steady[0], 10 ** (LFO_PEAK_DB / 20), delta=0.1)
        self.assertLess(min(swaying[1:3]), 0.75 * steady[1])

    def test_missing_voice(self):
        with self.assertRaises(ValueError):
            render("x", C.maj7s11, flute=PIECE["flute"])

    def test_piece_code_reproduces_wav(self):
        self.config.stems = False
        original = render("orig", C.maj7s11, **PIECE)[0].read_bytes()
        script = self.tmp / "orig.py"
        script.write_text(piece_code("orig", C.maj7s11, PIECE, seed=7))
        self.assertNotIn("sys.path", script.read_text())
        out = self.tmp / "rerun"
        subprocess.run([sys.executable, str(script), "--output-dir", str(out)], check=True, cwd=self.tmp)
        self.assertEqual((out / "orig.wav").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()


class HumanizeTest(unittest.TestCase):
    def setUp(self):
        Config(argv=[], tempo=60)

    def line(self, pattern, beats, humanize=True, name="clarinet"):
        return voice_line(instrument(name), voice(pattern, beats=beats), C.lydian, beats, 60, humanize)

    def test_deterministic_and_different_from_the_grid(self):
        pattern = [1, 2, 3, 2, 1, 0, 3, 0]
        self.assertTrue(np.array_equal(self.line(pattern, 8), self.line(pattern, 8)))
        self.assertFalse(np.array_equal(self.line(pattern, 8), self.line(pattern, 8, humanize=False)))

    def test_onsets_land_near_the_grid(self):
        line = self.line([1, 0] * 8, 16)  # a note every 2 s, rests between
        threshold = 0.05 * float(np.abs(line).max())
        offsets = []
        for k in range(8):
            grid = 2 * k * SAMPLE_RATE
            window = np.abs(line[max(0, grid - SAMPLE_RATE // 10) : grid + SAMPLE_RATE // 2])
            first = int(np.argmax(window > threshold)) + max(0, grid - SAMPLE_RATE // 10) - grid
            offsets.append(first / SAMPLE_RATE * 1000)
        self.assertLess(max(map(abs, offsets)), 25 + 10 + 60)  # timing limit + lean + the attack's own rise
        self.assertGreater(max(offsets) - min(offsets), 2)  # not all on the same spot

    def test_long_phrases_breathe(self):
        steady = self.line([1, 2, 3, 2] * 4, 16, humanize=False)  # 16 s with no rest at all
        breathing = self.line([1, 2, 3, 2] * 4, 16)
        quiet = (
            lambda x: sum(  # 50 ms windows far below the line's level
                float(np.sqrt(np.mean(np.square(x[i : i + 2205])))) < 0.05 * float(np.sqrt(np.mean(np.square(x))))
                for i in range(0, len(x) - 2205, 2205)
            )
        )
        self.assertEqual(quiet(steady), 0)
        self.assertGreaterEqual(quiet(breathing), 2)  # at least one breath of 150 ms or more

    def test_long_tones_leave_a_gap_before_the_next_note(self):
        def gap(line, at):  # longest run of quiet 10 ms windows in the second before `at` seconds
            window = SAMPLE_RATE // 100
            loud = float(np.sqrt(np.mean(np.square(line))))
            longest = run = 0
            for k in range((at - 1) * SAMPLE_RATE, at * SAMPLE_RATE, window):
                quiet = float(np.sqrt(np.mean(np.square(line[k : k + window])))) < 0.05 * loud
                run = run + 1 if quiet else 0
                longest = max(longest, run)
            return longest * window / SAMPLE_RATE

        pattern = [1, _, _, _, 2, _, _, _]  # two 4-beat tones, back to back
        self.assertLess(gap(self.line(pattern, 8, humanize=False), 4), 0.05)  # legato
        played = self.line(pattern, 8)
        self.assertGreater(gap(played, 4), 0.2)
        self.assertGreater(gap(played, 8), 0.2)  # across the loop point too

    def test_repeats_rotate_between_recordings(self):
        def three_times(humanize):  # one note per 4 s cycle, three cycles: metrically identical
            return voice_line(instrument("oboe"), voice([1, 0, 0, 0], beats=4), C.lydian, 12, 60, humanize)

        def notes(line):
            return [line[k * 4 * SAMPLE_RATE + SAMPLE_RATE // 10 : k * 4 * SAMPLE_RATE + SAMPLE_RATE] for k in range(3)]

        plain, played = notes(three_times(False)), notes(three_times(True))
        self.assertTrue(np.allclose(plain[0], plain[1]) and np.allclose(plain[1], plain[2]))
        peak = float(np.abs(played[0]).max())
        self.assertGreater(float(np.abs(played[0] - played[1]).max()), 0.05 * peak)  # another take (or level)


class IntonationTest(unittest.TestCase):
    def test_retuned_shifts_pitch_by_cents(self):
        from quintet.render import retuned

        t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
        tone = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        for cents in (4.0, -4.0):
            shifted = retuned(tone, cents)
            spectrum = np.abs(np.fft.rfft(shifted * np.hanning(len(shifted)), n=1 << 22))
            peak = np.argmax(spectrum) * SAMPLE_RATE / (1 << 22)
            self.assertAlmostEqual(1200 * np.log2(peak / 440.0), cents, delta=0.3)
        self.assertIs(retuned(tone, 0.0), tone)

    def test_off_by_default_and_deterministic_when_on(self):
        self.assertTrue(Config(argv=[], tempo=60).intonation)
        self.assertFalse(Config(argv=["--no-intonation"], tempo=60).intonation)

        def line(on):
            return voice_line(instrument("flute"), voice([1, 2, 3, 0], beats=4), C.lydian, 8, 60, False, on)

        self.assertFalse(np.array_equal(line(False), line(True)))
        self.assertTrue(np.array_equal(line(True), line(True)))
        Config(argv=[], tempo=60)


class ConcertPitchTest(unittest.TestCase):
    def test_a440_by_default(self):
        self.assertEqual(Config(argv=[], tempo=60).a4, 440.0)
        self.assertEqual(Config(argv=["--a4", "432"], tempo=60).a4, 432.0)
        Config(argv=[], tempo=60)

    def test_a4_shifts_every_note_by_its_ratio(self):
        def peak(a4):  # the strongest partial of one held note
            line = voice_line(instrument("flute"), voice([1], beats=4), C.lydian, 4, 60, False, False, a4)
            body = line[SAMPLE_RATE // 2 : 3 * SAMPLE_RATE]
            spectrum = np.abs(np.fft.rfft(body * np.hanning(len(body)), n=1 << 22))
            return np.argmax(spectrum) * SAMPLE_RATE / (1 << 22)

        self.assertAlmostEqual(1200 * np.log2(peak(432.0) / peak(440.0)), 1200 * np.log2(432 / 440), delta=0.5)
