"""Chuẩn hóa chéo mã (cross-section) cho các yếu tố."""
from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize(s: pd.Series, lo: float = 0.02, hi: float = 0.98) -> pd.Series:
    x = s.astype(float)
    if x.notna().sum() < 3:
        return x
    a, b = x.quantile(lo), x.quantile(hi)
    return x.clip(a, b)


def zscore(s: pd.Series) -> pd.Series:
    x = s.astype(float)
    sd = x.std(ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return x.where(x.isna(), 0.0)
    return (x - x.mean()) / sd


def rank_pct(s: pd.Series) -> pd.Series:
    """Hạng phần trăm trong [0, 1]; NaN giữ nguyên."""
    x = s.astype(float)
    n = x.notna().sum()
    if n <= 1:
        return x.where(x.isna(), 0.5)
    return (x.rank(method="average") - 1) / (n - 1)


def normalize(s: pd.Series, method: str = "zscore", winsor: tuple[float, float] = (0.02, 0.98)) -> pd.Series:
    if method == "rank":
        return (rank_pct(s) - 0.5) * 2.0          # quy về [-1, 1]
    return zscore(winsorize(s, *winsor))
