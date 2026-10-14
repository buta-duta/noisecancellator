import math
import threading

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, COMObject
from ctypes import (
    POINTER,
    Structure,
    WinDLL,
    addressof,
    byref,
    c_long,
    c_longlong,
    c_uint64,
    c_void_p,
    cast,
    string_at,
)
from ctypes import wintypes
from pycaw.api.audioclient import IAudioClient
from pycaw.api.audiopolicy import IAudioSessionControl2
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import AudioSession, AudioUtilities

from clarity.persist import log

# Process-loopback reads other programs' playback mix. It is not a capture device.
VIRTUAL_LOOPBACK = "VAD\\Process_Loopback"
PROCESS_LOOPBACK_INCLUDE = 0
PROCESS_LOOPBACK_EXCLUDE = 1
ACTIVATION_PROCESS_LOOPBACK = 1
STREAM_LOOPBACK = 0x00020000
STREAM_EVENT = 0x00040000
STREAM_AUTOCONVERT = 0x80000000
STREAM_SRC_QUALITY = 0x08000000
BUFFER_SILENT = 0x2
SHARE_SHARED = 0
VT_BLOB = 65
FLOAT_MARK = b"\x03\x00\x00\x00\x00\x00\x10\x00"
PCM_MARK = b"\x01\x00\x00\x00\x00\x00\x10\x00"
IID_CAPTURE = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
IID_RENDER = GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")

ole32 = WinDLL("ole32")
mmdevapi = WinDLL("Mmdevapi")
kernel32 = WinDLL("kernel32")

ole32.CoTaskMemFree.argtypes = [c_void_p]
ole32.CoTaskMemFree.restype = None
ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = c_long
ole32.CoUninitialize.argtypes = []
ole32.CoUninitialize.restype = None

kernel32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForMultipleObjects.argtypes = [
    wintypes.DWORD,
    POINTER(wintypes.HANDLE),
    wintypes.BOOL,
    wintypes.DWORD,
]
kernel32.WaitForMultipleObjects.restype = wintypes.DWORD

_activate = mmdevapi.ActivateAudioInterfaceAsync
_activate.argtypes = [wintypes.LPCWSTR, POINTER(GUID), c_void_p, c_void_p, POINTER(c_void_p)]
_activate.restype = c_long


class ActivationParams(Structure):
    _fields_ = [
        ("activation_type", wintypes.DWORD),
        ("target_pid", wintypes.DWORD),
        ("mode", wintypes.DWORD),
    ]


class BlobVariant(Structure):
    _fields_ = [
        ("vt", wintypes.WORD),
        ("reserved1", wintypes.WORD),
        ("reserved2", wintypes.WORD),
        ("reserved3", wintypes.WORD),
        ("cb_size", wintypes.ULONG),
        ("blob", c_void_p),
    ]


class FormatInfo:
    def __init__(self, rate, channels, bits, block, is_float, tag):
        self.rate = int(rate)
        self.channels = int(channels)
        self.bits = int(bits)
        self.block = int(block)
        self.is_float = bool(is_float)
        self.tag = int(tag)

    def __str__(self):
        kind = "float" if self.is_float else "pcm"
        return f"{self.rate} Hz {self.channels} ch {self.bits}-bit {kind}"


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "GetActivateResult",
            (["out"], POINTER(HRESULT), "activateResult"),
            (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
        )
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "ActivateCompleted",
            (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation"),
        )
    ]


class IAgileObject(IUnknown):
    # ActivateAudioInterfaceAsync rejects the handler without this IID.
    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_ = []


class _ActivationHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self, done):
        self._done = done
        super().__init__()

    def ActivateCompleted(self, _operation):
        self._done.set()


def init_mta():
    hr = ole32.CoInitializeEx(None, 0)
    if hr < 0:
        raise OSError(f"COM init failed: {hr & 0xFFFFFFFF:#010x}")
    return hr


def uninit_com():
    ole32.CoUninitialize()


def _hr(value):
    return int(value) & 0xFFFFFFFF


def _check(hr, what):
    if int(hr) < 0:
        raise OSError(f"{what} failed: {_hr(hr):#010x}")


def _raw(obj):
    return cast(obj, c_void_p).value


def _slot(value):
    return value.value if hasattr(value, "value") else value


def ctypes_fn(table, index, restype, argtypes):
    proto = ctypes_fn_type(restype, argtypes)
    return proto(_slot(table[index]))


def ctypes_fn_type(restype, argtypes):
    from ctypes import CFUNCTYPE

    return CFUNCTYPE(restype, c_void_p, *argtypes)


def _call(ptr, index, restype, argtypes, *args):
    vtbl = _slot(cast(c_void_p(ptr), POINTER(c_void_p))[0])
    table = cast(c_void_p(vtbl), POINTER(c_void_p))
    fn = ctypes_fn(table, index, restype, argtypes)
    return fn(ptr, *args)


def parse_format(ptr):
    raw = string_at(ptr, 80)
    tag = int.from_bytes(raw[0:2], "little")
    channels = int.from_bytes(raw[2:4], "little")
    rate = int.from_bytes(raw[4:8], "little")
    block = int.from_bytes(raw[12:14], "little")
    bits = int.from_bytes(raw[14:16], "little")
    is_float = tag == 3
    if tag == 0xFFFE:
        is_float = FLOAT_MARK in raw[:64]
        if not is_float and PCM_MARK not in raw[:64] and bits == 32:
            is_float = True
    if channels < 1 or channels > 8 or rate < 8000 or rate > 384000 or block < 1:
        raise OSError(f"unsupported playback format {raw[:40].hex()}")
    return FormatInfo(rate, channels, bits, block, is_float, tag)


def decode_frames(blob, info, frames):
    import numpy as np

    if frames <= 0:
        return np.zeros((0, info.channels), dtype=np.float64)
    count = frames * info.channels
    if info.is_float and info.bits == 32:
        data = np.frombuffer(blob, dtype=np.float32, count=count)
        audio = data.astype(np.float64)
    elif info.bits == 16:
        data = np.frombuffer(blob, dtype=np.int16, count=count)
        audio = data.astype(np.float64) / 32768.0
    elif info.bits == 32 and not info.is_float:
        data = np.frombuffer(blob, dtype=np.int32, count=count)
        audio = data.astype(np.float64) / 2147483648.0
    else:
        raise OSError(f"cannot read playback format {info}")
    return audio.reshape(frames, info.channels)


def encode_frames(audio, info):
    import numpy as np

    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.shape[1] != info.channels:
        if audio.shape[1] == 1:
            audio = np.repeat(audio, info.channels, axis=1)
        else:
            audio = audio[:, : info.channels]
    clipped = np.clip(audio, -1.0, 1.0)
    if info.is_float and info.bits == 32:
        return np.ascontiguousarray(clipped, dtype=np.float32).tobytes()
    if info.bits == 16:
        pcm = np.clip(np.round(clipped * 32767.0), -32768, 32767).astype(np.int16)
        return np.ascontiguousarray(pcm).tobytes()
    if info.bits == 32:
        pcm = np.clip(np.round(clipped * 2147483647.0), -2147483648, 2147483647).astype(np.int32)
        return np.ascontiguousarray(pcm).tobytes()
    raise OSError(f"cannot write playback format {info}")


def _bad_name(name):
    text = (name or "").casefold()
    return "hands-free" in text or "hands free" in text


def default_render(role):
    enumerator = AudioUtilities.GetDeviceEnumerator()
    device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, role)
    return AudioUtilities.CreateDevice(device)


def render_devices():
    found = AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eRender.value,
        device_state=DEVICE_STATE.ACTIVE.value,
    )
    return [device for device in found if not _bad_name(device.FriendlyName)]


def choose_output():
    console = default_render(ERole.eConsole.value)
    try:
        media = default_render(ERole.eMultimedia.value)
    except OSError:
        media = console
    output = console
    if _bad_name(getattr(console, "FriendlyName", "")):
        safe = render_devices()
        if not safe:
            raise OSError("No playback device is available off the hands-free path")
        output = safe[0]
    targets = []
    seen = set()
    for device in (output, console, media):
        if device is None or _bad_name(getattr(device, "FriendlyName", "")):
            continue
        if device.id in seen:
            continue
        seen.add(device.id)
        targets.append(device)
    return output, targets


def iter_sessions(device):
    manager = device.AudioSessionManager
    enumerator = manager.GetSessionEnumerator()
    count = int(enumerator.GetCount())
    for index in range(count):
        ctl = enumerator.GetSession(index)
        if ctl is None:
            continue
        yield AudioSession(ctl.QueryInterface(IAudioSessionControl2))


class EndpointStream:
    def __init__(self):
        self.client = None
        self.client_ptr = None
        self.service_ptr = None
        self.event = None
        self.format = None
        self.format_ptr = None
        self.buffer_frames = 0
        self.started = False
        self._owns_format = False

    def period_ms(self):
        if not self.format or not self.buffer_frames:
            return 0.0
        return 1000.0 * self.buffer_frames / self.format.rate

    def _set_client(self, client):
        self.client = client
        self.client_ptr = _raw(client)
        if not self.client_ptr:
            raise OSError("playback client pointer is empty")

    def _mix_format(self):
        out = c_void_p()
        hr = _call(self.client_ptr, 8, c_long, [POINTER(c_void_p)], byref(out))
        _check(hr, "GetMixFormat")
        if not out.value:
            raise OSError("playback mix format is empty")
        self.format_ptr = out.value
        self._owns_format = True
        self.format = parse_format(out.value)

    def _format_arg(self):
        from pycaw.api.audioclient.depend import WAVEFORMATEX

        return cast(c_void_p(self.format_ptr), POINTER(WAVEFORMATEX))

    def _event(self):
        self.event = kernel32.CreateEventW(None, False, False, None)
        if not self.event:
            raise OSError("audio event was not created")
        self.client.SetEventHandle(self.event)

    def _buffer_size(self):
        frames = wintypes.UINT()
        hr = _call(self.client_ptr, 4, c_long, [POINTER(wintypes.UINT)], byref(frames))
        _check(hr, "GetBufferSize")
        self.buffer_frames = int(frames.value)

    def _service(self, iid):
        unk = self.client.GetService(iid)
        ptr = _raw(unk)
        if not ptr:
            raise OSError("audio service pointer is empty")
        self._service_unk = unk
        self.service_ptr = ptr

    def start(self):
        if not self.started:
            self.client.Start()
            self.started = True

    def stop(self):
        if self.started and self.client is not None:
            try:
                self.client.Stop()
            except OSError as exc:
                log(exc)
            self.started = False

    def close(self):
        self.stop()
        if self.format_ptr and self._owns_format:
            ole32.CoTaskMemFree(self.format_ptr)
        self.format_ptr = None
        if self.event:
            kernel32.CloseHandle(self.event)
            self.event = None
        self.client = None
        self.client_ptr = None
        self.service_ptr = None

    def wait(self, timeout_ms):
        if self.event:
            kernel32.WaitForSingleObject(self.event, int(timeout_ms))


class LoopbackStream(EndpointStream):
    def __init__(self, pid, exclude_tree, rate=48000, channels=2):
        super().__init__()
        self._open(pid, exclude_tree, rate, channels)

    def _open(self, pid, exclude_tree, rate, channels):
        done = threading.Event()
        handler = _ActivationHandler(done)
        params = ActivationParams()
        params.activation_type = ACTIVATION_PROCESS_LOOPBACK
        params.target_pid = int(pid)
        params.mode = PROCESS_LOOPBACK_EXCLUDE if exclude_tree else PROCESS_LOOPBACK_INCLUDE
        variant = BlobVariant()
        variant.vt = VT_BLOB
        variant.cb_size = ctypes_sizeof(params)
        variant.blob = addressof(params)
        handler_ptr = handler._com_pointers_[IActivateAudioInterfaceCompletionHandler._iid_]
        op = c_void_p()
        hr = _activate(
            VIRTUAL_LOOPBACK,
            byref(IAudioClient._iid_),
            c_void_p(addressof(variant)),
            c_void_p(addressof(handler_ptr.contents)),
            byref(op),
        )
        _check(hr, "ActivateAudioInterfaceAsync")
        if not done.wait(3.0):
            raise OSError("playback loopback activation timed out")
        if not op.value:
            raise OSError("playback loopback returned no operation")
        act_hr = c_long()
        punk = c_void_p()
        hr = _call(
            op.value,
            3,
            c_long,
            [POINTER(c_long), POINTER(c_void_p)],
            byref(act_hr),
            byref(punk),
        )
        _check(hr, "GetActivateResult")
        _check(act_hr.value, "playback loopback activate")
        if not punk.value:
            raise OSError("playback loopback client is empty")
        client = cast(c_void_p(punk.value), POINTER(IAudioClient))
        self._set_client(client)
        self._handler = handler
        self._params = params
        self._variant = variant
        self._op = op
        # Process loopback does not implement GetMixFormat. Ask for float and convert.
        self._format_buf = float_format(rate, channels)
        self.format_ptr = addressof(self._format_buf)
        self._owns_format = False
        self.format = parse_format(self.format_ptr)
        flags = STREAM_LOOPBACK | STREAM_EVENT | STREAM_AUTOCONVERT | STREAM_SRC_QUALITY
        try:
            self.client.Initialize(SHARE_SHARED, flags, 0, 0, self._format_arg(), None)
        except OSError:
            raise
        except Exception as exc:
            raise OSError(f"loopback Initialize failed: {exc}") from exc
        self._event()
        self._buffer_size()
        self._service(IID_CAPTURE)
        log(f"loopback {self.format} buffer={self.buffer_frames}")

    def read(self):
        import numpy as np

        if not self.service_ptr:
            return np.zeros((0, self.format.channels), dtype=np.float64)
        chunks = []
        while True:
            packet = wintypes.UINT()
            hr = _call(self.service_ptr, 5, c_long, [POINTER(wintypes.UINT)], byref(packet))
            _check(hr, "GetNextPacketSize")
            if packet.value == 0:
                break
            data = c_void_p()
            frames = wintypes.UINT()
            flags = wintypes.DWORD()
            dev = c_uint64()
            qpc = c_uint64()
            hr = _call(
                self.service_ptr,
                3,
                c_long,
                [POINTER(c_void_p), POINTER(wintypes.UINT), POINTER(wintypes.DWORD), POINTER(c_uint64), POINTER(c_uint64)],
                byref(data),
                byref(frames),
                byref(flags),
                byref(dev),
                byref(qpc),
            )
            _check(hr, "loopback GetBuffer")
            count = int(frames.value)
            try:
                if flags.value & BUFFER_SILENT or not data.value or count == 0:
                    audio = np.zeros((count, self.format.channels), dtype=np.float64)
                else:
                    blob = string_at(data.value, count * self.format.block)
                    audio = decode_frames(blob, self.format, count)
            finally:
                rel = _call(self.service_ptr, 4, c_long, [wintypes.UINT], count)
                _check(rel, "loopback ReleaseBuffer")
            if count:
                chunks.append(audio)
        if not chunks:
            return np.zeros((0, self.format.channels), dtype=np.float64)
        return np.concatenate(chunks, axis=0)

    def close(self):
        super().close()
        if getattr(self, "_op", None) and self._op.value:
            _call(self._op.value, 2, c_long, [])
            self._op = None


class DeviceLoopback(EndpointStream):
    # Playback-endpoint loopback. Not a capture device.
    def __init__(self, device):
        super().__init__()
        self.device_name = getattr(device, "FriendlyName", "") or "Playback"
        activated = device._dev.Activate(IAudioClient._iid_, comtypes.CLSCTX_ALL, None)
        self._set_client(activated.QueryInterface(IAudioClient))
        self._mix_format()
        try:
            self.client.Initialize(
                SHARE_SHARED,
                STREAM_LOOPBACK | STREAM_EVENT,
                0,
                0,
                self._format_arg(),
                None,
            )
        except Exception as exc:
            raise OSError(f"device loopback Initialize failed: {exc}") from exc
        self._event()
        self._buffer_size()
        self._service(IID_CAPTURE)

    read = LoopbackStream.read


class RenderStream(EndpointStream):
    def __init__(self, device, source_format=None):
        super().__init__()
        self.device_name = getattr(device, "FriendlyName", "") or "Playback"
        self._open(device, source_format)

    def _open(self, device, source_format):
        activated = device._dev.Activate(IAudioClient._iid_, comtypes.CLSCTX_ALL, None)
        self._set_client(activated.QueryInterface(IAudioClient))
        native_ptr = c_void_p()
        hr = _call(self.client_ptr, 8, c_long, [POINTER(c_void_p)], byref(native_ptr))
        _check(hr, "render GetMixFormat")
        self._native_ptr = native_ptr.value
        self.format_ptr = source_format if source_format else native_ptr.value
        self.format = parse_format(self.format_ptr)
        flags = STREAM_EVENT
        if source_format:
            flags |= STREAM_AUTOCONVERT | STREAM_SRC_QUALITY
        duration = self._default_period()
        try:
            self.client.Initialize(SHARE_SHARED, flags, int(duration), 0, self._format_arg(), None)
        except Exception as first:
            if not source_format:
                raise OSError(f"render Initialize failed: {first}") from first
            log(f"render autoconvert declined ({first}); using device format")
            if self.format_ptr != self._native_ptr:
                self.format_ptr = self._native_ptr
                self.format = parse_format(self.format_ptr)
            self.client.Initialize(SHARE_SHARED, STREAM_EVENT, int(duration), 0, self._format_arg(), None)
        self._owns_format = self.format_ptr == self._native_ptr
        self._event()
        self._buffer_size()
        self._service(IID_RENDER)
        log(f"render {self.device_name} {self.format} buffer={self.buffer_frames}")

    def _default_period(self):
        default = c_longlong()
        minimum = c_longlong()
        hr = _call(
            self.client_ptr,
            9,
            c_long,
            [POINTER(c_longlong), POINTER(c_longlong)],
            byref(default),
            byref(minimum),
        )
        _check(hr, "GetDevicePeriod")
        return int(default.value)

    def available(self):
        padding = wintypes.UINT()
        hr = _call(self.client_ptr, 6, c_long, [POINTER(wintypes.UINT)], byref(padding))
        _check(hr, "GetCurrentPadding")
        return max(0, self.buffer_frames - int(padding.value))

    def write(self, audio):
        import numpy as np

        audio = np.asarray(audio, dtype=np.float64)
        if audio.ndim == 1:
            audio = audio[:, None]
        frames = int(audio.shape[0])
        if frames <= 0:
            return
        data = c_void_p()
        hr = _call(self.service_ptr, 3, c_long, [wintypes.UINT, POINTER(c_void_p)], frames, byref(data))
        _check(hr, "render GetBuffer")
        try:
            blob = encode_frames(audio, self.format)
            expected = frames * self.format.block
            if len(blob) != expected:
                raise OSError("playback frame size mismatch")
            if data.value:
                ctypes_memmove(data.value, blob, expected)
        finally:
            rel = _call(self.service_ptr, 4, c_long, [wintypes.UINT, wintypes.DWORD], frames, 0)
            _check(rel, "render ReleaseBuffer")

    def close(self):
        native = getattr(self, "_native_ptr", None)
        owns_native = self._owns_format
        super().close()
        if native and not owns_native:
            ole32.CoTaskMemFree(native)
        self._native_ptr = None


def ctypes_sizeof(obj):
    from ctypes import sizeof

    return sizeof(obj)


def ctypes_memmove(dest, blob, size):
    from ctypes import memmove

    memmove(dest, blob, size)


def float_format(rate, channels):
    import struct

    channels = int(channels)
    rate = int(rate)
    masks = {1: 0x4, 2: 0x3, 4: 0x33, 6: 0x3F, 8: 0x63F}
    block = channels * 4
    header = struct.pack("<HHIIHHH", 0xFFFE, channels, rate, rate * block, block, 32, 22)
    rest = struct.pack("<HI", 32, masks.get(channels, 0))
    guid = bytes.fromhex("0300000000001000800000aa00389b71")
    return create_string_buffer(header + rest + guid)


def create_string_buffer(raw):
    from ctypes import create_string_buffer as _buf

    return _buf(raw)


def stream_latency_ms(client_ptr):
    value = c_longlong()
    hr = _call(client_ptr, 5, c_long, [POINTER(c_longlong)], byref(value))
    if int(hr) < 0:
        return 0.0
    return int(value.value) / 10000.0


def play_tone(seconds, hz, amplitude, device=None):
    import numpy as np

    output, _targets = choose_output()
    if device is not None:
        output = device
    render = RenderStream(output)
    try:
        rate = render.format.rate
        channels = render.format.channels
        count = int(rate * seconds)
        t = np.arange(count, dtype=np.float64) / rate
        sine = float(amplitude) * np.sin(2.0 * math.pi * float(hz) * t)
        audio = np.repeat(sine[:, None], channels, axis=1)
        render.start()
        offset = 0
        while offset < count:
            render.wait(200)
            room = render.available()
            if room <= 0:
                continue
            piece = audio[offset : offset + room]
            if len(piece) < room:
                pad = np.zeros((room - len(piece), channels), dtype=np.float64)
                piece = np.concatenate([piece, pad], axis=0)
            render.write(piece)
            offset += room
            if offset >= count:
                break
        render.wait(int(render.period_ms()) + 20)
    finally:
        render.close()


def wait_many(handles, timeout_ms):
    count = len(handles)
    array = (wintypes.HANDLE * count)(*handles)
    return kernel32.WaitForMultipleObjects(count, array, False, int(timeout_ms))
