"""Điều phối: dữ liệu snapshot -> yếu tố/chi phí -> xếp hạng; hiệu chỉnh ngưỡng từ các phiên đầu."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..timeutil import TZ_NAME, SessionCalendar
from .features import compute_features
from .scoring import score_table


def run_screen(snaps: pd.DataFrame, as_of, cfg: dict, capital: float | None = None,
               frozen: dict | None = None) -> tuple[pd.DataFrame, dict]:
    feats = compute_features(snaps, as_of, cfg, capital)
    if feats.empty:
        return feats, {}
    return score_table(feats, cfg, frozen)


def decision_timestamp(date_str: str, hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{date_str} {hhmm}:00", tz=TZ_NAME)


def calibrate_thresholds(snaps: pd.DataFrame, cfg: dict, calib_dates: list[str],
                         capital: float | None = None) -> dict:
    """Cố định ngưỡng chi phí từ các phiên hiệu chỉnh (chỉ dùng dữ liệu của các phiên đó).

    Các phiên sau đó (phiên kiểm tra) dùng đúng ngưỡng này -> không rò rỉ thông tin từ tương lai.
    """
    ft, g = cfg["forward_test"], cfg["gates"]["max_cost_p90_bps"]
    pool = []
    for d in calib_dates:
        t = decision_timestamp(d, ft["decision_time"])
        f = compute_features(snaps[snaps["trade_date"] <= d], t, cfg, capital)
        if not f.empty:
            pool.append(f.loc[f["quote_ok"], "cost_p90_bps"].dropna())
    if not pool:
        return {}
    x = pd.concat(pool)
    if g.get("mode") == "fixed":
        v = float(g["value"])
    else:
        v = float(x.quantile(float(g.get("q", 0.8))))
    return {"max_cost_p90_bps": v, "calibrated_on": list(calib_dates), "n_obs": int(len(x))}
