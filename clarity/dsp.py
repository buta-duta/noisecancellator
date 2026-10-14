import math

import numpy as np
from scipy.signal import sosfilt

PREAMP_DB = 0.0
PRESENCE_HZ = 3200.0
PRESENCE_DB = 3.5
PRESENCE_Q = 0.65
LOW_SHELF_HZ = 120.0
LOW_SHELF_DB = -2.5
LOW_SHELF_Q = 0.7
SIBILANCE_HZ = 7200.0
SIBILANCE_DB = -1.3
SIBILANCE_Q = 1.6
AIR_HZ = 10500.0
AIR_DB = 0.8
AIR_Q = 0.7


def clarity_config(enabled):
    if not enabled:
        return "# Clarity off\r\n"
    lines = [
        "Stage: post-mix",
        f"Preamp: {PREAMP_DB:.1f} dB",
        f"Filter: ON LS Fc {LOW_SHELF_HZ:.0f} Hz Gain {LOW_SHELF_DB:.1f} dB Q {LOW_SHELF_Q:.1f}",
        f"Filter: ON PK Fc {PRESENCE_HZ:.0f} Hz Gain {PRESENCE_DB:.1f} dB Q {PRESENCE_Q:.2f}",
        f"Filter: ON PK Fc {SIBILANCE_HZ:.0f} Hz Gain {SIBILANCE_DB:.1f} dB Q {SIBILANCE_Q:.1f}",
        f"Filter: ON HS Fc {AIR_HZ:.0f} Hz Gain {AIR_DB:.1f} dB Q {AIR_Q:.1f}",
    ]
    return "\r\n".join(lines) + "\r\n"


def _sos_from_ba(b, a):
    a0 = a[0]
    b = [v / a0 for v in b]
    a = [v / a0 for v in a]
    return [b[0], b[1], b[2], 1.0, a[1], a[2]]


def _shelf_alpha(w0, gain_db, slope):
    amp = 10.0 ** (gain_db / 40.0)
    alpha = math.sin(w0) / 2.0 * math.sqrt((amp + 1.0 / amp) * (1.0 / slope - 1.0) + 2.0)
    return amp, alpha


def _low_shelf(fs, freq, gain_db, slope):
    w0 = 2.0 * math.pi * freq / fs
    cw = math.cos(w0)
    amp, alpha = _shelf_alpha(w0, gain_db, slope)
    sa = 2.0 * math.sqrt(amp) * alpha
    b0 = amp * ((amp + 1.0) - (amp - 1.0) * cw + sa)
    b1 = 2.0 * amp * ((amp - 1.0) - (amp + 1.0) * cw)
    b2 = amp * ((amp + 1.0) - (amp - 1.0) * cw - sa)
    a0 = (amp + 1.0) + (amp - 1.0) * cw + sa
    a1 = -2.0 * ((amp - 1.0) + (amp + 1.0) * cw)
    a2 = (amp + 1.0) + (amp - 1.0) * cw - sa
    return _sos_from_ba((b0, b1, b2), (a0, a1, a2))


def _high_shelf(fs, freq, gain_db, slope):
    w0 = 2.0 * math.pi * freq / fs
    cw = math.cos(w0)
    amp, alpha = _shelf_alpha(w0, gain_db, slope)
    sa = 2.0 * math.sqrt(amp) * alpha
    b0 = amp * ((amp + 1.0) + (amp - 1.0) * cw + sa)
    b1 = -2.0 * amp * ((amp - 1.0) + (amp + 1.0) * cw)
    b2 = amp * ((amp + 1.0) + (amp - 1.0) * cw - sa)
    a0 = (amp + 1.0) - (amp - 1.0) * cw + sa
    a1 = 2.0 * ((amp - 1.0) - (amp + 1.0) * cw)
    a2 = (amp + 1.0) - (amp - 1.0) * cw - sa
    return _sos_from_ba((b0, b1, b2), (a0, a1, a2))


def _peaking(fs, freq, gain_db, q):
    w0 = 2.0 * math.pi * freq / fs
    cw = math.cos(w0)
    amp = 10.0 ** (gain_db / 40.0)
    alpha = math.sin(w0) / (2.0 * q)
    b0 = 1.0 + alpha * amp
    b1 = -2.0 * cw
    b2 = 1.0 - alpha * amp
    a0 = 1.0 + alpha / amp
    a1 = -2.0 * cw
    a2 = 1.0 - alpha / amp
    return _sos_from_ba((b0, b1, b2), (a0, a1, a2))


def _q_to_slope(q):
    return max(0.3, min(1.0, q))


class ClarityProcessor:
    def __init__(self, sample_rate):
        self.fs = int(sample_rate)
        if self.fs < 8000:
            raise ValueError("sample rate is too low")
        self.preamp = 10.0 ** (PREAMP_DB / 20.0)
        rows = [
            _low_shelf(self.fs, LOW_SHELF_HZ, LOW_SHELF_DB, _q_to_slope(LOW_SHELF_Q)),
            _peaking(self.fs, PRESENCE_HZ, PRESENCE_DB, PRESENCE_Q),
            _peaking(self.fs, SIBILANCE_HZ, SIBILANCE_DB, SIBILANCE_Q),
            _high_shelf(self.fs, min(AIR_HZ, self.fs * 0.45), AIR_DB, _q_to_slope(AIR_Q)),
        ]
        self._sos = np.asarray(rows, dtype=np.float64)
        self._ch = None
        self._zi = None

    @property
    def latency_samples(self):
        return 0

    def _ensure(self, channels):
        if self._ch == channels:
            return
        self._ch = channels
        self._zi = np.zeros((len(self._sos), 2, channels), dtype=np.float64)

    def process(self, audio, enabled=True):
        if not enabled:
            return audio
        x = np.asarray(audio, dtype=np.float64)
        squeeze = x.ndim == 1
        if squeeze:
            x = x[:, None]
        if x.ndim != 2:
            raise ValueError("audio must be (frames,) or (frames, channels)")
        self._ensure(x.shape[1])
        y, self._zi = sosfilt(self._sos, x, axis=0, zi=self._zi)
        y = y * self.preamp
        if squeeze:
            return y[:, 0]
        return y
