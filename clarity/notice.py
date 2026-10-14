import ctypes
import threading
from ctypes import wintypes

from clarity.hook import MSG, user32

NOTICE_ON = "Clarity on"
NOTICE_OFF = "Clarity off"
DISMISS_MS = 1350

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = ctypes.c_void_p(-1)
WM_TIMER = 0x0113
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_SHOW = 0x8001
SPI_GETWORKAREA = 0x0030
DT_CENTER = 0x1
DT_VCENTER = 0x4
DT_SINGLELINE = 0x20
TRANSPARENT = 1
CS_HREDRAW = 0x2
CS_VREDRAW = 0x1

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def notice_label(enabled):
    return NOTICE_ON if enabled else NOTICE_OFF


def _bind():
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    user32.KillTimer.restype = wintypes.BOOL
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.restype = wintypes.BOOL
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH]
    user32.FillRect.restype = ctypes.c_int
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(RECT), wintypes.UINT]
    user32.DrawTextW.restype = ctypes.c_int
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    gdi32.CreateFontW.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPCWSTR,
    ]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
    gdi32.SetTextColor.restype = wintypes.DWORD
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkMode.restype = ctypes.c_int
    gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(SIZE)]
    gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
    gdi32.CreateRoundRectRgn.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE


_bind()


class _Host:
    def __init__(self):
        self._lock = threading.Lock()
        self._text = NOTICE_OFF
        self._hold = DISMISS_MS
        self._ready = threading.Event()
        self._hwnd = None
        self._proc = WNDPROC(self._wndproc)
        self._thread = threading.Thread(target=self._run, name="clarity-notice", daemon=True)
        self._thread.start()

    def show(self, text, hold_ms=None):
        if not self._ready.wait(2.0):
            return
        with self._lock:
            self._text = text
            self._hold = int(hold_ms or DISMISS_MS)
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_SHOW, 0, 0)

    def _text_now(self):
        with self._lock:
            return self._text

    def _place(self):
        text = self._text_now()
        hdc = user32.GetDC(self._hwnd)
        font = gdi32.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        old = gdi32.SelectObject(hdc, font)
        size = SIZE()
        gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
        gdi32.SelectObject(hdc, old)
        user32.ReleaseDC(self._hwnd, hdc)
        gdi32.DeleteObject(font)
        work = RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        margin = 16
        max_width = max(160, int(work.right - work.left) - margin * 2)
        width = min(max(96, int(size.cx) + 28), max_width)
        height = max(32, int(size.cy) + 16)
        if int(size.cx) + 28 > max_width:
            height = max(height, int(size.cy) * 2 + 20)
        x = int(work.right) - width - margin
        y = int(work.bottom) - height - margin
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, 12, 12)
        user32.SetWindowRgn(self._hwnd, region, True)
        user32.SetWindowPos(self._hwnd, HWND_TOPMOST, x, y, width, height, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.SetTimer(self._hwnd, 1, max(400, int(self._hold)), None)
        user32.InvalidateRect(self._hwnd, None, True)

    def _paint(self):
        paint = PAINTSTRUCT()
        hdc = user32.BeginPaint(self._hwnd, ctypes.byref(paint))
        rect = RECT()
        user32.GetClientRect(self._hwnd, ctypes.byref(rect))
        brush = gdi32.CreateSolidBrush(0x00221E1C)
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)
        font = gdi32.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        old = gdi32.SelectObject(hdc, font)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        gdi32.SetTextColor(hdc, 0x00F0F2F4)
        user32.DrawTextW(hdc, self._text_now(), -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(font)
        user32.EndPaint(self._hwnd, ctypes.byref(paint))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_SHOW:
            self._place()
            return 0
        if msg == WM_TIMER:
            user32.KillTimer(hwnd, 1)
            user32.ShowWindow(hwnd, SW_HIDE)
            return 0
        if msg == WM_PAINT:
            self._paint()
            return 0
        if msg == 0x0014:
            rect = RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            brush = gdi32.CreateSolidBrush(0x00221E1C)
            user32.FillRect(wparam, ctypes.byref(rect), brush)
            gdi32.DeleteObject(brush)
            return 1
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        klass = WNDCLASSW()
        klass.style = CS_HREDRAW | CS_VREDRAW
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        klass.hbrBackground = gdi32.CreateSolidBrush(0x00221E1C)
        klass.lpszClassName = "ClarityNotice"
        user32.RegisterClassW(ctypes.byref(klass))
        self._hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "ClarityNotice",
            "Clarity",
            WS_POPUP,
            0,
            0,
            10,
            10,
            None,
            None,
            instance,
            None,
        )
        if not self._hwnd:
            from clarity.persist import log

            log(f"notice window failed ({ctypes.get_last_error()})")
        self._ready.set()
        message = MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))


_host = None
_guard = threading.Lock()


def show_notice(text, hold_ms=None):
    global _host
    with _guard:
        if _host is None:
            _host = _Host()
    _host.show(text, hold_ms)
