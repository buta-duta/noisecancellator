import ctypes
import threading
import time
from ctypes import wintypes

from clarity.hotkey import VK_NUMLOCK, NumLockEightChord, numlock_is_physically_down
from clarity.persist import log

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
HC_ACTION = 0
LLKHF_UP = 0x80
PM_NOREMOVE = 0

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", wintypes.UINT),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


LowLevelProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class KeyboardHook:
    def __init__(self):
        self.chord = NumLockEightChord()
        self._proc = LowLevelProc(self._callback)
        self._hook = None
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._toggle = None
        self._error = None

    def _callback(self, n_code, w_param, l_param):
        if n_code == HC_ACTION and w_param in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
            try:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                is_up = bool(info.flags & LLKHF_UP) or w_param in (WM_KEYUP, WM_SYSKEYUP)
                held = None
                if info.vkCode != VK_NUMLOCK:
                    held = numlock_is_physically_down(user32.GetAsyncKeyState(VK_NUMLOCK))
                decision = self.chord.on_key(
                    info.vkCode,
                    info.scanCode,
                    not is_up,
                    numlock_held=held,
                    now=time.monotonic(),
                )
                if decision.toggle and self._toggle is not None:
                    self._toggle()
                if decision.swallow:
                    return 1
            except Exception as exc:
                log(f"hook vk={getattr(locals().get('info', None), 'vkCode', '?')} {exc}")
                return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _loop(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        message = MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_NOREMOVE)
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, module, 0)
        if not self._hook:
            self._error = ctypes.get_last_error()
            self._ready.set()
            return
        self._ready.set()
        while True:
            code = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if code <= 0:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def start(self, on_toggle):
        self._toggle = on_toggle
        self._thread = threading.Thread(target=self._loop, name="clarity-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(3.0):
            raise RuntimeError("keyboard hook did not start")
        if not self._hook:
            raise RuntimeError(f"keyboard hook failed ({self._error})")
        log("hook installed")

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None
