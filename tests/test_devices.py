import unittest

from clarity.devices import choice_labels, classify_name, form_factor, input_kind


class _Fake:
    def __init__(self, value):
        self.properties = {"{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E} 0": value}


class DeviceLabelTests(unittest.TestCase):
    def test_hands_free_is_not_on_the_music_list(self):
        self.assertEqual(classify_name("Headset Hands-Free"), "bad")
        self.assertEqual(input_kind("Headset Hands-Free AG Audio"), "bad")
        self.assertEqual(form_factor(_Fake(6)), 6)
        self.assertIsNone(form_factor(_Fake("nope")))

    def test_array_is_the_weaker_reference_and_jack_mic_is_primary(self):
        labels = choice_labels(
            [
                "Набор микрофонов (Realtek(R) Audio)",
                "Микрофон (Realtek(R) Audio)",
            ]
        )
        self.assertEqual(labels[0][0], "laptop")
        self.assertIn("weaker reference", labels[0][1])
        self.assertIn("not an AirPods equivalent", labels[0][1])
        self.assertEqual(labels[1][0], "headphone")
        self.assertIn("primary reference near the ear", labels[1][1])

    def test_a_lone_built_in_mic_is_not_called_a_headphone_mic(self):
        self.assertEqual(choice_labels(["Microphone"])[0][0], "laptop")
        self.assertEqual(choice_labels(["Headset Microphone"])[0][0], "headphone")


if __name__ == "__main__":
    unittest.main()