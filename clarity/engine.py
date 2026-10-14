from clarity.eqfile import write_eq
from clarity.persist import log


class Engine:
    def __init__(self):
        self.active = False
        self.error = ""
        self.latency_ms = 0.0

    def start(self):
        try:
            write_eq(True)
        except OSError as exc:
            self.active = False
            self.error = str(exc).splitlines()[0][:180]
            log(exc)
            return False, self.error
        self.active = True
        self.latency_ms = 0.0
        log("clarity on")
        return True, ""

    def stop(self):
        try:
            write_eq(False)
        except OSError as exc:
            self.error = str(exc).splitlines()[0][:180]
            log(exc)
            self.active = False
            return False, self.error
        self.active = False
        log("clarity off")
        return True, ""
