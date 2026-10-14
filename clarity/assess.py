import os
import tempfile

import numpy as np

from clarity.anc import (
    FS,
    LOW_PASS_DB,
    MID_PASS_DB,
    WORSE_LIMIT_DB,
    cabin_noise,
    cancel,
    quality,
)
from clarity.devices import classify_name, init_com, render_devices
from clarity.fxlms import best_delay
from clarity.wasapi import Stream, com_enter, com_leave


def report_path():
    folder = os.environ.get("TEMP") or tempfile.gettempdir()
    return os.path.join(folder, "clarity-assess.txt")


def _headphones():
    init_com()
    phones = []
    for device in render_devices():
        name = device.FriendlyName or ""
        if classify_name(name) == "phones":
            phones.append(device)
    for device in phones:
        if "realtek" in (device.FriendlyName or "").casefold():
            return device
    return phones[0] if phones else None


def _resample(samples, src_rate, dst_rate):
    if int(src_rate) == int(dst_rate) or len(samples) == 0:
        return np.asarray(samples, dtype=np.float64)
    from math import gcd

    from scipy.signal import resample_poly

    src = int(src_rate)
    dst = int(dst_rate)
    factor = gcd(src, dst)
    return resample_poly(np.asarray(samples, dtype=np.float64), dst // factor, src // factor)


def _play_capture(device_id, samples):
    owned = com_enter()
    playback = Stream(device_id, playback=True)
    loop = Stream(device_id, loopback=True)
    try:
        playback.open()
        loop.open()
        playback.start()
        loop.start()
        audio = _resample(samples, FS, playback.rate).astype(np.float32)
        prime = playback.render_needed()
        if prime:
            playback.write(np.zeros(prime, dtype=np.float32))
        loop.read()
        written = 0
        captured = []
        while written < audio.size:
            playback.wait(120)
            need = playback.render_needed()
            if need <= 0:
                continue
            take = min(need, int(audio.size - written))
            block = np.zeros(need, dtype=np.float32)
            block[:take] = audio[written : written + take]
            playback.write(block)
            written += take
            captured.append(loop.read())
        for _ in range(12):
            playback.wait(40)
            need = playback.render_needed()
            if need:
                playback.write(np.zeros(need, dtype=np.float32))
            captured.append(loop.read())
        parts = [part for part in captured if getattr(part, "size", 0)]
        heard = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return int(playback.rate), np.asarray(heard, dtype=np.float64)
    finally:
        loop.close()
        playback.close()
        com_leave(owned)


def _score_capture(noise, sent, captured, rate):
    blank = {"low_db": 0.0, "mid_db": 0.0, "high_db": 0.0, "passed": False}
    if captured.size < 64:
        return blank, 0, 0.0
    played = _resample(sent, FS, rate)
    source = _resample(noise, FS, rate)
    lag, coherence = best_delay(played, captured, max(1, int(rate) // 2))
    if lag >= captured.size:
        return blank, lag, coherence
    count = min(source.size, captured.size - lag)
    trim = 4000 if count > 12000 else max(0, count // 10)
    if count - (2 * trim) < 1000:
        trim = 0
    stop = count - trim if trim else count
    before = source[trim:stop]
    after = captured[lag + trim : lag + stop]
    if before.size < 1000 or after.size < 1000:
        return blank, lag, coherence
    return quality(_resample(before, rate, FS), _resample(after, rate, FS), FS), lag, coherence


def _line(key, value):
    if isinstance(value, float):
        return f"{key}={value:.2f}"
    return f"{key}={value}"


def main():
    lines = [
        f"thresholds low>={LOW_PASS_DB:.0f} mid>={MID_PASS_DB:.0f} high>={-WORSE_LIMIT_DB:.0f}",
    ]
    device = _headphones()
    if device is None:
        lines.append("device=missing")
        lines.append("result=FAIL")
        _write(lines)
        return 1
    name = device.FriendlyName or "headphones"
    lines.append(f"device={name}")
    noise = cabin_noise(FS * 2, fs=FS)
    sent, _residual = cancel(noise, delay_samples=48)
    digital = quality(noise[4000:-4000], sent[4000:-4000], FS)
    lines.append(_line("digital_low_db", digital["low_db"]))
    lines.append(_line("digital_mid_db", digital["mid_db"]))
    lines.append(_line("digital_high_db", digital["high_db"]))
    lines.append(f"digital_passed={'yes' if digital['passed'] else 'no'}")
    try:
        rate, captured = _play_capture(device.id, sent)
    except Exception as exc:
        lines.append(f"loopback_error={type(exc).__name__}: {exc}".splitlines()[0][:180])
        lines.append("result=FAIL")
        _write(lines)
        return 1
    score, lag, coherence = _score_capture(noise, sent, captured, rate)
    lines.append(_line("loopback_low_db", score["low_db"]))
    lines.append(_line("loopback_mid_db", score["mid_db"]))
    lines.append(_line("loopback_high_db", score["high_db"]))
    lines.append(f"loopback_lag_samples={lag}")
    lines.append(_line("loopback_coherence", coherence))
    lines.append(f"loopback_passed={'yes' if score['passed'] else 'no'}")
    audible = coherence >= 0.35 and float(np.max(np.abs(captured))) > 1e-4
    lines.append(f"loopback_audible={'yes' if audible else 'no'}")
    passed = bool(digital["passed"] and score["passed"] and audible)
    lines.append(f"result={'PASS' if passed else 'FAIL'}")
    _write(lines)
    return 0 if passed else 1


def _write(lines):
    path = report_path()
    text = "\r\n".join(lines) + "\r\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text, end="")
    print(path)


if __name__ == "__main__":
    raise SystemExit(main())
