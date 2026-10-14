import ctypes
from ctypes import POINTER, byref, c_float, c_uint32, c_void_p
from ctypes.wintypes import DWORD

import numpy as np
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
from clarity.report import AppIssue
from pycaw.api.audioclient import IAudioClient
from pycaw.pycaw import AudioUtilities

ole32 = ctypes.WinDLL("ole32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateEventW.argtypes = [c_void_p, ctypes.c_int, ctypes.c_int, c_void_p]
kernel32.CreateEventW.restype = c_void_p
kernel32.WaitForSingleObject.argtypes = [c_void_p, DWORD]
kernel32.WaitForSingleObject.restype = DWORD
ole32.CoInitializeEx.argtypes = [c_void_p, DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoUninitialize.argtypes = []

_COINIT_APARTMENT = 2
_CHANGED = -2147417850
_EVENT = 0x00040000
_LOOPBACK = 0x00020000
_SILENT = 0x2


class IAudioRenderClient(IUnknown):
    _iid_ = GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetBuffer", (["in"], c_uint32, "n"), (["out"], POINTER(c_void_p), "pp")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "n"), (["in"], DWORD, "flags")),
    )


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
    _methods_ = (
        COMMETHOD(
            [],
            HRESULT,
            "GetBuffer",
            (["out"], POINTER(c_void_p), "pp"),
            (["out"], POINTER(c_uint32), "frames"),
            (["out"], POINTER(DWORD), "flags"),
            (["out"], POINTER(ctypes.c_uint64), "pos"),
            (["out"], POINTER(ctypes.c_uint64), "qpc"),
        ),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "frames")),
    )


def com_enter():
    hr = int(ole32.CoInitializeEx(None, _COINIT_APARTMENT))
    if hr in (0, 1):
        return True
    if hr == _CHANGED:
        return False
    raise OSError(f"COM init failed ({hr})")


def com_leave(owned):
    if owned:
        ole32.CoUninitialize()


def _pcm_kind(fmt):
    info = fmt.contents
    if int(info.wFormatTag) == 3:
        return "float"
    if int(info.wFormatTag) == 1:
        return "pcm"
    raw = ctypes.string_at(ctypes.addressof(info), 40)
    marker = raw[24:28]
    if marker == b"\x01\x00\x00\x00":
        return "pcm"
    return "float"


def _open_error(exc, microphone):
    if isinstance(exc, AppIssue):
        raise exc
    code = getattr(exc, "hresult", 0) or 0
    code &= 0xFFFFFFFF
    if microphone and code == 0x8889000A:
        raise AppIssue("mic_busy") from exc
    if microphone and code in (0x80070005, 0x80070057):
        raise AppIssue("mic_denied") from exc
    if microphone:
        raise AppIssue("mic_missing") from exc
    raise AppIssue("output_missing") from exc


class Stream:
    def __init__(self, device_id, *, playback=False, loopback=False):
        self.device_id = device_id
        self.playback = playback
        self.loopback = loopback
        self.client = None
        self.render = None
        self.capture = None
        self.rate = 48000
        self.channels = 2
        self.align = 8
        self.bits = 32
        self.kind = "float"
        self.period_frames = 480
        self.buffer_frames = 0
        self._event = None

    def _client(self, device, flags):
        iface = device.Activate(IAudioClient._iid_, CLSCTX_ALL, None)
        client = iface.QueryInterface(IAudioClient)
        fmt = client.GetMixFormat()
        info = fmt.contents
        self.rate = int(info.nSamplesPerSec)
        self.channels = int(info.nChannels)
        self.align = int(info.nBlockAlign)
        self.bits = int(info.wBitsPerSample)
        self.kind = _pcm_kind(fmt)
        default_period, _minimum = client.GetDevicePeriod()
        self.period_frames = max(1, int(round(float(default_period) / 10000000.0 * self.rate)))
        client.Initialize(0, flags, 0, 0, fmt, None)
        return client

    def open(self):
        try:
            device = AudioUtilities.GetDeviceEnumerator().GetDevice(self.device_id)
            flags = _EVENT | (_LOOPBACK if self.loopback else 0)
            try:
                client = self._client(device, flags)
            except Exception:
                flags = _LOOPBACK if self.loopback else 0
                client = self._client(device, flags)
            if flags & _EVENT:
                self._event = kernel32.CreateEventW(None, 0, 0, None)
                client.SetEventHandle(self._event)
            self.client = client
            self.buffer_frames = int(client.GetBufferSize())
            if self.playback:
                self.render = client.GetService(IAudioRenderClient._iid_).QueryInterface(IAudioRenderClient)
            else:
                self.capture = client.GetService(IAudioCaptureClient._iid_).QueryInterface(IAudioCaptureClient)
            return self
        except Exception as exc:
            _open_error(exc, microphone=not self.playback and not self.loopback)

    def start(self):
        self.client.Start()

    def wait(self, timeout_ms):
        if self._event:
            kernel32.WaitForSingleObject(self._event, int(timeout_ms))

    def render_needed(self):
        padding = int(self.client.GetCurrentPadding())
        return max(0, self.buffer_frames - padding)

    def _mono(self, data, frames):
        blob = ctypes.string_at(data, int(frames) * self.align)
        if self.kind == "pcm" and self.bits == 16:
            audio = np.frombuffer(blob, dtype=np.int16).astype(np.float32) / 32768.0
        elif self.kind == "pcm":
            audio = np.frombuffer(blob, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            audio = np.frombuffer(blob, dtype=np.float32).copy()
        audio = audio.reshape(int(frames), self.channels)
        return np.mean(audio, axis=1).astype(np.float32)

    def read(self):
        parts = []
        while True:
            packet = self.capture.GetNextPacketSize()
            if not packet:
                break
            data, frames, flags, _pos, _qpc = self.capture.GetBuffer()
            count = int(frames)
            if data and count and not (int(flags) & _SILENT):
                parts.append(self._mono(data, count))
            self.capture.ReleaseBuffer(count)
        if not parts:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(parts)

    def write(self, mono):
        mono = np.asarray(mono, dtype=np.float32).reshape(-1)
        count = int(mono.size)
        if count <= 0:
            return
        block = np.zeros(count * self.channels, dtype=np.float32)
        for channel in range(self.channels):
            block[channel : count * self.channels : self.channels] = mono
        if self.kind == "pcm" and self.bits == 16:
            payload = np.clip(block * 32767.0, -32768, 32767).astype(np.int16)
        elif self.kind == "pcm":
            payload = np.clip(block * 2147483647.0, -2147483648, 2147483647).astype(np.int32)
        else:
            payload = block
        ptr = self.render.GetBuffer(count)
        ctypes.memmove(ptr, payload.ctypes.data, payload.nbytes)
        self.render.ReleaseBuffer(count, 0)

    def close(self):
        client = self.client
        self.client = None
        self.render = None
        self.capture = None
        if client is not None:
            try:
                client.Stop()
            except Exception:
                pass


def output_period(device_id):
    owned = com_enter()
    stream = Stream(device_id, playback=True)
    try:
        stream.open()
        return stream.period_frames, stream.rate
    finally:
        stream.close()
        com_leave(owned)
