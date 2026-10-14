VK_NUMLOCK = 0x90
VK_8 = 0x38
VK_NUMPAD8 = 0x68
VK_UP = 0x26
SCAN_NUM8 = 0x48


class ChordDecision:
    def __init__(self, swallow, toggle):
        self.swallow = swallow
        self.toggle = toggle


class NumLockEightChord:
    # Physical Num Lock is tracked separately from the LED. The Num Lock key
    # itself is never swallowed, so Windows still toggles the lock state.
    def __init__(self):
        self.numlock_down = False
        self.held = set()
        self.latched = False

    def _eight_id(self, vk, scan):
        scan = int(scan) & 0xFF
        if vk == VK_8:
            return "row8"
        if vk == VK_NUMPAD8:
            return "pad8"
        if vk == VK_UP and scan == SCAN_NUM8:
            return "pad8"
        return None

    def on_key(self, vk, scan, is_down):
        vk = int(vk)
        if vk == VK_NUMLOCK:
            self.numlock_down = bool(is_down)
            return ChordDecision(False, False)
        kid = self._eight_id(vk, scan)
        if kid is None:
            return ChordDecision(False, False)
        if is_down:
            repeat = kid in self.held
            self.held.add(kid)
            if repeat:
                return ChordDecision(self.numlock_down or self.latched, False)
            if self.numlock_down and not self.latched:
                self.latched = True
                return ChordDecision(True, True)
            if self.numlock_down or self.latched:
                return ChordDecision(True, False)
            return ChordDecision(False, False)
        self.held.discard(kid)
        swallow_up = self.latched
        if not self.held:
            self.latched = False
        return ChordDecision(swallow_up, False)
