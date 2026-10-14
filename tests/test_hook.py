import unittest

from clarity.hook import KeyboardHook


class HookTests(unittest.TestCase):
    def test_hook_installs_and_stops(self):
        hook = KeyboardHook()
        hook.start(lambda: None)
        hook.stop()


if __name__ == "__main__":
    unittest.main()
