"""Phương án A: thanh khoản thực thi - "duyệt sổ lệnh" để ước tính chi phí khi vào/ra lệnh.

Định nghĩa (toàn bộ so với GIÁ GIỮA mid = (bid1 + ask1)/2 tại thời điểm snapshot):
    mua : trượt giá (bps) = (VWAP_khớp / mid - 1) * 1e4
    bán : trượt giá (bps) = (1 - VWAP_khớp / mid) * 1e4
Trượt giá đã bao gồm một nửa spread, nên chi phí vòng (mua rồi bán) đã chứa cả spread:
    chi phí vòng (bps) = trượt giá mua + trượt giá bán + phí mua + phí bán + thuế bán

Giả định và giới hạn (PHẢI nêu trong báo cáo):
  * Chỉ thấy 3 mức giá; lệnh lớn hơn độ sâu 3 mức bị gắn cờ `beyond`, không ngoại suy ngầm.
  * Không tính lệnh ẩn, tác động lên giá của chính lệnh, hay thay đổi sổ lệnh trong lúc khớp.
  * Vốn danh nghĩa Q quy thành số cổ phiếu theo giá tốt nhất, làm tròn xuống lô 100.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .fees import FeeSchedule
from .microstructure import mid_price, parkinson_sigma_bps, valid_quote

BID_P = ["bid1_p", "bid2_p", "bid3_p"]
BID_V = ["bid1_v", "bid2_v", "bid3_v"]
ASK_P = ["ask1_p", "ask2_p", "ask3_p"]
ASK_V = ["ask1_v", "ask2_v", "ask3_v"]


def target_shares_from_capital(capital: float, best_price, lot: int = 100) -> np.ndarray:
    bp = np.asarray(best_price, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sh = np.floor(capital / bp / lot) * lot
    return np.where(np.isfinite(sh) & (sh > 0), sh, 0.0)


def fill_shares(prices, vols, target) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Duyệt các mức giá (đã xếp từ tốt nhất đến xấu nhất) để khớp `target` cổ phiếu.

    prices, vols: mảng (n, k). target: mảng (n,).
    Trả về (số cổ phiếu khớp được, giá trị khớp, tổng độ sâu hiển thị).
    """
    P = np.nan_to_num(np.asarray(prices, dtype=float), nan=0.0)
    V = np.nan_to_num(np.asarray(vols, dtype=float), nan=0.0)
    V = np.where(P > 0, np.clip(V, 0.0, None), 0.0)
    cum = np.cumsum(V, axis=1)
    prior = cum - V
    take = np.clip(np.asarray(target, dtype=float)[:, None] - prior, 0.0, V)
    return take.sum(axis=1), (take * P).sum(axis=1), V.sum(axis=1)


def slippage_bps(side: str, vwap, mid):
    v = np.asarray(vwap, dtype=float)
    m = np.asarray(mid, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        if side == "buy":
            return (v / m - 1.0) * 1e4
        return (1.0 - v / m) * 1e4


def cost_table(df: pd.DataFrame, capital: float, lot: int, fees: FeeSchedule,
               beyond_mode: str = "flag", sqrt_y: float = 1.0,
               adv_value: pd.Series | None = None) -> pd.DataFrame:
    """Tính chi phí thực thi cho từng snapshot trong `df` (có cột bid/ask 3 mức).

    Trả về DataFrame cùng chỉ mục với các cột: mid, spread_bps, buy_*, sell_*, rt_cost_bps, beyond.
    Snapshot không có chào mua/bán hợp lệ cho kết quả NaN (không đoán).
    """
    out = pd.DataFrame(index=df.index)
    ok = valid_quote(df["bid1_p"], df["ask1_p"])
    mid = mid_price(df["bid1_p"], df["ask1_p"])
    out["mid"] = mid
    out["spread_bps"] = np.where(ok, (df["ask1_p"] - df["bid1_p"]) / mid * 1e4, np.nan)

    for side, pcols, vcols in (("buy", ASK_P, ASK_V), ("sell", BID_P, BID_V)):
        P = df[pcols].to_numpy(dtype=float)
        V = df[vcols].to_numpy(dtype=float)
        tgt = target_shares_from_capital(capital, P[:, 0], lot)
        filled, value, depth = fill_shares(P, V, tgt)
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap = np.where(filled > 0, value / filled, np.nan)
            cov = np.where(tgt > 0, depth / tgt, np.nan)
        slip = slippage_bps(side, vwap, mid)
        beyond = (tgt > 0) & (filled < tgt)
        # phần chưa khớp: đánh dấu, hoặc cộng tác động căn bậc hai nếu cấu hình yêu cầu
        extra = np.zeros(len(df))
        if beyond_mode == "sqrt_impact" and adv_value is not None and "symbol" in df.columns:
            adv = df["symbol"].map(adv_value).to_numpy(dtype=float)
            unfilled_val = (tgt - filled) * P[:, 0]
            sigma = parkinson_sigma_bps(df.get("high", np.nan), df.get("low", np.nan))
            with np.errstate(invalid="ignore", divide="ignore"):
                frac = np.where(tgt > 0, (tgt - filled) / tgt, 0.0)
                extra = sqrt_y * sigma * np.sqrt(np.clip(unfilled_val, 0, None) / adv) * frac
            extra = np.where(np.isfinite(extra), extra, 0.0)
        valid = ok & (tgt > 0) & (filled > 0)
        out[f"{side}_target"] = np.where(ok, tgt, np.nan)
        out[f"{side}_filled"] = np.where(ok, filled, np.nan)
        out[f"{side}_vwap"] = np.where(valid, vwap, np.nan)
        out[f"{side}_slip_bps"] = np.where(valid, slip + extra, np.nan)
        out[f"{side}_cov"] = np.where(ok & (tgt > 0), cov, np.nan)
        out[f"{side}_beyond"] = np.where(ok & (tgt > 0), beyond, False)

    out["beyond"] = out["buy_beyond"].astype(bool) | out["sell_beyond"].astype(bool)
    out["rt_cost_bps"] = out["buy_slip_bps"] + out["sell_slip_bps"] + fees.round_trip_bps
    return out


@dataclass
class ExecResult:
    side: str
    target_shares: int
    filled_shares: int
    vwap: float
    mid: float
    slippage_bps: float
    coverage: float          # độ sâu hiển thị / số cổ phiếu mục tiêu
    levels_used: int
    beyond_depth: bool
    status: str              # OK | PARTIAL | NO_QUOTE | TOO_SMALL


def walk_book(levels: list[tuple[float, float]], side: str, capital: float,
              mid: float, lot: int = 100) -> ExecResult:
    """Phiên bản một lệnh (dùng cho giao diện/ví dụ). `levels`: [(giá, khối lượng)] từ tốt nhất."""
    lv = [(p, v) for p, v in levels if p and p > 0 and v and v > 0]
    if not lv or not mid or mid <= 0:
        return ExecResult(side, 0, 0, float("nan"), mid or float("nan"), float("nan"),
                          float("nan"), 0, False, "NO_QUOTE")
    P = np.array([[p for p, _ in lv]], dtype=float)
    V = np.array([[v for _, v in lv]], dtype=float)
    tgt = target_shares_from_capital(capital, P[:, 0], lot)
    if tgt[0] <= 0:
        return ExecResult(side, 0, 0, float("nan"), mid, float("nan"), float("nan"), 0, False, "TOO_SMALL")
    filled, value, depth = fill_shares(P, V, tgt)
    vwap = value[0] / filled[0] if filled[0] > 0 else float("nan")
    used = int(np.sum(np.cumsum(V[0]) - V[0] < tgt[0]))
    beyond = bool(filled[0] < tgt[0])
    return ExecResult(side, int(tgt[0]), int(filled[0]), float(vwap), float(mid),
                      float(slippage_bps(side, vwap, mid)), float(depth[0] / tgt[0]),
                      used, beyond, "PARTIAL" if beyond else "OK")
