import os
import tempfile
import unittest
from pathlib import Path

from clarity.dsp import PRESENCE_DB, PREAMP_DB, clarity_config
from clarity.engine import Engine


class RouteTests(unittest.TestCase):
    def test_toggle_writes_eq_without_com(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("engine.py", "tray.py", "hook.py"):
            text = (root / "clarity" / name).read_text(encoding="utf-8")
            self.assertNotIn("pycaw", text)
            self.assertNotIn("restore_route", text)
            self.assertNotIn("pick_pair", text)
        tray = (root / "clarity" / "tray.py").read_text(encoding="utf-8")
        self.assertNotIn("SetDefaultDevice", tray)
        self.assertIn("hook.start", tray)
        on = clarity_config(True)
        self.assertIn("Preamp: 0.0 dB", on)
        self.assertIn("Gain 3.5 dB", on)
        self.assertEqual(PREAMP_DB, 0.0)
        self.assertEqual(PRESENCE_DB, 3.5)
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "clarity.txt")
        sibling = os.path.join(folder, "config.txt")
        with open(sibling, "w", encoding="utf-8") as handle:
            handle.write("Include: clarity.txt\r\n")
        os.utime(sibling, (1, 1))
        previous = os.environ.get("CLARITY_EQ_FILE")
        os.environ["CLARITY_EQ_FILE"] = target
        engine = Engine()
        try:
            ok, message = engine.start()
            self.assertTrue(ok, message)
            self.assertEqual(engine.latency_ms, 0.0)
            text = Path(target).read_text(encoding="utf-8")
            self.assertIn("Filter:", text)
            self.assertIn("Preamp: 0.0 dB", text)
            self.assertIn("Gain 3.5 dB", text)
            self.assertGreater(os.path.getmtime(sibling), 1)
            stopped, stop_message = engine.stop()
            self.assertTrue(stopped, stop_message)
            off = Path(target).read_text(encoding="utf-8").casefold()
            self.assertNotIn("filter:", off)
        finally:
            if previous is None:
                os.environ.pop("CLARITY_EQ_FILE", None)
            else:
                os.environ["CLARITY_EQ_FILE"] = previous


if __name__ == "__main__":
    unittest.main()
