import unittest

import numpy as np

from clarity.fxlms import Canceller, FxLMS, accounted_delay, best_delay, cancellation_limit_hz, limit_line


def _rms(audio):
    return float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))


class FxLMSTests(unittest.TestCase):
    def test_silence_in_means_silence_out(self):
        filt = FxLMS(taps=24, delay_samples=32, sample_rate=48000, mu=0.4, leak=1.0)
        reference = np.zeros(4000)
        error = np.zeros(4000)
        out = np.array([filt.step(reference[i], error[i]) for i in range(len(reference))])
        self.assertEqual(float(np.max(np.abs(out))), 0.0)
        self.assertEqual(float(np.max(np.abs(filt.weights))), 0.0)
        canceller = Canceller(48000, 32, loop_delay=8)
        mixed = canceller.process(np.zeros(1000), np.zeros(1000))
        self.assertEqual(float(np.max(np.abs(mixed))), 0.0)

    def test_delayed_tone_is_attenuated(self):
        fs = 48000
        delay = 40
        self.assertGreater(cancellation_limit_hz(delay, fs), 80.0)
        seconds = 1.5
        count = int(seconds * fs)
        tone = 60.0
        t = np.arange(count) / fs
        reference = 0.25 * np.sin(2.0 * np.pi * tone * t)
        desired = np.zeros(count)
        desired[delay:] = reference[:-delay]
        anti = np.zeros(count)
        error = np.zeros(count)
        filt = FxLMS(taps=64, delay_samples=delay, sample_rate=fs, mu=0.02, leak=1.0, output_limit=1.0)
        for index in range(count):
            error[index] = desired[index] + (anti[index - delay] if index >= delay else 0.0)
            anti[index] = filt.step(reference[index], error[index])
        start = count // 2
        before = _rms(desired[start:])
        after = _rms(error[start:])
        self.assertGreater(before, 0.05)
        self.assertLess(after, before * 0.45)
        self.assertTrue(np.isfinite(anti).all())
        self.assertTrue(np.isfinite(filt.weights).all())

    def test_filter_does_not_explode(self):
        fs = 48000
        delay = 36
        count = fs
        rng = np.random.default_rng(3)
        reference = rng.normal(0.0, 0.4, count)
        desired = np.zeros(count)
        desired[delay:] = 1.7 * reference[:-delay]
        anti = np.zeros(count)
        error = np.zeros(count)
        filt = FxLMS(
            taps=32,
            delay_samples=delay,
            sample_rate=fs,
            mu=0.5,
            leak=0.999,
            output_limit=0.5,
            max_norm=4.0,
        )
        for index in range(count):
            error[index] = desired[index] + (anti[index - delay] if index >= delay else 0.0)
            anti[index] = filt.step(reference[index], error[index])
        self.assertTrue(np.isfinite(anti).all())
        self.assertTrue(np.isfinite(error).all())
        self.assertTrue(np.isfinite(filt.weights).all())
        self.assertLessEqual(float(np.max(np.abs(anti))), 0.5 + 1e-9)
        self.assertLessEqual(float(filt.weights @ filt.weights), 4.0 + 1e-6)

    def test_latency_accounting_matches_measured_delay(self):
        measured = 544
        self.assertEqual(accounted_delay(measured), measured)
        self.assertEqual(accounted_delay(measured + 0.4), measured)
        self.assertEqual(accounted_delay(-12), 0)
        filt = FxLMS(taps=16, delay_samples=accounted_delay(measured), sample_rate=48000)
        self.assertEqual(filt.delay_samples, measured)
        self.assertAlmostEqual(filt.limit_hz, 48000.0 / (4.0 * measured))
        self.assertAlmostEqual(cancellation_limit_hz(measured, 48000), filt.limit_hz)
        text = limit_line(measured, 48000, "structural")
        self.assertIn("22 Hz", text)
        self.assertIn("11.3 ms", text)
        self.assertIn("not AirPods Pro", text)
        self.assertNotIn("\n", text)
        rng = np.random.default_rng(5)
        source = rng.normal(0.0, 1.0, 4000)
        shifted = np.zeros_like(source)
        shifted[100:] = source[:-100]
        found, coherence = best_delay(source, shifted, 1000)
        self.assertEqual(found, 100)
        self.assertGreater(coherence, 0.99)


if __name__ == "__main__":
    unittest.main()
