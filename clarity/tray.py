import ctypes
import threading
from ctypes import wintypes

import pystray
from PIL import Image, ImageDraw

from clarity.engine import Engine
from clarity.hook import KeyboardHook
from clarity.notice import notice_label, show_notice
from clarity.persist import load_enabled, log, save_enabled
from clarity.routing import restore_route

STATUS = "Outside noise is reduced by the silicone seal; this mode keeps playback clear."
HOTKEY = "Num Lock + 8"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
ERROR_ALREADY_EXISTS = 183


def _icon(active):
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = (36, 164, 108, 255) if active else (118, 122, 128, 255)
    draw.ellipse((4, 4, 60, 60), fill=color)
    draw.ellipse((24, 24, 40, 40), fill=(255, 255, 255, 235))
    return image


class App:
    def __init__(self):
        self.engine = Engine()
        self.engine.on_failure = self._failed
        self.enabled = False
        self.icon = None
        self._state_lock = threading.Lock()
        self._wake = threading.Event()
        self._pending = 0
        self._quit = False
        self._worker = threading.Thread(target=self._loop, name="clarity-toggle", daemon=True)
        self._worker.start()

    def request_toggle(self):
        with self._state_lock:
            self._pending += 1
        self._wake.set()

    def set_enabled(self, enabled, notify=True):
        with self._state_lock:
            self._apply(bool(enabled), notify)

    def _loop(self):
        while not self._quit:
            self._wake.wait(0.25)
            self._wake.clear()
            while not self._quit:
                with self._state_lock:
                    if self._pending <= 0:
                        break
                    self._pending -= 1
                    target = not self.enabled
                self.set_enabled(target, True)

    def _apply(self, enabled, notify):
        if enabled == self.enabled and (not enabled or self.engine.active):
            self._refresh()
            return
        if enabled:
            ok, message = self.engine.start()
            if not ok:
                self.enabled = False
                save_enabled(False)
                self._refresh()
                self._notify(message or "Playback processing did not start")
                return
        else:
            self.engine.stop()
        self.enabled = enabled
        save_enabled(enabled)
        self._refresh()
        if notify:
            self._notify("On" if enabled else "Off")
            show_notice(notice_label(enabled))

    def _failed(self, message):
        self.enabled = False
        save_enabled(False)
        self._refresh()
        self._notify(message)

    def _refresh(self):
        icon = self.icon
        if icon is None:
            return
        icon.icon = _icon(self.enabled)
        icon.title = f"{'Clarity on — system playback' if self.enabled else 'Clarity off'} — {HOTKEY}"
        try:
            icon.update_menu()
        except Exception:
            pass

    def _notify(self, message):
        icon = self.icon
        if icon is None or not message:
            return
        try:
            icon.notify(str(message), "Clarity")
        except Exception as exc:
            log(exc)

    def menu(self):
        return pystray.Menu(
            pystray.MenuItem("Toggle", lambda icon, item: self.request_toggle(), default=True, visible=False),
            pystray.MenuItem("On", lambda icon, item: self.set_enabled(True), checked=lambda item: self.enabled),
            pystray.MenuItem("Off", lambda icon, item: self.set_enabled(False), checked=lambda item: not self.enabled),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(HOTKEY, None, enabled=False),
            pystray.MenuItem(STATUS, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self.quit()),
        )

    def quit(self):
        self._quit = True
        self._wake.set()
        self.engine.stop()
        if self.icon is not None:
            self.icon.stop()


def _single_instance():
    kernel32.CreateMutexW(None, False, "Local\\ClarityModeSingleton")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def run_check():
    from clarity.dsp import ClarityProcessor
    from clarity.routing import pick_pair

    listen, capture = pick_pair()
    processor = ClarityProcessor(48000)
    print(f"listen={listen.FriendlyName}")
    print(f"capture={capture.FriendlyName}")
    print(f"dsp_latency_ms={processor.latency_samples / 48.0:.2f}")
    print("system_playback=speakers-loopback-to-headphones")
    print("apo=not-installed")
    print(STATUS)
    return 0


def run():
    if not _single_instance():
        print("Clarity is already running")
        return 0
    restore_route()
    app = App()
    hook = KeyboardHook()
    icon = pystray.Icon("Clarity", _icon(False), f"Clarity off — {HOTKEY}", app.menu())
    app.icon = icon

    def setup(icon):
        icon.visible = True
        try:
            hook.start(app.request_toggle)
        except Exception as exc:
            log(exc)
            icon.notify(str(exc), "Clarity")
        if load_enabled():
            app.set_enabled(True, notify=False)

    try:
        icon.run(setup)
    finally:
        app._quit = True
        app._wake.set()
        hook.stop()
        app.engine.stop()
        restore_route()
    return 0
