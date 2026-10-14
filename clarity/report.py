import sys
import threading
import traceback

from clarity.persist import log

_MESSAGES = {
    "mic_missing": "No microphone was found.",
    "mic_headset_missing": "No headphone microphone was found.",
    "mic_laptop_missing": "No built-in laptop microphone was found.",
    "mic_busy": "The microphone is in use by another app.",
    "mic_denied": "Windows blocked access to the microphone.",
    "mic_choice": "Choose a microphone in Setup.",
    "output_missing": "No headphones are plugged in.",
    "apo_not_loaded": "Noise cancellation is not loaded. Run setup.ps1.",
    "config_missing": "Equalizer APO is not installed. Run setup.",
    "config_locked": "Could not save the Equalizer APO config.",
    "hook_failed": "Num Lock + 8 could not be registered.",
    "device_lost": "The audio device disconnected.",
}


class AppIssue(Exception):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(detail or _MESSAGES.get(code, code))


_presenter = None


def set_presenter(fn):
    global _presenter
    _presenter = fn


def explain(exc):
    if isinstance(exc, AppIssue):
        text = _MESSAGES.get(exc.code)
        if text:
            return text
        return exc.detail or exc.code
    if isinstance(exc, PermissionError):
        return _MESSAGES["config_locked"]
    if isinstance(exc, FileNotFoundError):
        return _MESSAGES["config_missing"]
    text = str(exc)
    folded = text.casefold()
    if isinstance(exc, RuntimeError) and "hook" in folded:
        return _MESSAGES["hook_failed"]
    if "config folder is missing" in folded or "equalizer apo config" in folded:
        return _MESSAGES["config_missing"]
    if "headphone microphone" in folded:
        return _MESSAGES["mic_headset_missing"]
    if "built-in" in folded or "laptop microphone" in folded:
        return _MESSAGES["mic_laptop_missing"]
    if "microphone" in folded and ("not found" in folded or "no " in folded):
        return _MESSAGES["mic_missing"]
    if "microphone" in folded and ("busy" in folded or "in use" in folded):
        return _MESSAGES["mic_busy"]
    if "microphone" in folded and ("denied" in folded or "access" in folded):
        return _MESSAGES["mic_denied"]
    if "headphone" in folded and ("not found" in folded or "no " in folded or "plug" in folded):
        return _MESSAGES["output_missing"]
    if "disconnected" in folded or "device lost" in folded or "unplugged" in folded:
        return _MESSAGES["device_lost"]
    if "not loaded" in folded or "equalizerapo.dll" in folded:
        return _MESSAGES["apo_not_loaded"]
    name = type(exc).__name__
    detail = text.splitlines()[0][:160] if text else name
    return f"Clarity stopped: {name}: {detail}"


def _message_box(text):
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, str(text), "Clarity", 0x00000030 | 0x00010000)


def present(text, hold_ms=4500, crash=False):
    log(text)
    shown = False
    if _presenter is not None:
        try:
            _presenter(str(text), hold_ms)
            shown = True
        except Exception as exc:
            log(exc)
    if crash or not shown:
        try:
            _message_box(text)
        except Exception as exc:
            log(exc)


def report_exception(exc, crash=False):
    log("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    present(explain(exc), crash=crash)


def install_crash_report():
    def _sys(exc_type, exc, tb):
        if exc is None:
            exc = exc_type()
        report_exception(exc, crash=True)

    def _thread(args):
        report_exception(args.exc_value, crash=True)

    sys.excepthook = _sys
    threading.excepthook = _thread
