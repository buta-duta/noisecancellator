import unittest

from clarity.report import AppIssue, explain


class ReportTests(unittest.TestCase):
    def test_each_known_issue_is_specific(self):
        cases = {
            "mic_missing": "No microphone was found.",
            "mic_headset_missing": "No headphone microphone was found.",
            "mic_laptop_missing": "No built-in laptop microphone was found.",
            "mic_busy": "The microphone is in use by another app.",
            "mic_denied": "Windows blocked access to the microphone.",
            "output_missing": "No headphones are plugged in.",
            "apo_not_loaded": "Noise cancellation is not loaded. Run setup.",
            "config_missing": "Equalizer APO is not installed. Run setup.",
            "config_locked": "Could not save the Equalizer APO config.",
            "hook_failed": "Num Lock + 8 could not be registered.",
            "device_lost": "The audio device disconnected.",
        }
        for code, text in cases.items():
            self.assertEqual(explain(AppIssue(code)), text)
            self.assertNotIn("Clarity stopped", text)

    def test_missing_config_and_hook_and_disconnect(self):
        self.assertEqual(explain(PermissionError("denied")), "Could not save the Equalizer APO config.")
        self.assertEqual(explain(FileNotFoundError("clarity.txt")), "Equalizer APO is not installed. Run setup.")
        self.assertEqual(
            explain(RuntimeError("keyboard hook failed (5)")),
            "Num Lock + 8 could not be registered.",
        )
        self.assertEqual(explain(OSError("microphone not found")), "No microphone was found.")
        self.assertEqual(explain(OSError("headphone microphone not found")), "No headphone microphone was found.")
        self.assertEqual(explain(OSError("device unplugged")), "The audio device disconnected.")

    def test_unknown_crash_names_the_exception(self):
        text = explain(ValueError("bad sample rate"))
        self.assertIn("ValueError", text)
        self.assertIn("bad sample rate", text)


if __name__ == "__main__":
    unittest.main()
