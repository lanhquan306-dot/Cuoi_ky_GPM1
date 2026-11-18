import copy

import numpy as np
import pandas as pd
import pytest

from execscreen.analytics.features import compute_features
from execscreen.analytics.normalize import normalize, rank_pct, winsorize, zscore
from execscreen.analytics.pipeline import calibrate_thresholds, decision_timestamp, run_screen
from execscreen.analytics.scoring import explain_row, score_table
from execscreen.analytics.sensitivity import weight_sensitivity


def test_normalize():
    z = zscore(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert z.mean() == pytest.approx(0) and z.std(ddof=0) == pytest.approx(1)
    assert (zscore(pd.Series([5.0, 5.0, 5.0])) == 0).all()
    w = winsorize(pd.Series(list(range(100)) + [10_000]), 0.0, 0.95)
    assert w.max() < 10_000
    assert rank_pct(pd.Series([10, 20, 30])).tolist() == [0.0, 0.5, 1.0]
    assert np.isnan(zscore(pd.Series([1.0, np.nan, 3.0])).iloc[1])
    assert normalize(pd.Series([1, 2, 3]), "rank").tolist() == [-1.0, 0.0, 1.0]


def _feats(n=8, seed=0):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame(index=[f"S{i}" for i in range(n)])
    f["mom_ref"] = rng.normal(0, 0.01, n)
    f["range_pos"] = rng.uniform(0, 1, n)
    f["rvol_tod"] = rng.uniform(0.5, 2, n)
    f["obi3"] = rng.uniform(-0.5, 0.5, n)
    f["range_pct"] = rng.uniform(0.005, 0.03, n)
    f["foreign_net"] = np.nan
    f["cost_p50_bps"] = rng.uniform(40, 80, n)
    f["cost_p90_bps"] = f["cost_p50_bps"] + 10
    f["coverage_med"] = 3.0
    f["beyond_share"] = 0.0
    f["participation"] = 0.001
    f["adv_value"] = 1e11
    f["quote_ok"], f["limit_locked"], f["stale"] = True, False, False
    return f


def test_gates_and_reasons(cfg):
    f = _feats()
    f.loc["S0", "quote_ok"] = False
    f.loc["S1", "limit_locked"] = True
    f.loc["S2", "stale"] = True
    f.loc["S3", "participation"] = 0.5
    f.loc["S4", "beyond_share"] = 0.9
    t, th = score_table(f, cfg)
    assert "NO_QUOTE" in t.loc["S0", "gate_reasons"]
    assert "LIMIT_LOCKED" in t.loc["S1", "gate_reasons"]
    assert "STALE" in t.loc["S2", "gate_reasons"]
    assert "PARTICIPATION" in t.loc["S3", "gate_reasons"]
    assert "BEYOND_DEPTH" in t.loc["S4", "gate_reasons"]
    assert t.loc[["S0", "S1", "S2", "S3", "S4"], "eligible"].sum() == 0
    assert t["rank"].dropna().is_unique


def test_missing_factor_renormalizes_and_contributions_sum_to_score(cfg):
    f = _feats()
    f.loc["S5", "rvol_tod"] = np.nan          # thiếu một yếu tố
    t, _ = score_table(f, cfg)
    row = t.loc["S5"]
    assert pd.notna(row["comp_score"])        # vẫn chấm được bằng các yếu tố còn lại
    contribs = [c for c in t.columns if c.startswith("contrib_")]
    assert t[contribs].sum(axis=1, min_count=1).sub(t["comp_score"]).abs().max() < 1e-9
    assert row["n_factors"] == t["n_factors"].max() - 1


def test_too_few_factors_excluded(cfg):
    f = _feats()
    f.loc["S6", ["mom_ref", "range_pos", "rvol_tod", "obi3"]] = np.nan   # chỉ còn range_pct
    t, _ = score_table(f, cfg)
    assert "FEW_FACTORS" in t.loc["S6", "gate_reasons"]


def test_cost_penalty_changes_ranking(cfg):
    f = _feats()
    f["cost_p90_bps"] = 50.0
    f.loc["S0", ["mom_ref", "range_pos", "rvol_tod", "obi3", "range_pct"]] = [0.05, 1, 3, 0.5, 0.03]  # điểm cao nhất
    f.loc["S0", "cost_p90_bps"] = 400.0                                                                 # nhưng rất đắt
    c0, c3 = copy.deepcopy(cfg), copy.deepcopy(cfg)
    c0["scoring"]["cost_penalty_lambda"], c3["scoring"]["cost_penalty_lambda"] = 0.0, 3.0
    c0["gates"]["max_cost_p90_bps"] = c3["gates"]["max_cost_p90_bps"] = {"mode": "fixed", "value": 1000}
    r0, _ = score_table(f, c0)
    r3, _ = score_table(f, c3)
    assert r0.loc["S0", "rank"] == 1
    assert r3.loc["S0", "rank"] > 1


def test_frozen_threshold_is_used(cfg):
    f = _feats()
    t, th = score_table(f, cfg, frozen={"max_cost_p90_bps": 0.0})
    assert th["source"] == "frozen" and not t["eligible"].any()


def test_explain_row_is_deterministic_text(cfg):
    t, _ = score_table(_feats(), cfg)
    top = t.iloc[0]
    assert "Hạng 1" in explain_row(top, cfg)
    bad = t.iloc[0].copy()
    bad["eligible"], bad["gate_reasons"] = False, "STALE"
    assert "dữ liệu cũ" in explain_row(bad, cfg)


def test_pipeline_on_mock_end_to_end(mock_df, cfg):
    days = sorted(mock_df["trade_date"].unique())
    ranked, th = run_screen(mock_df, decision_timestamp(days[-1], "10:00"), cfg)
    assert len(ranked) == mock_df["symbol"].nunique()
    assert ranked["eligible"].sum() >= 1
    assert ranked["rvol_tod"].notna().any()          # đã có đủ phiên trước để tính RVOL
    r = ranked["rank"].dropna()
    assert sorted(r.tolist()) == list(range(1, len(r) + 1))


def test_no_lookahead(mock_df, cfg):
    """Thêm dữ liệu tương lai (ts > as_of) không được làm đổi kết quả tại as_of."""
    days = sorted(mock_df["trade_date"].unique())
    t = decision_timestamp(days[-2], "10:30")
    f_full = compute_features(mock_df, t, cfg)
    f_cut = compute_features(mock_df[mock_df["ts"] <= t], t, cfg)
    pd.testing.assert_frame_equal(f_full.sort_index(), f_cut.sort_index())
    # kể cả khi dữ liệu tương lai bị thay bằng giá trị cực đoan
    poisoned = mock_df.copy()
    fut = poisoned["ts"] > t
    poisoned.loc[fut, ["last", "cum_volume", "bid1_v", "ask1_v"]] = 1e12
    pd.testing.assert_frame_equal(f_full.sort_index(), compute_features(poisoned, t, cfg).sort_index())


def test_rvol_needs_min_sessions(mock_df, cfg):
    days = sorted(mock_df["trade_date"].unique())
    f = compute_features(mock_df, decision_timestamp(days[1], "10:00"), cfg)   # chỉ có 1 phiên trước
    assert f["rvol_tod"].isna().all()


def test_calibration_uses_only_calibration_sessions(mock_df, cfg):
    days = sorted(mock_df["trade_date"].unique())
    th = calibrate_thresholds(mock_df, cfg, days[:3])
    assert th["calibrated_on"] == days[:3] and th["max_cost_p90_bps"] > 0
    poisoned = mock_df.copy()
    poisoned.loc[poisoned["trade_date"] > days[2], ["ask1_p", "bid1_p"]] = np.nan
    assert calibrate_thresholds(poisoned, cfg, days[:3])["max_cost_p90_bps"] == th["max_cost_p90_bps"]


def test_sensitivity(mock_df, cfg):
    days = sorted(mock_df["trade_date"].unique())
    f = compute_features(mock_df, decision_timestamp(days[-1], "10:00"), cfg)
    out = weight_sensitivity(f, cfg, n_draws=30, top_n=3)
    assert out["ok"] and -1 <= out["spearman_mean"] <= 1 and 0 <= out["topn_overlap_mean"] <= 1
