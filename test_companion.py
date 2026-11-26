import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

import companion


class RoutingTest(unittest.TestCase):
    def test_asio_channel_to_separate_stereo_endpoint_and_midi(self):
        stop = threading.Event()
        sender = Mock()
        t = np.arange(1920) / 48000
        wave = (.25 * np.sin(2 * np.pi * 440 * t)).astype("float32")

        class Stream:
            active = True

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def capture(**kw):
            self.assertEqual(kw["channels"], 1)
            self.assertEqual(kw["extra_settings"], [2])
            kw["callback"](wave[:, None], len(wave), None, None)
            return Stream()

        def render(**kw):
            output = np.empty((len(wave), 2), dtype="float32")
            kw["callback"](output, len(wave), None, None)
            np.testing.assert_array_equal(output, np.column_stack((wave, wave)))
            kw["callback"](output, len(wave), None, None)
            self.assertFalse(output.any())
            return Stream()

        def report(text):
            if "dBFS" in text:
                self.assertIn("A5", text)
                stop.set()

        devices = [dict(hostapi=0, default_samplerate=48000),
                   dict(hostapi=1, default_samplerate=48000, max_output_channels=2)]
        with patch.multiple(companion.sd, query_devices=devices.__getitem__,
                            query_hostapis=lambda i: {"name": ["ASIO", "Windows WASAPI"][i]},
                            AsioSettings=list, check_input_settings=Mock(), check_output_settings=Mock(),
                            InputStream=capture, OutputStream=render), patch.object(
                                companion.midi, "Output", return_value=sender):
            companion.route(0, 3, 1, 4, stop, report)
        status, low, high = sender.write_short.call_args_list[0].args
        self.assertEqual(status, 0xef)
        self.assertAlmostEqual(low + 128 * high, 8101, delta=3)
        sender.write_short.assert_called_with(0xef, 0, 0)
        sender.close.assert_called_once()
