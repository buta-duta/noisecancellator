import ctypes
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

import psutil
import pystray
from PIL import Image, ImageDraw

from clarity.apo import apo_loaded
from clarity.devices import listening_device
from clarity.engine import Engine
from clarity.eqfile import eq_path
from clarity.fxlms import limit_line
from clarity.hook import KeyboardHook
from clarity.notice import notice_label, show_notice
from clarity.persist import load_state, log, save_state
from clarity.report import AppIssue, explain, install_crash_report, set_presenter
from clarity.session import Session
from clarity.setupui import open_setup

HONEST = "This is not AirPods Pro: a PC mic through Windows only softens steady low rumble."
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
        self.session = Session()
        state = load_state()
        saved_mode = state.get("mode")
        if saved_mode not in ("off", "eq", "anc"):
            saved_mode = "eq" if state.get("enabled") else "off"
        self.mode = "off"
        self.armed = state.get("armed") if state.get("armed") in ("eq", "anc") else ("anc" if saved_mode == "anc" else "eq")
        self._saved_mode = saved_mode
        self.icon = None
        self._state_lock = threading.Lock()
        self._wake = threading.Event()
        self._pending = 0
        self._quit = False
        self._apo_warned = False
        self._worker = threading.Thread(target=self._loop, name="clarity-toggle", daemon=True)
        self._worker.start()

    @property
    def enabled(self):
        return self.mode != "off"

    def request_toggle(self):
        with self._state_lock:
            self._pending += 1
        self._wake.set()

    def apply_saved(self, notify=False):
        state = load_state()
        mode = state.get("mode")
        if mode not in ("off", "eq", "anc"):
            mode = "eq" if state.get("enabled") else "off"
        if state.get("armed") in ("eq", "anc"):
            self.armed = state["armed"]
        self._saved_mode = mode
        self.set_mode(mode, notify=notify)

    def set_mode(self, mode, notify=True):
        if mode not in ("off", "eq", "anc"):
            mode = "off"
        self._switch(mode, notify)

    def _loop(self):
        while not self._quit:
            self._wake.wait(0.25)
            self._wake.clear()
            while not self._quit:
                with self._state_lock:
                    if self._pending <= 0:
                        break
                    self._pending -= 1
                    target = "off" if self.mode != "off" else self.armed
                self.set_mode(target, True)

    def _ids(self):
        state = load_state()
        output_id = state.get("output_id") or ""
        input_id = state.get("input_id") or ""
        if not output_id:
            try:
                device = listening_device()
            except OSError:
                device = None
            output_id = device.id if device is not None else ""
        return output_id, input_id, state

    def _persist(self):
        save_state({"mode": self.mode, "enabled": self.mode != "off", "armed": self.armed})

    def _fail(self, message):
        self.session.stop()
        self.engine.stop()
        self.mode = "off"
        self._persist()
        self._refresh()
        self._report(message)

    def _warn_apo(self):
        if self._apo_warned or apo_loaded():
            return False
        self._apo_warned = True
        self._report(explain(AppIssue("apo_not_loaded")))
        return True

    def _switch(self, mode, notify):
        same = mode == self.mode and (
            mode == "off" or (mode == "eq" and self.engine.active) or (mode == "anc" and self.session.running)
        )
        if same:
            self._refresh()
            return
        self.session.stop()
        if mode != "eq" and self.engine.active:
            stopped, message = self.engine.stop()
            if not stopped:
                self._report(message or "Could not save the Equalizer APO config.")
        if mode == "eq":
            if not apo_loaded():
                self._fail(explain(AppIssue("apo_not_loaded")))
                self._apo_warned = True
                return
            ok, message = self.engine.start()
            if not ok:
                self._fail(message or "Could not save the Equalizer APO config.")
                return
        elif mode == "anc":
            self.engine.stop()
            output_id, input_id, state = self._ids()
            if not output_id:
                self._fail(explain(AppIssue("output_missing")))
                return
            if not input_id:
                self._fail(explain(AppIssue("mic_choice")))
                return
            try:
                self.session.start(output_id, input_id, state)
            except Exception as exc:
                self._fail(explain(exc))
                return
            save_state(
                {
                    "output_id": output_id,
                    "input_id": input_id,
                    "delay_samples": self.session.delay_samples,
                    "loop_delay": self.session.loop_delay,
                    "sample_rate": self.session.sample_rate,
                    "delay_kind": self.session.delay_kind,
                }
            )
            self._warn_apo()
        self.mode = mode
        self._saved_mode = mode
        if mode in ("eq", "anc"):
            self.armed = mode
        self._persist()
        self._refresh()
        if notify:
            label = notice_label(self.enabled)
            show_notice(label)
            self._notify(label)

    def _report(self, message):
        text = str(message or "Clarity stopped.")
        show_notice(text, hold_ms=4500)
        self._notify(text)

    def _refresh(self):
        icon = self.icon
        if icon is None:
            return
        icon.icon = _icon(self.enabled)
        icon.title = f"{notice_label(self.enabled)} — {HOTKEY}"
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

    def _status_line(self):
        state = load_state()
        delay = state.get("delay_samples")
        rate = state.get("sample_rate")
        if delay and rate:
            return limit_line(delay, rate, state.get("delay_kind") or "structural")
        return HONEST

    def menu(self):
        return pystray.Menu(
            pystray.MenuItem("Toggle", lambda icon, item: self.request_toggle(), default=True, visible=False),
            pystray.MenuItem("Off", lambda icon, item: self.set_mode("off"), checked=lambda item: self.mode == "off", radio=True),
            pystray.MenuItem("Clarity EQ", lambda icon, item: self.set_mode("eq"), checked=lambda item: self.mode == "eq", radio=True),
            pystray.MenuItem(
                "Mic cancellation",
                lambda icon, item: self.set_mode("anc"),
                checked=lambda item: self.mode == "anc",
                radio=True,
            ),
            pystray.MenuItem("Setup", lambda icon, item: open_setup(lambda: self.apply_saved(notify=True))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(HOTKEY, None, enabled=False),
            pystray.MenuItem(lambda item: self._status_line(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self.quit()),
        )

    def quit(self):
        self._quit = True
        self._wake.set()
        self.session.stop()
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
    print(f"dll={'loaded' if apo_loaded() else 'not-loaded'}")
    print(HONEST)
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
        if not apo_loaded():
            app._warn_apo()
        if not load_state().get("setup_done"):
            open_setup(lambda: app.apply_saved(notify=True))
        else:
            app.apply_saved(notify=False)

    try:
        icon.run(setup)
    finally:
        app._quit = True
        app._wake.set()
        hook.stop()
        app.session.stop()
        app.engine.stop()
    return 0
