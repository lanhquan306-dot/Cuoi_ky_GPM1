"""Bước giá, lô giao dịch, biên độ giá. Giá tính bằng VND (không phải nghìn đồng).

KIỂM TRA LẠI với quy định hiện hành của sở giao dịch trước khi nộp bài.
"""
from __future__ import annotations

import math

PRICE_BAND = {"HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}


def tick_size(price: float, exchange: str = "HOSE", instrument: str = "STOCK") -> int:
    ex = exchange.upper()
    if ex == "HOSE":
        if instrument.upper() == "ETF":
            return 10
        if price < 10_000:
            return 10
        if price < 50_000:
            return 50
        return 100
    return 100  # HNX, UPCoM


def round_to_tick(price: float, exchange: str = "HOSE", direction: str = "nearest") -> float:
    t = tick_size(price, exchange)
    q = price / t
    if direction == "down":
        return math.floor(q + 1e-9) * t
    if direction == "up":
        return math.ceil(q - 1e-9) * t
    return round(q) * t


def price_limits(ref: float, exchange: str = "HOSE") -> tuple[float, float]:
    """Trả về (sàn, trần): trần làm tròn xuống, sàn làm tròn lên theo bước giá."""
    band = PRICE_BAND.get(exchange.upper(), 0.07)
    ceiling = round_to_tick(ref * (1 + band), exchange, "down")
    floor = round_to_tick(ref * (1 - band), exchange, "up")
    return floor, ceiling


def round_lot(shares: float, lot: int = 100) -> int:
    return int(math.floor(shares / lot) * lot)
