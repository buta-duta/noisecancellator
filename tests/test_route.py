import os
import tempfile
import unittest
from pathlib import Path

from clarity.devices import default_render
from clarity.engine import Engine


class RouteTests(unittest.TestCase):
    def test_toggle_does_not_move_default_or_open_loopback(self):
        engine_source = Path(__file__).resolve().parents[1].joinpath("clarity", "engine.py").read_text(encoding="utf-8")
        tray_source = Path(__file__).resolve().parents[1].joinpath("clarity", "tray.py").read_text(encoding="utf-8")
        self.assertNotIn("DeviceLoopback", engine_source)
        self.assertNotIn("SetDefaultDevice", engine_source)
        self.assertNotIn("SetDefaultDevice", tray_source)
        before = default_render().id
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "clarity.txt")
        previous = os.environ.get("CLARITY_EQ_FILE")
        os.environ["CLARITY_EQ_FILE"] = target
        engine = Engine()
        try:
            ok, message = engine.start()
            self.assertTrue(ok, message)
            self.assertEqual(engine.latency_ms, 0.0)
            self.assertEqual(default_render().id, before)
            self.assertNotIn("loop", engine.__dict__)
            text = Path(target).read_text(encoding="utf-8").casefold()
            self.assertIn("filter:", text)
            stopped, stop_message = engine.stop()
            self.assertTrue(stopped, stop_message)
            self.assertEqual(default_render().id, before)
            off = Path(target).read_text(encoding="utf-8").casefold()
            self.assertNotIn("filter:", off)
        finally:
            if previous is None:
                os.environ.pop("CLARITY_EQ_FILE", None)
            else:
                os.environ["CLARITY_EQ_FILE"] = previous


if __name__ == "__main__":
    unittest.main()
