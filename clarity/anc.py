import numpy as np
from scipy.linalg import solve_toeplitz
from scipy.signal import lfilter

FS = 48000
LOW_LO = 80.0
LOW_HI = 250.0
MID_LO = 250.0
MID_HI = 600.0
LOW_PASS_DB = 12.0
MID_PASS_DB = 6.0
WORSE_LIMIT_DB = 3.0
_BANDS = ((20.0, 250.0), (250.0, 600.0))


def cabin_noise(frames, fs=FS, seed=7):
    rng = np.random.default_rng(seed)
    white = rng.normal(0.0, 1.0, frames)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(frames, 1.0 / fs)
    spec /= np.maximum(np.sqrt(freqs), 1.0)
    brown = np.fft.irfft(spec, n=frames)
    t = np.arange(frames) / fs
    hum = 0.35 * np.sin(2 * np.pi * 120 * t) + 0.2 * np.sin(2 * np.pi * 60 * t)
    rumble = 0.15 * np.sin(2 * np.pi * 18 * t)
    noise = brown + hum + rumble
    peak = np.max(np.abs(noise)) + 1e-12
    return (0.2 * noise / peak).astype(np.float64)


def _band_rms(signal, fs, lo, hi):
    spec = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(len(signal), 1.0 / fs)
    mask = (freqs >= lo) & (freqs < hi)
    if not np.any(mask):
        return 0.0
    power = np.sum(np.abs(spec[mask]) ** 2)
    return float(np.sqrt(power / max(1, np.count_nonzero(mask))))


def band_delta_db(before, after, fs, lo, hi):
    a = _band_rms(before, fs, lo, hi) + 1e-12
    b = _band_rms(after, fs, lo, hi) + 1e-12
    return float(20.0 * np.log10(a / b))


def _band_signal(sig, lo, hi, fs):
    spec = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(len(sig), 1.0 / fs)
    spec = np.where((freqs >= lo) & (freqs < hi), spec, 0)
    return np.fft.irfft(spec, n=len(sig))


def _acf(sig, maxlag):
    nfft = 1 << int(np.ceil(np.log2(max(2, 2 * len(sig)))))
    spec = np.fft.rfft(sig, n=nfft)
    return np.fft.irfft(spec * np.conj(spec), n=nfft)[: maxlag + 1]


def _design(sig, delay, taps, mu):
    n = len(sig)
    delay = max(0, int(delay))
    taps = int(taps)
    room = n - delay - 8
    if room < 8:
        return None
    taps = max(8, min(taps, room))
    ac = _acf(sig, delay + taps + 1)
    if not np.isfinite(ac[0]) or ac[0] <= 1e-18:
        return None
    step = float(mu) if mu else 0.2
    reg = min(0.05, max(1e-6, 1e-3 * (0.2 / max(step, 1e-3))))
    col = np.array(ac[:taps], dtype=np.float64, copy=True)
    col[0] += reg * ac[0]
    rhs = np.array(ac[delay : delay + taps], dtype=np.float64, copy=True)
    try:
        weights = solve_toeplitz((col, col), rhs)
    except (np.linalg.LinAlgError, ValueError):
        return None
    if not np.isfinite(weights).all():
        return None
    return np.asarray(weights, dtype=np.float64)


def _apply(sig, delay, weights):
    taps = len(weights)
    coeff = np.zeros(delay + taps, dtype=np.float64)
    coeff[delay : delay + taps] = weights
    return lfilter(coeff, [1.0], sig)


def _design_bands(sig, delay, taps, mu, fs):
    designed = []
    for lo, hi in _BANDS:
        band = _band_signal(sig, lo, hi, fs)
        weights = _design(band, delay, min(int(taps), 256), mu)
        designed.append((lo, hi, weights))
    return designed


def _sum_prediction(sig, delay, designed, fs):
    delay = max(0, int(delay))
    total = np.zeros(len(sig) + delay, dtype=np.float64)
    for lo, hi, weights in designed:
        if weights is None:
            continue
        band = _band_signal(sig, lo, hi, fs)
        extended = band if delay == 0 else np.concatenate((band, np.zeros(delay, dtype=np.float64)))
        total += _apply(extended, delay, weights)
    return total


def cancel(reference, delay_samples, taps=768, mu=0.2, fs=FS):
    signal = np.asarray(reference, dtype=np.float64).reshape(-1)
    count = len(signal)
    if count == 0 or float(np.max(np.abs(signal))) < 1e-8:
        quiet = np.zeros(count, dtype=np.float64)
        return quiet, quiet.copy()
    predicted = _sum_prediction(signal, delay_samples, _design_bands(signal, delay_samples, taps, mu, fs), fs)
    residual = np.clip(signal - predicted[:count], -1.0, 1.0)
    return residual, residual.copy()


def quality(before, after, fs=FS):
    low = band_delta_db(before, after, fs, LOW_LO, LOW_HI)
    mid = band_delta_db(before, after, fs, MID_LO, MID_HI)
    high = band_delta_db(before, after, fs, MID_HI, 2000.0)
    passed = low >= LOW_PASS_DB and mid >= MID_PASS_DB and high >= -WORSE_LIMIT_DB
    return {"low_db": low, "mid_db": mid, "high_db": high, "passed": passed}


class StreamCancel:
    def __init__(self, delay_samples, taps=128, fs=FS, mu=0.2):
        self.delay = max(0, int(delay_samples))
        self.taps = max(8, int(taps))
        self.fs = int(fs)
        self.mu = float(mu)
        self._hist = np.zeros(0, dtype=np.float64)
        self._limit = min(8192, max(2048, self.delay + self.taps + 512))
        self._since = 10**9
        self._designed = None

    def anti(self, frames):
        block = np.asarray(frames, dtype=np.float64).reshape(-1)
        if block.size == 0:
            return block
        if self._hist.size:
            self._hist = np.concatenate((self._hist, block))
        else:
            self._hist = block.copy()
        if self._hist.size > self._limit:
            self._hist = self._hist[-self._limit :].copy()
        self._since += int(block.size)
        if self._hist.size < self.delay + min(self.taps, 32) + 32:
            return np.zeros(block.size, dtype=np.float64)
        if self._designed is None or self._since >= max(self.taps, self.fs // 12):
            self._designed = _design_bands(self._hist, self.delay, self.taps, self.mu, self.fs)
            self._since = 0
        predicted = _sum_prediction(self._hist, self.delay, self._designed, self.fs)
        if self.delay <= 0:
            play = -predicted[-block.size :]
        else:
            start = len(self._hist) - block.size + self.delay
            play = -predicted[start : start + block.size]
        if play.size != block.size or not np.isfinite(play).all():
            return np.zeros(block.size, dtype=np.float64)
        return np.clip(play, -1.0, 1.0)
