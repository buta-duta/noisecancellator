import os
import threading

from pycaw.constants import EDataFlow, ERole
from pycaw.pycaw import AudioUtilities

from clarity.persist import clear_ledger, load_ledger, log, save_ledger
from clarity.wasapi_playback import iter_sessions, render_devices

_LOCK = threading.Lock()


def classify_name(name):
    text = (name or "").casefold()
    if "hands-free" in text or "hands free" in text:
        return "bad"
    if any(token in text for token in ("headphone", "наушник", "earphone", "airpod")):
        return "phones"
    if any(token in text for token in ("speaker", "динамик")):
        return "speakers"
    return "other"


def mirror_scalar(listen_scalar, previous_capture, new_capture):
    if previous_capture <= 0.001:
        return max(0.0, min(1.0, float(new_capture)))
    updated = float(listen_scalar) * (float(new_capture) / float(previous_capture))
    return max(0.0, min(1.0, updated))


def _default_id(role):
    enumerator = AudioUtilities.GetDeviceEnumerator()
    device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, role)
    return AudioUtilities.CreateDevice(device).id


def _find(device_id):
    if not device_id:
        return None
    for device in render_devices():
        if device.id == device_id:
            return device
    return None


def pick_pair():
    devices = render_devices()
    phones = [device for device in devices if classify_name(device.FriendlyName) == "phones"]
    speakers = [device for device in devices if classify_name(device.FriendlyName) == "speakers"]
    others = [device for device in devices if classify_name(device.FriendlyName) == "other"]
    listen = phones[0] if phones else (devices[0] if devices else None)
    capture = None
    for device in speakers + others + phones:
        if listen is not None and device.id != listen.id:
            capture = device
            break
    if listen is None or capture is None:
        raise OSError(
            "Need two playback devices so system audio can be processed without doubling it"
        )
    return listen, capture


def _session_key(device, session):
    try:
        ident = session.InstanceIdentifier or ""
    except Exception:
        ident = ""
    return f"{device.id}|{int(session.ProcessId)}|{ident}"


def _restore_saved(data):
    if data.get("console_id"):
        AudioUtilities.SetDefaultDevice(data["console_id"], [ERole.eConsole])
    if data.get("multimedia_id"):
        AudioUtilities.SetDefaultDevice(data["multimedia_id"], [ERole.eMultimedia])
    device = _find(data.get("capture_id"))
    if device is not None:
        endpoint = device.EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(float(data.get("capture_level", 1.0)), None)
        endpoint.SetMute(1 if data.get("capture_muted") else 0, None)
    pending = dict(data.get("sessions") or {})
    if not pending:
        return
    for render in render_devices():
        for session in iter_sessions(render):
            key = _session_key(render, session)
            if key not in pending:
                continue
            item = pending.pop(key)
            volume = session.SimpleAudioVolume
            volume.SetMasterVolume(float(item.get("volume", 1.0)), None)
            volume.SetMute(1 if item.get("was_muted") else 0, None)


def restore_route():
    with _LOCK:
        data = load_ledger()
        if not data:
            return
        try:
            _restore_saved(data)
        except Exception as exc:
            log(f"route restore failed: {exc}")
            return
        clear_ledger()


class Route:
    def __init__(self):
        self.armed = False
        self.listen = None
        self.capture = None
        self.last_scalar = None
        self.ledger = None

    def arm(self, listen, capture):
        with _LOCK:
            ledger = {
                "console_id": _default_id(ERole.eConsole.value),
                "multimedia_id": _default_id(ERole.eMultimedia.value),
                "capture_id": capture.id,
                "capture_level": float(capture.EndpointVolume.GetMasterVolumeLevelScalar()),
                "capture_muted": bool(capture.EndpointVolume.GetMute()),
                "sessions": {},
            }
            save_ledger(ledger)
            self.ledger = ledger
            self.listen = listen
            self.capture = capture
            try:
                capture.EndpointVolume.SetMute(1, None)
                AudioUtilities.SetDefaultDevice(
                    capture.id, [ERole.eConsole, ERole.eMultimedia]
                )
                self._duck_listen()
            except Exception:
                self.armed = False
                try:
                    _restore_saved(ledger)
                except Exception as exc:
                    log(exc)
                clear_ledger()
                self.ledger = None
                raise
            self.last_scalar = float(capture.EndpointVolume.GetMasterVolumeLevelScalar())
            self.armed = True

    def poll(self):
        with _LOCK:
            if not self.armed or self.capture is None or self.listen is None:
                return
            endpoint = self.capture.EndpointVolume
            scalar = float(endpoint.GetMasterVolumeLevelScalar())
            if self.last_scalar is not None and abs(scalar - self.last_scalar) > 0.001:
                listen_endpoint = self.listen.EndpointVolume
                current = float(listen_endpoint.GetMasterVolumeLevelScalar())
                listen_endpoint.SetMasterVolumeLevelScalar(
                    mirror_scalar(current, self.last_scalar, scalar), None
                )
            self.last_scalar = scalar
            if not bool(endpoint.GetMute()):
                endpoint.SetMute(1, None)
            self._duck_listen()

    def restore(self):
        with _LOCK:
            self.armed = False
            data = self.ledger or load_ledger()
            self.listen = None
            self.capture = None
            self.last_scalar = None
            self.ledger = None
            if not data:
                return
            try:
                _restore_saved(data)
            except Exception as exc:
                log(f"route restore failed: {exc}")
                return
            clear_ledger()

    def _duck_listen(self):
        if self.ledger is None or self.listen is None:
            return
        changed = False
        try:
            sessions = list(iter_sessions(self.listen))
        except Exception as exc:
            log(exc)
            return
        for session in sessions:
            try:
                if int(session.ProcessId) == os.getpid():
                    continue
                key = _session_key(self.listen, session)
                volume = session.SimpleAudioVolume
                if key not in self.ledger["sessions"]:
                    self.ledger["sessions"][key] = {
                        "was_muted": bool(volume.GetMute()),
                        "volume": float(volume.GetMasterVolume()),
                    }
                    changed = True
                if not bool(volume.GetMute()):
                    volume.SetMute(1, None)
            except Exception as exc:
                log(exc)
        if changed:
            save_ledger(self.ledger)
