"""Xếp hạng: bộ lọc cứng -> điểm yếu tố tổng hợp -> điểm ròng sau chi phí thực thi.

  điểm yếu tố  = Σ w_i · z_i / Σ w_i  (chỉ trên các yếu tố có dữ liệu của mã đó; trọng số chuẩn hóa lại)
  điểm ròng    = z(điểm yếu tố) - λ · z(chi phí vòng P90)      [z tính trên tập mã đủ điều kiện]

Trọng số mặc định là tiên nghiệm (gần bằng nhau), KHÔNG tối ưu trên dữ liệu. Độ nhạy: sensitivity.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .normalize import normalize, rank_pct, zscore

GATE_LABELS = {
    "NO_QUOTE": "thiếu chào mua/bán hợp lệ hoặc quá ít snapshot",
    "LIMIT_LOCKED": "khóa trần/sàn",
    "STALE": "dữ liệu cũ",
    "PARTICIPATION": "vốn vượt ngưỡng % GTGD trung bình ngày",
    "ADV_LOW": "GTGD trung bình thấp hơn mức tối thiểu",
    "COST_HIGH": "chi phí vòng P90 vượt ngưỡng",
    "BEYOND_DEPTH": "lệnh thường vượt độ sâu 3 mức",
    "FEW_FACTORS": "không đủ yếu tố có dữ liệu",
}


def enabled_factors(cfg: dict) -> list[str]:
    return [k for k, v in cfg["factors"].items() if v.get("enabled", False)]


def resolve_thresholds(cfg: dict, feats: pd.DataFrame, frozen: dict | None = None) -> dict:
    """Ngưỡng bộ lọc. `frozen` (từ phiên hiệu chỉnh) ưu tiên hơn ngưỡng tính từ lát cắt hiện tại."""
    g = cfg["gates"]
    th: dict = {"source": "frozen" if frozen else "cross_section"}
    spec = g.get("max_cost_p90_bps", {})
    if frozen and "max_cost_p90_bps" in frozen:
        th["max_cost_p90_bps"] = frozen["max_cost_p90_bps"]
    elif spec.get("mode") == "fixed":
        th["max_cost_p90_bps"] = float(spec["value"])
    else:
        x = feats.loc[feats["quote_ok"], "cost_p90_bps"].dropna() if "quote_ok" in feats else pd.Series(dtype=float)
        th["max_cost_p90_bps"] = float(x.quantile(float(spec.get("q", 0.8)))) if len(x) else float("inf")
    return th


def apply_gates(feats: pd.DataFrame, cfg: dict, th: dict) -> pd.DataFrame:
    g = cfg["gates"]
    reasons = pd.Series("", index=feats.index, dtype=object)

    def add(mask: pd.Series, code: str):
        m = mask.fillna(False).astype(bool)
        if m.any():
            cur = reasons.loc[m]
            reasons.loc[m] = np.where(cur == "", code, cur + "," + code)

    if g.get("require_quote", True):
        add(~feats["quote_ok"], "NO_QUOTE")
    if g.get("exclude_limit_locked", True):
        add(feats["limit_locked"], "LIMIT_LOCKED")
    if g.get("exclude_stale", True):
        add(feats["stale"], "STALE")
    if g.get("max_participation") is not None:
        add(feats["participation"] > float(g["max_participation"]), "PARTICIPATION")
    if g.get("min_adv_vnd"):
        add(feats["adv_value"] < float(g["min_adv_vnd"]), "ADV_LOW")
    add(feats["cost_p90_bps"] > th["max_cost_p90_bps"], "COST_HIGH")
    if g.get("max_beyond_depth_share") is not None:
        add(feats["beyond_share"] > float(g["max_beyond_depth_share"]), "BEYOND_DEPTH")
    out = feats.copy()
    out["gate_reasons"] = reasons
    out["eligible_gate"] = reasons == ""
    return out


def composite_scores(feats: pd.DataFrame, cfg: dict) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    """Trả về (điểm tổng hợp, đóng góp từng yếu tố, số yếu tố dùng)."""
    sc = cfg["scoring"]
    names = enabled_factors(cfg)
    z = pd.DataFrame(index=feats.index)
    w = {}
    for n in names:
        if n not in feats:
            continue
        spec = cfg["factors"][n]
        z[n] = normalize(feats[n], sc.get("normalization", "zscore"),
                         tuple(sc.get("winsor", (0.02, 0.98)))) * float(spec.get("direction", 1))
        w[n] = float(spec.get("weight", 1.0))
    if z.empty:
        return pd.Series(np.nan, index=feats.index), pd.DataFrame(index=feats.index), pd.Series(0, index=feats.index)
    W = pd.DataFrame({n: np.where(z[n].notna(), w[n], 0.0) for n in z.columns}, index=z.index)
    wsum = W.sum(axis=1)
    contrib = (z.fillna(0.0) * W).div(wsum.replace(0, np.nan), axis=0)
    comp = contrib.sum(axis=1, min_count=1)
    n_used = z.notna().sum(axis=1)
    comp = comp.where(n_used >= int(sc.get("min_factors_available", 2)))
    contrib.columns = [f"contrib_{c}" for c in contrib.columns]
    return comp, contrib, n_used


def score_table(feats: pd.DataFrame, cfg: dict, frozen: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Bảng xếp hạng đầy đủ + ngưỡng đã dùng. Mã không đủ điều kiện có rank = NaN và nêu lý do."""
    if feats.empty:
        return feats, {}
    th = resolve_thresholds(cfg, feats, frozen)
    t = apply_gates(feats, cfg, th)
    comp, contrib, n_used = composite_scores(t, cfg)
    t["comp_score"], t["n_factors"] = comp, n_used
    t = pd.concat([t, contrib], axis=1)
    few = t["comp_score"].isna()
    t.loc[few & (t["gate_reasons"] == ""), "gate_reasons"] = "FEW_FACTORS"
    t["eligible"] = t["gate_reasons"] == ""

    lam = float(cfg["scoring"].get("cost_penalty_lambda", 0.0))
    e = t["eligible"]
    t["net_score"], t["score_0_100"], t["rank"] = np.nan, np.nan, np.nan
    if e.any():
        cz = zscore(t.loc[e, "cost_p90_bps"])
        sz = zscore(t.loc[e, "comp_score"])
        t.loc[e, "net_score"] = sz - lam * cz
        t.loc[e, "score_0_100"] = rank_pct(t.loc[e, "net_score"]) * 100.0
        t.loc[e, "rank"] = t.loc[e, "net_score"].rank(ascending=False, method="first")
    t = t.sort_values(["rank", "gate_reasons"], na_position="last")
    return t, th


def explain_row(row: pd.Series, cfg: dict) -> str:
    """Giải thích xác định (không dùng AI): tóm tắt đóng góp, chi phí, cờ."""
    if not bool(row.get("eligible", False)):
        codes = [c for c in str(row.get("gate_reasons", "")).split(",") if c]
        return "Bị loại: " + "; ".join(GATE_LABELS.get(c, c) for c in codes) if codes else "Chưa đủ dữ liệu."
    parts = {c[len("contrib_"):]: row[c] for c in row.index if c.startswith("contrib_") and pd.notna(row[c])}
    ranked = sorted(parts.items(), key=lambda kv: kv[1], reverse=True)
    pos = [f"{k} ({v:+.2f})" for k, v in ranked[:2] if v > 0]
    neg = [f"{k} ({v:+.2f})" for k, v in ranked[::-1][:1] if v < 0]
    s = f"Hạng {int(row['rank'])}. "
    if pos:
        s += "Điểm cộng chính: " + ", ".join(pos) + ". "
    if neg:
        s += "Kéo điểm xuống: " + ", ".join(neg) + ". "
    s += (f"Chi phí vòng ước tính P50/P90 = {row['cost_p50_bps']:.0f}/{row['cost_p90_bps']:.0f} bps; "
          f"độ phủ sổ lệnh (trung vị) = {row['coverage_med']:.1f} lần vốn; "
          f"{row['beyond_share'] * 100:.0f}% snapshot vượt độ sâu 3 mức.")
    return s
