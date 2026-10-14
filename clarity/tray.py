import ctypes
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

import psutil
import pystray
from PIL import Image, ImageDraw

from clarity.engine import Engine
from clarity.eqfile import eq_path
from clarity.hook import KeyboardHook
from clarity.notice import notice_label, show_notice
from clarity.persist import load_enabled, log, save_enabled
from clarity.report import explain, install_crash_report, set_presenter

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


def _repo_main():
    return str(Path(__file__).resolve().parents[1] / "main.py")


def replace_existing():
    me = os.getpid()
    parent = os.getppid()
    root = str(Path(__file__).resolve().parents[1]).casefold()
    victims = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        pid = proc.info["pid"]
        if pid in (me, parent):
            continue
        cmd = proc.info["cmdline"] or []
        text = " ".join(cmd)
        if "main.py" not in text.casefold():
            continue
        cwd = ""
        try:
            cwd = proc.cwd()
        except (psutil.Error, OSError):
            cwd = ""
        if root in text.casefold() or root in cwd.casefold():
            victims.append(proc)
    for proc in victims:
        try:
            proc.kill()
        except psutil.Error as exc:
            log(exc)
    if victims:
        psutil.wait_procs(victims, timeout=3)
        time.sleep(0.2)


class App:
    def __init__(self):
        self.engine = Engine()
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
                self._report(message or "Could not save the Equalizer APO config.")
                return
        else:
            ok, message = self.engine.stop()
            if not ok:
                self._report(message or "Could not save the Equalizer APO config.")
                return
        self.enabled = enabled
        save_enabled(enabled)
        self._refresh()
        if notify:
            show_notice(notice_label(enabled))

    def _report(self, message):
        text = str(message or "Clarity stopped.")
        show_notice(text, hold_ms=4500)
        self._notify(text)

    def _refresh(self):
        icon = self.icon
        if icon is None:
            return
        icon.icon = _icon(self.enabled)
        icon.title = f"{'Clarity on' if self.enabled else 'Clarity off'} — {HOTKEY}"
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
    path = eq_path()
    text = ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    dll = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "EqualizerAPO", "EqualizerAPO.dll")
    print(f"eq={path}")
    print(f"filters={'yes' if 'filter:' in text.casefold() else 'no'}")
    print(f"apo={'installed' if os.path.isfile(dll) else 'missing'}")
    print(STATUS)
    return 0


def run():
    install_crash_report()
    set_presenter(lambda text, hold_ms=4500: None)
    replace_existing()
    if not _single_instance():
        print("Clarity is already running")
        return 0
    app = App()
    hook = KeyboardHook()
    icon = pystray.Icon("Clarity", _icon(False), f"Clarity off — {HOTKEY}", app.menu())
    app.icon = icon

    def setup(icon):
        icon.visible = True

        def _show(text, hold_ms=4500):
            show_notice(text, hold_ms)
            try:
                icon.notify(str(text), "Clarity")
            except Exception as exc:
                log(exc)

        set_presenter(_show)
        try:
            hook.start(app.request_toggle)
        except Exception as exc:
            log(exc)
            _show(explain(exc))
            icon.stop()
            return
        if load_enabled():
            app.set_enabled(True, notify=False)

    try:
        icon.run(setup)
    finally:
        app._quit = True
        app._wake.set()
        hook.stop()
        app.engine.stop()
    return 0
