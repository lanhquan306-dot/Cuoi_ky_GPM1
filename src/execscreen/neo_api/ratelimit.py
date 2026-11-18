"""Giới hạn tần suất kiểu token bucket (NEO API: 5 yêu cầu/giây cho mỗi máy khách)."""
from __future__ import annotations

import asyncio
import time
from typing import Callable


class TokenBucket:
    _EPS = 1e-9   # dung sai số thực, tránh vòng lặp vô hạn khi thiếu token ~1e-16

    def __init__(self, rate: float = 5.0, capacity: float | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate = float(rate)
        self.capacity = float(capacity if capacity is not None else rate)
        self._tokens = self.capacity
        self._clock, self._sleep = clock, sleep
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def acquire(self, n: float = 1.0) -> float:
        """Chặn đến khi đủ token. Trả về thời gian đã chờ (giây)."""
        waited = 0.0
        self._refill()
        while self._tokens < n - self._EPS:
            need = (n - self._tokens) / self.rate
            self._sleep(need)
            waited += need
            self._refill()
        self._tokens = max(0.0, self._tokens - n)
        return waited

    async def acquire_async(self, n: float = 1.0) -> None:
        self._refill()
        while self._tokens < n - self._EPS:
            await asyncio.sleep((n - self._tokens) / self.rate)
            self._refill()
        self._tokens = max(0.0, self._tokens - n)
