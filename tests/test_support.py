import unittest

import numpy as np

from clarity.ring import RingBuffer
from clarity.routing import classify_name, mirror_scalar


class RingTests(unittest.TestCase):
    def test_roundtrip_and_overflow_keeps_newest(self):
        ring = RingBuffer(4, 2)
        ring.write(np.arange(6, dtype=np.float64).reshape(3, 2))
        first = ring.read(2)
        self.assertTrue(np.array_equal(first, np.array([[0, 1], [2, 3]], dtype=np.float64)))
        ring.write(np.arange(8, dtype=np.float64).reshape(4, 2) + 10)
        out = ring.read(4)
        self.assertTrue(np.array_equal(out, np.arange(8, dtype=np.float64).reshape(4, 2) + 10))


class RoutingMathTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(classify_name("Наушники (Realtek(R) Audio)"), "phones")
        self.assertEqual(classify_name("Динамики (Realtek(R) Audio)"), "speakers")
        self.assertEqual(classify_name("AirPods Hands-Free"), "bad")

    def test_volume_mirror(self):
        self.assertAlmostEqual(mirror_scalar(0.5, 0.8, 0.4), 0.25)
        self.assertAlmostEqual(mirror_scalar(0.2, 0.0, 0.7), 0.7)


if __name__ == "__main__":
    unittest.main()
