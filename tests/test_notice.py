import unittest

from clarity.notice import DISMISS_MS, NOTICE_OFF, NOTICE_ON, notice_label


class NoticeTests(unittest.TestCase):
    def test_label(self):
        self.assertEqual(notice_label(True), "Clarity on")
        self.assertEqual(notice_label(False), "Clarity off")
        self.assertEqual(NOTICE_ON, "Clarity on")
        self.assertEqual(NOTICE_OFF, "Clarity off")

    def test_dismiss_window(self):
        self.assertGreaterEqual(DISMISS_MS, 1200)
        self.assertLessEqual(DISMISS_MS, 1500)


if __name__ == "__main__":
    unittest.main()
