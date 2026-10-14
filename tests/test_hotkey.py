import unittest

from clarity.hotkey import (
    VK_8,
    VK_NUMLOCK,
    VK_NUMPAD8,
    VK_UP,
    NumLockEightChord,
    numlock_is_physically_down,
)


class HotkeyTests(unittest.TestCase):
    def test_numlock_alone_does_not_toggle_or_swallow(self):
        chord = NumLockEightChord()
        down = chord.on_key(VK_NUMLOCK, 0, True, now=0.0)
        up = chord.on_key(VK_NUMLOCK, 0, False, now=0.1)
        self.assertFalse(down.toggle or down.swallow)
        self.assertFalse(up.toggle or up.swallow)

    def test_eight_alone_does_not_toggle(self):
        chord = NumLockEightChord()
        row = chord.on_key(VK_8, 0x09, True, now=1.0)
        pad = NumLockEightChord().on_key(VK_NUMPAD8, 0x48, True, now=1.0)
        self.assertFalse(row.toggle or row.swallow)
        self.assertFalse(pad.toggle or pad.swallow)

    def test_chord_toggles_once_and_swallows_repeat(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True, now=0.0)
        first = chord.on_key(VK_8, 0x09, True, now=0.1)
        repeat = chord.on_key(VK_8, 0x09, True, now=0.2)
        pad = chord.on_key(VK_NUMPAD8, 0x48, True, now=0.2)
        self.assertTrue(first.toggle and first.swallow)
        self.assertFalse(repeat.toggle)
        self.assertTrue(repeat.swallow)
        self.assertFalse(pad.toggle)
        self.assertTrue(pad.swallow)

    def test_numpad_eight_with_numlock_off_scan(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True, now=0.0)
        decision = chord.on_key(VK_UP, 0x48, True, now=0.1)
        self.assertTrue(decision.toggle and decision.swallow)

    def test_eight_within_window_after_numlock_release(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True, now=0.0)
        chord.on_key(VK_NUMLOCK, 0, False, now=0.1)
        decision = chord.on_key(VK_8, 0x09, True, now=0.4)
        self.assertTrue(decision.toggle and decision.swallow)

    def test_eight_after_window_does_not_toggle(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True, now=0.0)
        chord.on_key(VK_NUMLOCK, 0, False, now=0.1)
        decision = chord.on_key(VK_8, 0x09, True, now=0.6)
        self.assertFalse(decision.toggle or decision.swallow)

    def test_release_numlock_before_eight_still_swallows_keyup(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True, now=0.0)
        chord.on_key(VK_8, 0x09, True, now=0.05)
        chord.on_key(VK_NUMLOCK, 0, False, now=0.06)
        released = chord.on_key(VK_8, 0x09, False, now=0.07)
        self.assertTrue(released.swallow)
        self.assertFalse(released.toggle)

    def test_physical_down_bit_is_not_the_led_bit(self):
        self.assertTrue(numlock_is_physically_down(0x8000))
        self.assertTrue(numlock_is_physically_down(0x8001))
        self.assertFalse(numlock_is_physically_down(0x0001))
        led_only = NumLockEightChord()
        self.assertFalse(led_only.on_key(VK_8, 0x09, True, numlock_held=False, now=1.0).toggle)
        held = NumLockEightChord()
        self.assertTrue(held.on_key(VK_NUMPAD8, 0x48, True, numlock_held=True, now=1.0).toggle)


if __name__ == "__main__":
    unittest.main()
