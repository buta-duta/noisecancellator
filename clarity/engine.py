from clarity.devices import listening_device
from clarity.eqfile import write_eq
from clarity.persist import log


class Engine:
    def __init__(self):
        self.active = False
        self.error = ""
        self.device_name = ""
        self.latency_ms = 0.0
        self.on_failure = None

    def start(self):
        try:
            device = listening_device()
            self.device_name = getattr(device, "FriendlyName", "") or ""
            write_eq(True)
        except Exception as exc:
            self.active = False
            self.error = str(exc).splitlines()[0][:180]
            log(exc)
            return False, self.error
        self.active = True
        self.latency_ms = 0.0
        log(f"clarity on {self.device_name}")
        return True, ""

    def stop(self):
        try:
            write_eq(False)
        except Exception as exc:
            self.error = str(exc).splitlines()[0][:180]
            log(exc)
            self.active = False
            return False, self.error
        self.active = False
        log("clarity off")
        return True, ""
