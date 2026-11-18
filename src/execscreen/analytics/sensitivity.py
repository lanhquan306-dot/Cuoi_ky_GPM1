"""Độ nhạy của xếp hạng theo trọng số: nếu đổi trọng số ±rel thì thứ hạng thay đổi thế nào?

Kết quả chính: tương quan hạng Spearman với xếp hạng gốc và mức trùng top-N. Nếu thứ hạng
rất nhạy, không nên diễn giải mạnh thứ tự chính xác của các mã.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .scoring import enabled_factors, score_table


def weight_sensitivity(feats: pd.DataFrame, cfg: dict, n_draws: int = 200, rel: float = 0.3,
                       top_n: int = 5, seed: int = 42, frozen: dict | None = None) -> dict:
    base, th = score_table(feats, cfg, frozen)
    elig = base[base["eligible"]]
    if len(elig) < max(top_n, 3):
        return {"ok": False, "reason": "quá ít mã đủ điều kiện để đo độ nhạy"}
    th_frozen = frozen or {"max_cost_p90_bps": th["max_cost_p90_bps"]}   # giữ ngưỡng cố định giữa các lần chạy
    base_rank = elig["net_score"].rank(ascending=False)
    base_top = set(elig.nsmallest(top_n, "rank").index)
    rng = np.random.default_rng(seed)
    rhos, overlaps = [], []
    freq = pd.Series(0.0, index=elig.index)
    names = enabled_factors(cfg)
    for _ in range(n_draws):
        c2 = copy.deepcopy(cfg)
        for n in names:
            c2["factors"][n]["weight"] = cfg["factors"][n]["weight"] * rng.uniform(1 - rel, 1 + rel)
        t2, _ = score_table(feats, c2, th_frozen)
        e2 = t2[t2["eligible"]].reindex(elig.index)
        r2 = e2["net_score"].rank(ascending=False)
        ok = r2.notna()
        if ok.sum() >= 3:
            rhos.append(spearmanr(base_rank[ok], r2[ok]).statistic)
        top2 = set(e2.nsmallest(top_n, "rank").index) if e2["rank"].notna().any() else set()
        overlaps.append(len(base_top & top2) / top_n)
        for s in top2:
            freq[s] += 1
    return {"ok": True, "n_draws": n_draws, "rel": rel,
            "spearman_mean": float(np.nanmean(rhos)), "spearman_min": float(np.nanmin(rhos)),
            "topn_overlap_mean": float(np.mean(overlaps)),
            "topn_frequency": (freq / n_draws).sort_values(ascending=False)}
