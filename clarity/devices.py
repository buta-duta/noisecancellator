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


def form_factor(device):
    props = getattr(device, "properties", None) or {}
    for key, value in props.items():
        folded = str(key).casefold()
        if "1da5d803-d492-4edd-8c23-e0c0ffee7f0e" not in folded or not folded.endswith(" 0"):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def is_hands_free(name):
    text = (name or "").casefold()
    return "hands-free" in text or "hands free" in text or "handsfree" in text


def input_kind(name):
    text = (name or "").casefold()
    if is_hands_free(text):
        return "bad"
    if any(token in text for token in ("headphone", "headset", "наушник", "гарнитур", "earphone", "airpod")):
        return "headphone"
    if any(token in text for token in ("array", "набор", "internal", "built-in", "builtin", "встроен")):
        return "laptop"
    return "jack"


def choice_labels(names):
    kinds = [input_kind(name) for name in names]
    has_laptop = any(kind == "laptop" for kind in kinds)
    labeled = []
    for name, kind in zip(names, kinds):
        if kind == "bad":
            continue
        if kind == "jack":
            kind = "headphone" if has_laptop else "laptop"
        if kind == "headphone":
            text = f"{name} — headphone mic, primary reference near the ear"
        else:
            text = f"{name} — laptop mic, weaker reference, not an AirPods equivalent"
        labeled.append((kind, text))
    return labeled


def classify_name(name):
    text = (name or "").casefold()
    if is_hands_free(text):
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
    kept = []
    for device in found:
        if classify_name(device.FriendlyName) == "bad" or form_factor(device) == 6:
            continue
        kept.append(device)
    return kept


def capture_devices():
    init_com()
    capture_flow = next(item.value for item in EDataFlow if item.name.casefold() == "e" + "capture")
    found = AudioUtilities.GetAllDevices(
        data_flow=capture_flow,
        device_state=DEVICE_STATE.ACTIVE.value,
    )
    kept = []
    for device in found:
        if is_hands_free(device.FriendlyName) or input_kind(device.FriendlyName) == "bad" or form_factor(device) == 6:
            continue
        kept.append(device)
    return kept


def render_choices():
    rows = []
    for device in render_devices():
        name = device.FriendlyName or "Output"
        rows.append((device.id, name, classify_name(name)))
    return rows


def capture_choices():
    devices = capture_devices()
    labels = choice_labels([device.FriendlyName or "Microphone" for device in devices])
    rows = []
    for device, (kind, label) in zip(devices, labels):
        rows.append((device.id, label, kind))
    return rows


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
