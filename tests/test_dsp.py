import unittest

import numpy as np

from clarity.dsp import ClarityProcessor, clarity_config


def _rms(audio):
    return float(np.sqrt(np.mean(audio ** 2)))


class DspTests(unittest.TestCase):
    def test_bypass_is_identity(self):
        processor = ClarityProcessor(48000)
        audio = np.linspace(-0.4, 0.4, 480, dtype=np.float64).reshape(-1, 1)
        self.assertIs(processor.process(audio, enabled=False), audio)

    def test_no_added_buffer(self):
        processor = ClarityProcessor(48000)
        self.assertEqual(processor.latency_samples, 0)
        audio = np.zeros((128, 2))
        out = processor.process(audio, enabled=True)
        self.assertEqual(len(out), len(audio))

    def test_sines_do_not_clip(self):
        fs = 48000
        processor = ClarityProcessor(fs)
        t = np.arange(fs) / fs
        for freq in (100.0, 1000.0, 3000.0, 12000.0):
            wave = np.sin(2.0 * np.pi * freq * t)
            audio = np.stack([wave, wave], axis=1)
            out = processor.process(audio, enabled=True)
            steady = out[int(0.2 * fs) :]
            self.assertLessEqual(float(np.max(np.abs(steady))), 1.0, freq)
            self.assertTrue(np.isfinite(steady).all())

    def test_presence_above_bass(self):
        fs = 48000
        low = self._steady_db(fs, 100.0)
        presence = self._steady_db(fs, 3000.0)
        self.assertGreater(presence, low + 2.0)

    def test_stereo_image_is_not_crossed(self):
        fs = 48000
        t = np.arange(fs) / fs
        audio = np.zeros((fs, 2))
        audio[:, 0] = 0.2 * np.sin(2.0 * np.pi * 1000.0 * t)
        out = ClarityProcessor(fs).process(audio, enabled=True)
        self.assertLess(float(np.max(np.abs(out[:, 1]))), 1e-5)
        self.assertGreater(float(np.max(np.abs(out[:, 0]))), 0.01)

    def test_config_is_iir_without_delay_lines(self):
        off = clarity_config(False).casefold()
        on = clarity_config(True).casefold()
        self.assertNotIn("filter:", off)
        for banned in ("graphiceq", "convolution", "delay:"):
            self.assertNotIn(banned, on)
        self.assertIn("preamp:", on)
        self.assertIn("filter:", on)

    def _steady_db(self, fs, freq):
        t = np.arange(fs) / fs
        wave = 0.1 * np.sin(2.0 * np.pi * freq * t)
        audio = np.stack([wave, wave], axis=1)
        out = ClarityProcessor(fs).process(audio, enabled=True)
        start = int(0.25 * fs)
        return 20.0 * np.log10((_rms(out[start:]) + 1e-12) / (_rms(audio[start:]) + 1e-12))


if __name__ == "__main__":
    unittest.main()
