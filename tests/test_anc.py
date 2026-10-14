import unittest

import numpy as np

from clarity.anc import cabin_noise, cancel, quality


class AncTests(unittest.TestCase):
    def test_known_noise_is_cut_on_the_way_to_the_ear(self):
        noise = cabin_noise(FS := 48000, fs=48000)
        sent, _residual = cancel(noise, delay_samples=48)
        # Skip the adaption start and the lookahead edge.
        score = quality(noise[4000:-4000], sent[4000:-4000], 48000)
        self.assertGreaterEqual(score["low_db"], 12.0, score)
        self.assertGreaterEqual(score["mid_db"], 6.0, score)
        self.assertGreaterEqual(score["high_db"], -3.0, score)
        self.assertTrue(score["passed"], score)

    def test_silence_stays_silent(self):
        sent, residual = cancel(np.zeros(4000), delay_samples=16)
        self.assertLess(float(np.max(np.abs(sent))), 1e-6)
        self.assertLess(float(np.max(np.abs(residual))), 1e-6)

    def test_output_stays_in_range(self):
        sent, _residual = cancel(cabin_noise(12000), delay_samples=32)
        self.assertLessEqual(float(np.max(np.abs(sent))), 1.0)
        self.assertTrue(np.isfinite(sent).all())


if __name__ == "__main__":
    unittest.main()
