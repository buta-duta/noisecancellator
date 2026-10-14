VK_NUMLOCK = 0x90
VK_8 = 0x38
VK_NUMPAD8 = 0x68
VK_UP = 0x26
SCAN_NUM8 = 0x48
NUMLOCK_DOWN_BIT = 0x8000
NUMLOCK_WINDOW_S = 0.4


def numlock_is_physically_down(async_state):
    return bool(int(async_state) & NUMLOCK_DOWN_BIT)


class ChordDecision:
    def __init__(self, swallow, toggle):
        self.swallow = swallow
        self.toggle = toggle


class NumLockEightChord:
    def __init__(self):
        self.numlock_down = False
        self.numlock_up_at = None
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

    def _recent(self, now):
        if now is None or self.numlock_up_at is None:
            return False
        return (now - self.numlock_up_at) <= NUMLOCK_WINDOW_S

    def _armed(self, numlock_held, now):
        return self.numlock_down or bool(numlock_held) or self._recent(now)

    def on_key(self, vk, scan, is_down, numlock_held=None, now=None):
        vk = int(vk)
        if vk == VK_NUMLOCK:
            self.numlock_down = bool(is_down)
            if is_down:
                self.numlock_up_at = None
            else:
                self.numlock_up_at = now
            return ChordDecision(False, False)
        kid = self._eight_id(vk, scan)
        if kid is None:
            return ChordDecision(False, False)
        armed = self._armed(numlock_held, now)
        if is_down:
            repeat = kid in self.held
            self.held.add(kid)
            if repeat:
                return ChordDecision(armed or self.latched, False)
            if armed and not self.latched:
                self.latched = True
                return ChordDecision(True, True)
            if armed or self.latched:
                return ChordDecision(True, False)
            return ChordDecision(False, False)
        self.held.discard(kid)
        swallow_up = self.latched
        if not self.held:
            self.latched = False
        return ChordDecision(swallow_up, False)
