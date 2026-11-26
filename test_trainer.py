import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import mido
import numpy as np

from trainer import Score, Step, pitch, run, song, warmup


class PracticeTests(unittest.TestCase):
    def test_pitch(self):
        for rate in [44100, 48000, 96000]:
            for hz in [82.41, 146.83, 440, 880]:
                t = np.arange(round(rate * .04)) / rate
                wave = .28*np.sin(2*np.pi*t*hz) + .42*np.sin(4*np.pi*t*hz)
                self.assertAlmostEqual(pitch(wave, rate), 81 + 12*np.log2(hz/440), delta=.17)
        self.assertIsNone(pitch(np.zeros(1920), 48000))
        self.assertIsNone(pitch(np.random.default_rng(7).normal(0, .1, 1920), 48000))

    def test_score(self):
        score = Score([Step(1, 2, (60,)), Step(3, 4, (62,))])
        score.observe(0, 1.5, 60)
        score.observe(1.5, 3.5, 62)
        score.observe(3.5, 4, None)
        self.assertEqual((score.duration, score.voiced, score.hit, score.error), (2, 1.5, 1, 100))

    def test_tempo_map_and_rests(self):
        f = mido.MidiFile(ticks_per_beat=480)
        tempo = f.add_track()
        tempo.append(mido.MetaMessage("set_tempo", tempo=1000000, time=480))
        melody = f.add_track()
        melody.append(mido.Message("note_on", note=60, time=240))
        melody.append(mido.Message("note_on", note=60, velocity=0, time=720))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "song.mid"
            f.save(path)
            self.assertEqual(song(path, 1, 1), [Step(.25, 1.5, (60,))])

    def test_harmonic_target(self):
        step = warmup("harmonic", 55, 60)[0]
        self.assertEqual((step.notes, step.target), ((55, 62), 62))

    def test_session_on_simulated_microphone(self):
        wave = (.15 * np.sin(2*np.pi*220*np.arange(1920)/48000)).reshape(-1, 1)

        class Stream:
            def __init__(self, callback, **kwargs):
                self.callback = callback
                self.count = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            @property
            def time(self):
                self.count += 1
                stamp = 10 + .04 * self.count
                self.callback(wave, len(wave), SimpleNamespace(inputBufferAdcTime=stamp-.04),
                              SimpleNamespace(input_overflow=False))
                return stamp

        out = Mock()
        with patch("trainer.sd.InputStream", Stream), redirect_stdout(StringIO()), \
             patch("trainer.sd.query_devices", return_value={"default_samplerate": 48000}):
            run(SimpleNamespace(mic=None, delay_ms=0), [Step(0, .4, (69,))], out)
        out.note_on.assert_called_once_with(69, 80)
        out.note_off.assert_called_once_with(69)
        out.write_short.assert_called_with(0xbf, 21, 101)


if __name__ == "__main__":
    unittest.main()
