"""Client REST NEO: giới hạn 5 yêu cầu/giây, thử lại có lùi, ghi log lỗi rõ ràng.

TRẠNG THÁI: chưa kiểm thử với máy chủ thật. Đường dẫn endpoint điền ở config/neo_connection.yaml.
REST chỉ dùng cho dữ liệu tham chiếu đầu ngày và đối chiếu cuối ngày, KHÔNG dùng để hỏi liên tục.
"""
from __future__ import annotations

import logging
import time

import requests

from .auth import TokenProvider
from .ratelimit import TokenBucket

log = logging.getLogger("execscreen.neo.rest")


class NeoApiError(RuntimeError):
    pass


class NeoRestClient:
    def __init__(self, base_url: str, token: TokenProvider, rate: float = 5.0, retries: int = 3,
                 session: requests.Session | None = None, limiter: TokenBucket | None = None,
                 timeout: float = 10.0):
        self.base = base_url.rstrip("/")
        self.token, self.retries, self.timeout = token, retries, timeout
        self.session = session or requests.Session()
        self.limiter = limiter or TokenBucket(rate)

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        last_err = None
        for attempt in range(1, self.retries + 1):
            self.limiter.acquire()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout,
                                     headers={"Authorization": f"Bearer {self.token.get()}"})
            except requests.RequestException as e:
                last_err = e
                log.warning("Lỗi mạng lần %d/%d: %s", attempt, self.retries, type(e).__name__)
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = NeoApiError(f"HTTP {r.status_code}")
                    log.warning("HTTP %s lần %d/%d (sẽ thử lại)", r.status_code, attempt, self.retries)
                else:  # 4xx khác: lỗi xác thực/tham số, thử lại không giúp ích
                    raise NeoApiError(f"HTTP {r.status_code} tại {path}: {r.text[:200]}")
            time.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)))
        raise NeoApiError(f"Hết số lần thử cho {path}: {last_err!r}")
