"""DỮ LIỆU MÔ PHỎNG (không phải dữ liệu thị trường thật).

Mục đích: phát triển/kiểm thử khi chưa có khóa NEO hoặc ngoài giờ giao dịch.
Mọi dòng sinh ra có source='mock'; giao diện luôn hiển thị cảnh báo khi dữ liệu là mô phỏng.
Tuyệt đối không dùng kết quả từ dữ liệu này làm bằng chứng của báo cáo.

Mô hình: giá bước ngẫu nhiên (biến động theo tier), sổ lệnh 3 mức quanh giá giữa,
khối lượng cộng dồn theo hình chữ U, dòng tiền nước ngoài ngẫu nhiên.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from ..finance.ticks import price_limits, tick_size
from ..neo_api.models import NUMERIC_FIELDS
from ..timeutil import SessionCalendar, TZ, TZ_NAME

TIERS = {  # GTGD trung bình ngày (VND), biến động ngày, spread (số bước giá) kỳ vọng, hệ số độ sâu
    "A": dict(adv=250e9, vol=0.014, spread_ticks=1.0, depth=1.0),
    "B": dict(adv=60e9, vol=0.018, spread_ticks=1.4, depth=0.6),
    "C": dict(adv=12e9, vol=0.024, spread_ticks=2.2, depth=0.35),
}


def business_days(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _u_profile(n: int) -> np.ndarray:
    """Tỷ trọng khối lượng chữ U theo thời gian (tổng = 1)."""
    x = np.linspace(0, 1, n)
    w = 1.0 + 1.6 * (np.exp(-x / 0.12) + np.exp(-(1 - x) / 0.12))
    return w / w.sum()


def generate_mock_history(symbols: list[str], tiers: dict[str, str], days: list[date],
                          interval_s: int = 30, seed: int = 7, cal: SessionCalendar | None = None,
                          base_ref: dict[str, float] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cal = cal or SessionCalendar((9 * 3600, 9 * 3600 + 900), ((9 * 3600 + 900, 11 * 3600 + 1800),
                                                              (13 * 3600, 14 * 3600 + 1800)),
                                 (14 * 3600 + 1800, 14 * 3600 + 2700))
    frames = []
    for sym in symbols:
        t = TIERS[tiers.get(sym, "B")]
        ref = (base_ref or {}).get(sym) or float(rng.choice([12_000, 18_500, 26_300, 38_700, 54_000, 83_500, 112_000]))
        room_total = float(rng.integers(300, 900)) * 1e6
        room_cur = room_total * rng.uniform(0.2, 0.9)
        for d in days:
            floor_, ceil_ = price_limits(ref, "HOSE")
            # lưới giờ: ATO (vài mẫu), liên tục, ATC (vài mẫu)
            secs = []
            secs += list(range(cal.ato[0], cal.ato[1], max(interval_s, 300)))
            for a, b in cal.continuous:
                secs += list(range(a, b, interval_s))
            secs += list(range(cal.atc[0], cal.atc[1], max(interval_s, 300)))
            secs = np.array(secs)
            n = len(secs)
            sigma_step = t["vol"] / np.sqrt(max(n, 1))
            drift = rng.normal(0, t["vol"] * 0.3)
            rets = rng.normal(drift / n, sigma_step, n)
            mid_raw = ref * np.exp(np.cumsum(rets))
            mid_raw = np.clip(mid_raw, floor_ + 20, ceil_ - 20)
            tick = np.array([tick_size(p) for p in mid_raw], dtype=float)
            bid1 = np.floor(mid_raw / tick) * tick
            sp = 1 + rng.poisson(max(t["spread_ticks"] - 1, 0.01), n)
            ask1 = bid1 + sp * tick
            bid1 = np.clip(bid1, floor_, ceil_)
            ask1 = np.clip(ask1, floor_ + tick, ceil_)
            ask1 = np.maximum(ask1, bid1 + tick)
            last = np.where(rng.random(n) < 0.5, bid1, ask1)

            shares_day = t["adv"] / ref * rng.lognormal(0, 0.25)
            prof = _u_profile(n)
            cum_vol = np.cumsum(prof * shares_day * rng.lognormal(0, 0.15, n))
            cum_vol = np.maximum.accumulate(cum_vol)
            step_vol = np.diff(np.concatenate([[0], cum_vol]))
            cum_val = np.cumsum(step_vol * last)

            def depth(scale):
                base = shares_day * 0.0012 * t["depth"] * scale
                return np.round(rng.lognormal(np.log(base), 0.7, n) / 100) * 100

            cols = {"symbol": sym, "source": "mock"}
            df = pd.DataFrame({
                "ts": [datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(seconds=int(s)) for s in secs],
                "ref": ref, "ceiling": ceil_, "floor": floor_, "last": last,
                "cum_volume": cum_vol, "cum_value": cum_val,
            })
            df["open"] = last[0]
            df["high"] = np.maximum.accumulate(last)
            df["low"] = np.minimum.accumulate(last)
            for i in (1, 2, 3):
                df[f"bid{i}_p"] = bid1 - (i - 1) * tick
                df[f"ask{i}_p"] = ask1 + (i - 1) * tick
                df[f"bid{i}_v"] = depth(1.0 / i ** 0.3)
                df[f"ask{i}_v"] = depth(1.0 / i ** 0.3)
            # tạo áp lực mua/bán ngẫu nhiên cho tin hiệu OBI
            tilt = np.clip(rng.normal(0, 0.35, n).cumsum() * 0.05 + rng.normal(0, 0.2, n), -0.8, 0.8)
            for i in (1, 2, 3):
                df[f"bid{i}_v"] = np.round(df[f"bid{i}_v"] * (1 + tilt) / 100) * 100
                df[f"ask{i}_v"] = np.round(df[f"ask{i}_v"] * (1 - tilt) / 100) * 100
            phase = cal.phase_of_seconds(secs)
            nonc = phase != "CONTINUOUS"
            for c in [f"{s}{i}_{k}" for s in ("bid", "ask") for i in (1, 2, 3) for k in ("p", "v")]:
                df.loc[nonc, c] = np.nan  # ngoài phiên liên tục: không có sổ lệnh khớp liên tục
            fb = step_vol * last * rng.uniform(0.02, 0.12, n)
            fs = step_vol * last * rng.uniform(0.02, 0.12, n)
            df["fbuy_val"], df["fsell_val"] = np.cumsum(fb), np.cumsum(fs)
            df["fbuy_vol"], df["fsell_vol"] = df["fbuy_val"] / last, df["fsell_val"] / last
            room_path = room_cur - np.cumsum((fb - fs) / last)
            df["room_cur"], df["room_total"] = room_path, room_total
            df["symbol"], df["source"] = sym, "mock"
            df["phase"] = phase
            df["q_flags"] = np.where(nonc, "NONCONT", "")
            df["ingest_ts"] = df["ts"]
            df["trade_date"] = d.strftime("%Y-%m-%d")
            frames.append(df)
            ref = float(last[-1])          # giá tham chiếu phiên sau = giá cuối phiên này
            room_cur = float(room_path[-1])
    out = pd.concat(frames, ignore_index=True)
    out["ts"] = pd.to_datetime(out["ts"], utc=True).dt.tz_convert(TZ_NAME)
    for c in NUMERIC_FIELDS:
        if c not in out:
            out[c] = np.nan
    return out.sort_values(["ts", "symbol"]).reset_index(drop=True)
