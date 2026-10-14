import threading

import numpy as np


class RingBuffer:
    def __init__(self, capacity, channels):
        self.capacity = int(capacity)
        self.channels = int(channels)
        self.buf = np.zeros((self.capacity, self.channels), dtype=np.float64)
        self.read_at = 0
        self.write_at = 0
        self.size = 0
        self.lock = threading.Lock()

    def write(self, data):
        data = np.asarray(data, dtype=np.float64)
        if data.ndim == 1:
            data = data[:, None]
        count = int(data.shape[0])
        if count <= 0:
            return
        if data.shape[1] != self.channels:
            raise ValueError("channel mismatch")
        with self.lock:
            if count >= self.capacity:
                data = data[-self.capacity :]
                count = self.capacity
                self.read_at = 0
                self.write_at = 0
                self.size = 0
            elif self.size + count > self.capacity:
                drop = self.size + count - self.capacity
                self.read_at = (self.read_at + drop) % self.capacity
                self.size -= drop
            first = min(count, self.capacity - self.write_at)
            self.buf[self.write_at : self.write_at + first] = data[:first]
            rest = count - first
            if rest:
                self.buf[:rest] = data[first:]
            self.write_at = (self.write_at + count) % self.capacity
            self.size += count

    def read(self, count):
        count = int(count)
        out = np.zeros((count, self.channels), dtype=np.float64)
        with self.lock:
            take = min(count, self.size)
            first = min(take, self.capacity - self.read_at)
            out[:first] = self.buf[self.read_at : self.read_at + first]
            rest = take - first
            if rest:
                out[first:take] = self.buf[:rest]
            self.read_at = (self.read_at + take) % self.capacity
            self.size -= take
        return out

    def available(self):
        with self.lock:
            return self.size
