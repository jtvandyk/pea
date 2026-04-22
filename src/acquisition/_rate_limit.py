"""
Shared rate-limiting utilities.

Used by the Nominatim geocoder (1 req/s policy) and the Azure extractor
(RPM ceiling). A single `SlidingWindowLimiter` instance is shared across
worker threads so every network request — initial call and retries alike —
passes through the same bookkeeping, preventing burst bypass during retry
storms.
"""

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """
    Thread-safe sliding-window rate limiter.

    Enforces at most `max_requests` calls in any `window_seconds` window.
    `acquire()` blocks when the window is full until a slot frees. The lock
    is released before sleeping so other threads can still enter `acquire()`
    concurrently — only one at a time will observe a free slot, but the
    rest queue without serialising the whole sleep.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = float(window_seconds)
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - self.window_seconds
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return
                sleep_for = self._timestamps[0] + self.window_seconds - now
            if sleep_for > 0:
                time.sleep(sleep_for)
