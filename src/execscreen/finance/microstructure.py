"""Chỉ báo vi cấu trúc từ sổ lệnh (mọi hàm vector hóa, nhận mảng hoặc Series)."""
from __future__ import annotations

import numpy as np


def valid_quote(bid1, ask1):
    """Chào mua/bán hợp lệ: cả hai > 0 và bán > mua (sổ không bị chéo)."""
    b = np.asarray(bid1, dtype=float)
    a = np.asarray(ask1, dtype=float)
    return np.isfinite(b) & np.isfinite(a) & (b > 0) & (a > b)


def mid_price(bid1, ask1):
    b = np.asarray(bid1, dtype=float)
    a = np.asarray(ask1, dtype=float)
    return np.where(valid_quote(b, a), (b + a) / 2.0, np.nan)


def spread_bps(bid1, ask1):
    """Chênh lệch mua-bán chào tốt nhất, tính bằng bps của giá giữa."""
    b = np.asarray(bid1, dtype=float)
    a = np.asarray(ask1, dtype=float)
    m = mid_price(b, a)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (a - b) / m * 1e4


def order_book_imbalance(bid_vols, ask_vols):
    """OBI = (ΣBid - ΣAsk) / (ΣBid + ΣAsk) trên các mức đã cho. Giá trị trong [-1, 1].

    bid_vols, ask_vols: mảng (n, k). NaN coi như khối lượng 0. Tổng bằng 0 -> NaN.
    """
    b = np.nan_to_num(np.asarray(bid_vols, dtype=float), nan=0.0).sum(axis=-1)
    a = np.nan_to_num(np.asarray(ask_vols, dtype=float), nan=0.0).sum(axis=-1)
    tot = b + a
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, (b - a) / tot, np.nan)


def parkinson_sigma_bps(high, low):
    """Ước lượng biến động Parkinson từ cao/thấp: ln(H/L) / (2·sqrt(ln 2)), đơn vị bps."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.log(h / l) / (2.0 * np.sqrt(np.log(2.0))) * 1e4
    return np.where(np.isfinite(v) & (h > 0) & (l > 0) & (h >= l), v, np.nan)
