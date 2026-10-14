import ctypes
import unittest

from clarity.hook import MSG
from clarity.hotkey import VK_8, VK_NUMLOCK, VK_NUMPAD8, VK_UP, NumLockEightChord


class HotkeyTests(unittest.TestCase):
    def test_numlock_alone_does_not_toggle_or_swallow(self):
        chord = NumLockEightChord()
        down = chord.on_key(VK_NUMLOCK, 0, True)
        up = chord.on_key(VK_NUMLOCK, 0, False)
        self.assertFalse(down.toggle or down.swallow)
        self.assertFalse(up.toggle or up.swallow)

    def test_eight_alone_does_not_toggle(self):
        chord = NumLockEightChord()
        row = chord.on_key(VK_8, 0x09, True)
        pad = NumLockEightChord().on_key(VK_NUMPAD8, 0x48, True)
        self.assertFalse(row.toggle or row.swallow)
        self.assertFalse(pad.toggle or pad.swallow)

    def test_chord_toggles_once_and_swallows_repeat(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True)
        first = chord.on_key(VK_8, 0x09, True)
        repeat = chord.on_key(VK_8, 0x09, True)
        pad = chord.on_key(VK_NUMPAD8, 0x48, True)
        self.assertTrue(first.toggle and first.swallow)
        self.assertFalse(repeat.toggle)
        self.assertTrue(repeat.swallow)
        self.assertFalse(pad.toggle)
        self.assertTrue(pad.swallow)

    def test_numpad_eight_with_numlock_off_scan(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True)
        decision = chord.on_key(VK_UP, 0x48, True)
        self.assertTrue(decision.toggle and decision.swallow)

    def test_release_numlock_before_eight_still_swallows_keyup(self):
        chord = NumLockEightChord()
        chord.on_key(VK_NUMLOCK, 0, True)
        chord.on_key(VK_8, 0x09, True)
        chord.on_key(VK_NUMLOCK, 0, False)
        released = chord.on_key(VK_8, 0x09, False)
        self.assertTrue(released.swallow)
        self.assertFalse(released.toggle)

    def test_message_struct_matches_windows_x64(self):
        self.assertEqual(ctypes.sizeof(MSG), 48)


if __name__ == "__main__":
    unittest.main()
