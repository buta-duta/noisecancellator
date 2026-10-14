import ctypes
from ctypes import wintypes

ole32 = ctypes.WinDLL("ole32")
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
_COINIT_APARTMENTTHREADED = 2
_RPC_E_CHANGED_MODE = -2147417850

from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import AudioUtilities


def init_com():
    hr = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED))
    if hr in (0, 1) or hr == _RPC_E_CHANGED_MODE:
        return
    raise OSError(f"CoInitializeEx failed ({hr})")


def classify_name(name):
    text = (name or "").casefold()
    if "hands-free" in text or "hands free" in text:
        return "bad"
    if any(token in text for token in ("headphone", "наушник", "earphone", "airpod")):
        return "phones"
    if any(token in text for token in ("speaker", "динамик")):
        return "speakers"
    return "other"


def endpoint_guid(device_id):
    text = str(device_id or "")
    marker = "}."
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.strip()


def default_render():
    init_com()
    enumerator = AudioUtilities.GetDeviceEnumerator()
    device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eConsole.value)
    return AudioUtilities.CreateDevice(device)


def render_devices():
    init_com()
    found = AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eRender.value,
        device_state=DEVICE_STATE.ACTIVE.value,
    )
    return [device for device in found if classify_name(device.FriendlyName) != "bad"]


def listening_device():
    devices = render_devices()
    default = default_render()
    phones = [device for device in devices if classify_name(device.FriendlyName) == "phones"]
    for device in phones:
        if default is not None and device.id == default.id:
            return device
    if phones:
        return phones[0]
    if default is not None and classify_name(default.FriendlyName) != "bad":
        return default
    return devices[0] if devices else None


if __name__ == "__main__":
    device = listening_device()
    if device is None:
        raise SystemExit(1)
    print(endpoint_guid(device.id))
    print(device.FriendlyName)
