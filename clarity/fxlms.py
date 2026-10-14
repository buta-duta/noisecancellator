import math

import numpy as np

FADE_MS = 3.0


def accounted_delay(measured_samples):
    return max(0, int(round(float(measured_samples))))


def cancellation_limit_hz(delay_samples, sample_rate):
    delay = accounted_delay(delay_samples)
    rate = float(sample_rate)
    if delay <= 0 or rate <= 0:
        return rate / 2.0
    return rate / (4.0 * delay)


def best_delay(reference, recorded, max_delay):
    reference = np.asarray(reference, dtype=np.float64).reshape(-1)
    recorded = np.asarray(recorded, dtype=np.float64).reshape(-1)
    count = min(reference.size, recorded.size)
    limit = accounted_delay(max_delay)
    if count < 32 or limit <= 0:
        return 0, 0.0
    ref = reference[:count]
    rec = recorded[:count]
    ref = ref - float(np.mean(ref))
    rec = rec - float(np.mean(rec))
    corr = np.correlate(rec, ref, mode="full")
    center = count - 1
    window = corr[center : min(corr.size, center + limit + 1)]
    if window.size == 0:
        return 0, 0.0
    raw = int(np.argmax(np.abs(window)))
    span = 32
    start = max(0, raw - span)
    stop = min(window.size - 1, raw + span)

    def coherence_at(delay):
        aligned_ref = ref[: count - delay]
        aligned_rec = rec[delay : delay + aligned_ref.size]
        if aligned_ref.size < 32:
            return 0.0
        denom = float(np.linalg.norm(aligned_ref) * np.linalg.norm(aligned_rec)) + 1e-12
        return abs(float(np.dot(aligned_ref, aligned_rec))) / denom

    delay = raw
    coherence = -1.0
    for candidate in range(start, stop + 1):
        score = coherence_at(candidate)
        if score > coherence:
            delay = candidate
            coherence = score
    return delay, max(0.0, coherence)


def limit_line(delay_samples, sample_rate, kind):
    delay = accounted_delay(delay_samples)
    rate = float(sample_rate) if sample_rate else 0.0
    hz = cancellation_limit_hz(delay, rate)
    ms = 1000.0 * delay / rate if rate else 0.0
    return (
        f"Cancellation band: up to {hz:.0f} Hz ({kind} loop {ms:.1f} ms). "
        "This is not AirPods Pro."
    )


class FxLMS:
    """Leaky normalized FxLMS. The lowpass is minimum-phase; the secondary path is the measured delay."""

    def __init__(self, taps, delay_samples, sample_rate, mu=0.02, leak=0.9995, output_limit=0.2, max_norm=4.0):
        self.taps = max(1, int(taps))
        self.delay_samples = accounted_delay(delay_samples)
        self.sample_rate = int(sample_rate)
        if self.sample_rate < 1000:
            raise ValueError("sample rate is too low")
        self.mu = float(mu)
        self.leak = float(leak)
        self.output_limit = float(output_limit)
        self.max_norm = float(max_norm)
        self.weights = np.zeros(self.taps, dtype=np.float64)
        self.limit_hz = cancellation_limit_hz(self.delay_samples, self.sample_rate)
        cutoff = min(self.limit_hz, self.sample_rate * 0.45)
        if self.delay_samples <= 0:
            self._a = 1.0
        else:
            self._a = 1.0 - math.exp(-2.0 * math.pi * max(cutoff, 1.0) / self.sample_rate)
        self._lp = 0.0
        self._ring_len = self.taps + self.delay_samples + 1
        self._ring = np.zeros(self._ring_len, dtype=np.float64)
        self._pos = 0
        self._steps = np.arange(self.taps, dtype=np.int64)

    def reset(self):
        self.weights[:] = 0.0
        self._ring[:] = 0.0
        self._lp = 0.0
        self._pos = 0

    def step(self, reference, error):
        self._lp += self._a * (float(reference) - self._lp)
        self._ring[self._pos] = self._lp
        positions = (self._pos - self._steps) % self._ring_len
        vector = self._ring[positions]
        y = float(self.weights @ vector)
        if y > self.output_limit:
            y = self.output_limit
        elif y < -self.output_limit:
            y = -self.output_limit
        fx_pos = (self._pos - self.delay_samples) % self._ring_len
        fx = self._ring[(fx_pos - self._steps) % self._ring_len]
        energy = float(fx @ fx) + 1e-4
        self.weights *= self.leak
        self.weights -= (self.mu / energy) * float(error) * fx
        norm = float(self.weights @ self.weights)
        if norm > self.max_norm:
            self.weights *= math.sqrt(self.max_norm / norm)
        if not math.isfinite(y) or not np.isfinite(self.weights).all():
            self.weights[:] = 0.0
            y = 0.0
        self._pos += 1
        if self._pos >= self._ring_len:
            self._pos = 0
        return y


class LeakageCanceller:
    """Remove playback that leaked into the microphone. The playback itself is not replayed."""

    def __init__(self, taps=24, mu=0.08):
        self.taps = max(1, int(taps))
        self.mu = float(mu)
        self.weights = np.zeros(self.taps, dtype=np.float64)
        self._hist = np.zeros(self.taps, dtype=np.float64)

    def step(self, mic, reference):
        self._hist[1:] = self._hist[:-1]
        self._hist[0] = float(reference)
        estimate = float(self.weights @ self._hist)
        error = float(mic) - estimate
        energy = float(self._hist @ self._hist) + 1e-3
        self.weights += (self.mu / energy) * error * self._hist
        if not np.isfinite(self.weights).all():
            self.weights[:] = 0.0
            return float(mic)
        return error


class Canceller:
    def __init__(self, sample_rate, delay_samples, loop_delay=0, taps=48):
        self.sample_rate = int(sample_rate)
        self.delay_samples = accounted_delay(delay_samples)
        self.loop_delay = accounted_delay(loop_delay)
        self.limit_hz = cancellation_limit_hz(self.delay_samples, self.sample_rate)
        self.fx = FxLMS(
            taps=taps,
            delay_samples=self.delay_samples,
            sample_rate=self.sample_rate,
            mu=0.02,
            leak=0.9995,
            output_limit=0.18,
        )
        self.leakage = LeakageCanceller()
        depth = max(self.delay_samples, self.loop_delay) + 4
        self._y = np.zeros(depth, dtype=np.float64)
        self._yi = 0
        self._fade = 1.0 / max(1, int(FADE_MS * 0.001 * self.sample_rate))
        self.gain = 0.0
        self.target = 1.0
        self._err_power = 0.0
        self._out_power = 0.0

    def _past(self, delay):
        if delay <= 0 or delay >= len(self._y):
            return 0.0
        return float(self._y[(self._yi - delay) % len(self._y)])

    def _push(self, sample):
        self._y[self._yi] = sample
        self._yi = (self._yi + 1) % len(self._y)

    def process(self, mic, loopback):
        mic = np.asarray(mic, dtype=np.float64).reshape(-1)
        loopback = np.asarray(loopback, dtype=np.float64).reshape(-1)
        count = min(mic.size, loopback.size)
        out = np.zeros(count, dtype=np.float64)
        for index in range(count):
            music = float(loopback[index]) - self._past(self.loop_delay)
            residual = self.leakage.step(float(mic[index]), music)
            reference = residual - self._past(self.delay_samples)
            sample = self.fx.step(reference, residual)
            if self.target >= 0.5:
                self.gain = min(1.0, self.gain + self._fade)
            else:
                self.gain = max(0.0, self.gain - self._fade)
            sample *= self.gain
            self._err_power = 0.995 * self._err_power + 0.005 * residual * residual
            self._out_power = 0.995 * self._out_power + 0.005 * sample * sample
            if self._out_power > 0.008 and self._out_power > 3.0 * self._err_power:
                self.fx.weights *= 0.95
            self._push(sample)
            out[index] = sample
        return out
