import subprocess
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest import mock

from utils import (SAMPLE_RATE, Config, C, _, hairpin, instrument, leveled, loudness_db, midi_to_note, palette,
                   loopable, piece_code, render, sustain, voice, voice_line)
from utils.render import ATTACK_BEATS, PEAK

# 4 beats at 240 bpm = 1 s
PIECE = dict(
    flute=voice([1, 2], beats=2),
    oboe=voice([1, 0], beats=1),
    clarinet=voice([1, _, 2], beats=4),
    horn=voice([1], beats=4, dynamic="mp"),
    bassoon=voice([1, 2, 3, 4], beats=2),
)


def read(path):
    with wave.open(str(path)) as w:
        return w.getnchannels(), array("h", w.readframes(w.getnframes()))


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = Config(argv=[], tempo=240, output_dir=self.tmp, stems=True)

    def test_mix_and_stems(self):
        paths = render("t", C.maj7s11, **PIECE)
        self.assertEqual([p.name for p in paths],
                         ["t.wav", "t_flute.wav", "t_oboe.wav", "t_clarinet.wav", "t_horn.wav", "t_bassoon.wav"])
        channels, frames = read(paths[0])
        self.assertEqual(channels, 2)
        self.assertEqual(len(frames), 2 * SAMPLE_RATE)  # 1 s stereo
        self.assertLessEqual(max(map(abs, frames)), round(PEAK * 32767))
        self.assertEqual(read(paths[1]), (1, read(paths[1])[1]))

    def test_flute_is_panned_left(self):
        solo = {n: voice([0], beats=4) for n in PIECE} | {"flute": voice([1], beats=4)}
        _, frames = read(render("solo", C.maj7s11, **solo)[0])
        left, right = frames[0::2], frames[1::2]
        self.assertGreater(sum(map(abs, left)), 1.5 * sum(map(abs, right)))

    def test_mild_seating(self):
        from utils.render import PAN
        self.assertTrue(all(abs(p) <= 0.4 for p in PAN.values()))
        self.assertTrue(abs(PAN["horn"]) <= 0.1 and abs(PAN["bassoon"]) <= 0.1)

    def test_line_cuts_and_rests(self):
        horn = instrument("horn")
        line = voice_line(horn, voice([1, 0], beats=2), C.maj7s11, 2, 240)  # note 0.25 s, rest 0.25 s
        quarter = SAMPLE_RATE // 4
        self.assertEqual(len(line), 2 * quarter)
        self.assertEqual(line[quarter - 1], 0)  # faded to silence at the cut
        self.assertTrue(any(line[:quarter]))
        self.assertFalse(any(line[quarter:]))

    def test_sustain_extends_smoothly(self):
        sample = instrument("oboe").note("A4", "mf", "1s").load()
        n = 6 * SAMPLE_RATE
        out = sustain(sample, n)
        self.assertEqual(len(out), n)
        jump = lambda a: max(abs(x - y) for x, y in zip(a, a[1:]))  # noqa: E731
        self.assertLessEqual(jump(out), 1.5 * jump(sample))  # no clicks at the loop seams
        tail = len(sample) // 4
        self.assertEqual(out[-tail:], sample[-tail:])  # the natural release ends the note
        rms = lambda a: (sum(x * x for x in a) / len(a)) ** 0.5  # noqa: E731
        self.assertGreater(rms(out[n // 2 - 4410:n // 2 + 4410]), 0.3 * rms(sample))  # still sounding mid-note

    def test_loopable_only_when_it_will_not_stutter(self):
        second = SAMPLE_RATE
        self.assertTrue(loopable(array("h", [1000] * 3 * second), 6 * second))  # 2.1 s loop, ~1.5 repeats
        self.assertFalse(loopable(array("h", [1000] * 3 * second), 12 * second))  # would need ~4.5 repeats
        self.assertFalse(loopable(array("h", [1000] * second), 2 * second))  # 0.4 s loop: too short

    def test_unloopable_long_note_plays_once_then_rests(self):
        line = voice_line(instrument("oboe"), voice([1, _, _, _], beats=16), C.maj7s11, 16, 120)  # 8 s note
        self.assertEqual(len(line), 8 * SAMPLE_RATE)
        self.assertTrue(any(line[:SAMPLE_RATE]))
        self.assertFalse(any(line[6 * SAMPLE_RATE:]))  # the oboe's longest sample is ~2 s: no stutter loop

    def test_long_notes_get_the_actually_longest_samples(self):
        bassoon = instrument("bassoon")
        chosen = bassoon.note("G2", "mf", 1.4, max_dynamic="mf")
        candidates = [s for d in ("pp", "p", "mp", "mf") for s in bassoon.find("G2", d)]
        covering = [s for s in candidates if s.seconds >= 1.4]
        if covering:
            self.assertGreaterEqual(chosen.seconds, 1.4)
        else:
            self.assertEqual(chosen.seconds, max(s.seconds for s in candidates))
        self.assertGreater(chosen.seconds, 0.39)  # not the 0.39 s "0.5s" file piece_8 used

    def test_instruments_are_level_matched(self):
        for dyn, target in (("p", -32), ("mf", -24), ("f", -21)):
            for name in ("flute", "oboe", "clarinet", "horn", "bassoon"):
                inst = instrument(name)
                for m in palette(C.lydian, inst):
                    sample = inst.note(midi_to_note(m), dyn, 1.0)
                    self.assertAlmostEqual(loudness_db(leveled(sample, dyn)), target, delta=0.5, msg=(name, m, dyn))

    def test_layers_capped_per_instrument(self):
        for name in ("flute", "oboe", "clarinet", "horn", "bassoon"):
            inst = instrument(name)
            with mock.patch.object(inst, "note", wraps=inst.note) as note:
                for dyn in ("p", "mp", "mf", "ff"):
                    voice_line(inst, voice([1, [2, 3], 4], beats=2, dynamic=dyn), C.lydian, 2, 60)
            used = {s.dynamic for s in [inst.note(*c.args, **c.kwargs) for c in note.call_args_list]}
            allowed = {"pp", "p", "mp"} | ({"mf"} if name != "horn" else set())
            self.assertTrue(used <= allowed, (name, used))
            if name != "horn" and "mf" in inst.dynamics:
                self.assertIn("mf", used)  # woodwinds with mf recordings do reach them

    def test_hairpin_shape(self):
        shaped = hairpin(array("h", [10000] * 1000))
        self.assertLess(shaped[0], 400)
        self.assertLess(shaped[-1], 400)
        self.assertEqual(max(shaped), shaped[400])  # peaks at 40% of the note
        self.assertGreater(shaped[400], 9900)

    def test_long_notes_swell(self):
        line = voice_line(instrument("flute"), voice([1], beats=2), C.maj7s11, 2, 60)  # one 2 s note
        n, peak = len(line), lambda a: max(map(abs, a))  # noqa: E731
        middle = peak(line[n // 3:n // 2])
        self.assertLess(peak(line[:n // 20]), middle / 3)  # starts from near silence
        self.assertLess(peak(line[-n // 20:]), middle / 3)  # and dies away

    def test_short_notes_fade_in_with_tempo(self):
        flute = instrument("flute")
        for tempo in (60, 120):
            line = voice_line(flute, voice([1], beats=1), C.maj7s11, 1, tempo)  # 1 s and 0.5 s: short
            k = round(ATTACK_BEATS * 60 / tempo * SAMPLE_RATE)
            self.assertEqual(line[0], 0)
            self.assertLess(max(map(abs, line[:k // 8])), max(map(abs, line[k:2 * k])) / 4)

    def test_volume_sine_in_mix_and_stems(self):
        Config(argv=[], tempo=60, output_dir=self.tmp, stems=True, reverb=0)
        silent = {n: voice([0], beats=4) for n in PIECE}

        def horn_peaks(label, horn):  # peak of each 1 s note in the horn stem of a 4 s piece
            mixed = read(render(label, C.maj7s11, **dict(silent, horn=horn))[0])[1]
            self.assertEqual(len(mixed), 2 * 4 * SAMPLE_RATE)
            stem = read(self.tmp / f"{label}_horn.wav")[1]
            return [max(map(abs, stem[i * SAMPLE_RATE:(i + 1) * SAMPLE_RATE])) for i in range(4)]

        steady = horn_peaks("steady", voice([1, 1, 1, 1], beats=4))
        swaying = horn_peaks("swaying", voice([1, 1, 1, 1], beats=4, lfo=1))  # loud, quiet at 2 s, loud
        from utils.voice import LFO_PEAK_DB
        self.assertAlmostEqual(swaying[0] / steady[0], 10 ** (LFO_PEAK_DB / 20), delta=0.1)  # near the peak
        self.assertLess(min(swaying[1:3]), 0.75 * steady[1])  # the notes either side of the trough dip

    def test_missing_voice(self):
        with self.assertRaises(ValueError):
            render("x", C.maj7s11, flute=PIECE["flute"])

    def test_piece_code_reproduces_wav(self):
        self.config.stems = False
        original = render("orig", C.maj7s11, **PIECE)[0].read_bytes()
        script = self.tmp / "orig.py"
        script.write_text(piece_code("orig", C.maj7s11, PIECE, seed=7))
        out = self.tmp / "rerun"
        subprocess.run([sys.executable, str(script), "--output-dir", str(out)], check=True, cwd=self.tmp)
        self.assertEqual((out / "orig.wav").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
