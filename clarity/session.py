import threading

import numpy as np

from clarity.anc import StreamCancel
from clarity.fxlms import best_delay, cancellation_limit_hz
from clarity.persist import log
from clarity.report import AppIssue
from clarity.wasapi import Stream, com_enter, com_leave


class Session:
    def __init__(self):
        self.running = False
        self.delay_samples = 0
        self.loop_delay = 0
        self.sample_rate = 48000
        self.delay_kind = "structural"
        self.limit_hz = 0.0
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._stream = None
        self._output_id = ""
        self._input_id = ""

    def start(self, output_id, input_id, remembered=None):
        if not input_id:
            raise AppIssue("mic_choice")
        if not output_id:
            raise AppIssue("output_missing")
        self.stop()
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._output_id = output_id
        self._input_id = input_id
        self._remembered = remembered or {}
        self._thread = threading.Thread(target=self._run, name="clarity-cancel", daemon=True)
        self._thread.start()
        if not self._ready.wait(6.0):
            self.stop()
            raise AppIssue("device_lost")
        if self._error is not None:
            error = self._error
            self.stop()
            raise error
        self.running = True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(2.0)
        self._thread = None
        self.running = False
        self._stream = None

    def _run(self):
        owned = False
        playback = None
        mic = None
        reference = None
        try:
            owned = com_enter()
            playback = Stream(self._output_id, playback=True)
            playback.open()
            mic = Stream(self._input_id)
            mic.open()
            try:
                reference = Stream(self._output_id, loopback=True)
                reference.open()
            except Exception:
                if reference is not None:
                    reference.close()
                reference = None
            playback.start()
            mic.start()
            if reference is not None:
                reference.start()
            need = playback.render_needed()
            if need:
                playback.write(np.zeros(need, dtype=np.float32))
            mic.read()
            if reference is not None:
                reference.read()
            self.sample_rate = playback.rate
            self._arm(playback, mic, reference)
            self._ready.set()
            self._pump(playback, mic, reference)
            self._fade(playback, mic, reference)
        except Exception as exc:
            log(exc)
            self._error = exc if isinstance(exc, AppIssue) else AppIssue("device_lost", str(exc).splitlines()[0][:160])
            self._ready.set()
        finally:
            for stream in (mic, reference, playback):
                if stream is not None:
                    stream.close()
            mic = None
            reference = None
            playback = None
            com_leave(owned)

    def _remembered_delay(self, rate):
        data = self._remembered
        if data.get("output_id") != self._output_id or data.get("input_id") != self._input_id:
            return None
        if int(data.get("sample_rate") or 0) != int(rate):
            return None
        delay = data.get("delay_samples")
        if delay is None:
            return None
        return int(delay), int(data.get("loop_delay") or 0), str(data.get("delay_kind") or "structural")

    def _arm(self, playback, mic, reference):
        saved = self._remembered_delay(playback.rate)
        if saved is not None:
            delay, loop_delay, kind = saved
        else:
            delay, loop_delay, kind = self._measure(playback, mic, reference)
        horizon = int(loop_delay) if int(loop_delay) > 0 else int(delay)
        if horizon <= 0:
            horizon = max(int(playback.period_frames), 48)
        self.delay_samples = horizon
        self.loop_delay = int(loop_delay)
        self.delay_kind = kind if int(loop_delay) > 0 else "structural"
        self.limit_hz = cancellation_limit_hz(self.delay_samples, playback.rate)
        self._stream = StreamCancel(self.delay_samples, taps=128, fs=playback.rate)
        self._mic_q = np.zeros(0, dtype=np.float32)

    def _measure(self, playback, mic, reference):
        rate = playback.rate
        count = int(rate * 0.2)
        rng = np.random.default_rng(11)
        probe = (rng.uniform(-1.0, 1.0, count) * 0.03).astype(np.float32)
        sent = []
        heard = []
        looped = []
        written = 0
        while written < count and not self._stop.is_set():
            playback.wait(80)
            need = playback.render_needed()
            if need <= 0:
                continue
            block = np.zeros(need, dtype=np.float32)
            take = min(need, count - written)
            block[:take] = probe[written : written + take]
            playback.write(block)
            sent.append(block[:take].copy())
            written += take
            heard.append(self._match(mic.read(), mic.rate, rate))
            if reference is not None:
                looped.append(self._match(reference.read(), reference.rate, rate))
        playback.wait(40)
        heard.append(self._match(mic.read(), mic.rate, rate))
        if reference is not None:
            looped.append(self._match(reference.read(), reference.rate, rate))
        sent_audio = np.concatenate(sent) if sent else np.zeros(1, dtype=np.float32)
        mic_audio = np.concatenate([part for part in heard if part.size]) if heard else np.zeros(1, dtype=np.float32)
        loop_audio = np.concatenate([part for part in looped if part.size]) if looped else np.zeros(1, dtype=np.float32)
        structural = int(playback.period_frames + mic.period_frames)
        loop_delay, loop_coh = best_delay(sent_audio, loop_audio, rate // 5)
        if loop_coh < 0.8:
            loop_delay = min(structural, max(playback.period_frames, 1))
        else:
            structural = max(structural, int(loop_delay))
        mic_delay, mic_coh = best_delay(sent_audio, mic_audio, int(rate * 0.12))
        if mic_coh >= 0.45 and 0 < mic_delay < int(rate * 0.12):
            return mic_delay, loop_delay, "measured"
        return structural, loop_delay, "structural"

    def _match(self, chunk, src_rate, dst_rate):
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if chunk.size == 0 or src_rate == dst_rate:
            return chunk
        dest = max(1, int(round(chunk.size * float(dst_rate) / float(src_rate))))
        return np.interp(np.linspace(0, chunk.size - 1, dest), np.arange(chunk.size), chunk).astype(np.float32)

    def _take(self, queue, count, limit):
        if queue.size > limit:
            queue = queue[-limit:]
        if queue.size < count:
            return None, queue
        return queue[:count], queue[count:]

    def _pump(self, playback, mic, reference):
        limit = max(playback.period_frames * 3, 256)
        while not self._stop.is_set():
            playback.wait(50)
            self._mic_q = np.concatenate([self._mic_q, self._match(mic.read(), mic.rate, playback.rate)])
            if reference is not None:
                reference.read()
            need = playback.render_needed()
            if need <= 0:
                continue
            block_mic, self._mic_q = self._take(self._mic_q, need, limit)
            if block_mic is None or self._stream is None:
                playback.write(np.zeros(need, dtype=np.float32))
                continue
            anti = self._stream.anti(block_mic).astype(np.float32)
            if anti.size < need:
                anti = np.pad(anti, (0, need - anti.size))
            playback.write(anti[:need])

    def _fade(self, playback, mic, reference):
        frames = max(1, int(0.02 * playback.rate))
        left = frames
        while left > 0:
            playback.wait(30)
            need = playback.render_needed()
            if need <= 0:
                continue
            take = min(need, left)
            playback.write(np.zeros(need, dtype=np.float32))
            mic.read()
            if reference is not None:
                reference.read()
            left -= take
