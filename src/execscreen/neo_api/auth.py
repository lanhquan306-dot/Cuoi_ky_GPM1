"""Quản lý mã truy cập JWT. Khóa chỉ đọc từ biến môi trường, không bao giờ ghi vào mã/nhật ký."""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Callable


class MissingCredentials(RuntimeError):
    pass


def mask(secret: str) -> str:
    """Che khóa khi ghi log."""
    return "***" if not secret else f"{secret[:3]}…({len(secret)} ký tự)"


class TokenProvider:
    """Cung cấp token; nếu có `refresh_fn` thì tự làm mới khi sắp hết hạn."""

    def __init__(self, env_var: str = "NEO_ACCESS_TOKEN", refresh_fn: Callable[[], str] | None = None,
                 skew_seconds: int = 60):
        self.env_var = env_var
        self.refresh_fn = refresh_fn
        self.skew = skew_seconds
        self._token = os.environ.get(env_var, "")

    @staticmethod
    def expiry_of(token: str) -> float | None:
        """Đọc trường `exp` của JWT (không xác thực chữ ký, chỉ để biết khi nào hết hạn)."""
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except Exception:
            return None

    def get(self) -> str:
        exp = self.expiry_of(self._token) if self._token else None
        if self.refresh_fn and (not self._token or (exp and exp - time.time() < self.skew)):
            self._token = self.refresh_fn()
        if not self._token:
            raise MissingCredentials(f"Chưa có token: đặt biến môi trường {self.env_var} (xem .env.example)")
        return self._token
