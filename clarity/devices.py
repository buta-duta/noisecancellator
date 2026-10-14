from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import AudioUtilities

from clarity.routing import classify_name


def endpoint_guid(device_id):
    text = str(device_id or "")
    marker = "}."
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.strip()


def default_render():
    enumerator = AudioUtilities.GetDeviceEnumerator()
    device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eConsole.value)
    return AudioUtilities.CreateDevice(device)


def render_devices():
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
