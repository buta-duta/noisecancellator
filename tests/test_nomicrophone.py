import unittest
from pathlib import Path


class NoMicTests(unittest.TestCase):
    def test_sources_do_not_touch_input_devices(self):
        root = Path(__file__).resolve().parents[1]
        files = [root / "main.py", *root.joinpath("clarity").glob("*.py")]
        banned = (
            "wavein",
            "pyaudio",
            "ecapture",
            "getmicrophone",
            "speech_recognition",
        )
        for path in files:
            text = path.read_text(encoding="utf-8").casefold()
            for word in banned:
                self.assertNotIn(word, text, f"{path.name} contains {word}")


if __name__ == "__main__":
    unittest.main()
