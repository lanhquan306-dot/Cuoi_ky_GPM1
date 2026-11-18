import sqlite3

import numpy as np
import pandas as pd
import pytest

from execscreen.analytics.forward_test import (PicksAlreadyFrozen, bootstrap_ci, evaluate_run, freeze_picks,
                                               load_picks, random_baseline, simulate_trade, summarize_runs)
from execscreen.analytics.pipeline import decision_timestamp, run_screen
from execscreen.finance.fees import FeeSchedule
from execscreen.timeutil import TZ_NAME


def _snap(ts, bid, ask):
    t = pd.Timestamp(ts, tz=TZ_NAME)
    return {"ts": t, "trade_date": t.strftime("%Y-%m-%d"), "phase": "CONTINUOUS",
            "bid1_p": bid, "bid1_v": 5000, "bid2_p": bid - 100, "bid2_v": 5000, "bid3_p": bid - 200, "bid3_v": 5000,
            "ask1_p": ask, "ask1_v": 5000, "ask2_p": ask + 100, "ask2_v": 5000, "ask3_p": ask + 200, "ask3_v": 5000}


def test_simulate_trade_hand_calc():
    df = pd.DataFrame([_snap("2026-11-16 10:01:00", 49_900, 50_000), _snap("2026-11-17 10:01:00", 51_000, 51_100)])
    r = simulate_trade(df, pd.Timestamp("2026-11-16 10:01:00", tz=TZ_NAME),
                       pd.Timestamp("2026-11-17 10:01:00", tz=TZ_NAME), 100_000_000, 100, FeeSchedule(15, 15, 10))
    cost = 2000 * 50_000 * (1 + 0.0015)
    proceeds = 2000 * 51_000 * (1 - 0.0025)
    assert r["status"] == "OK"
    assert r["net_return"] == pytest.approx(proceeds / cost - 1)
    assert r["gross_mid_return"] == pytest.approx(51_050 / 49_950 - 1)


def test_simulate_trade_pending_when_exit_not_yet_available():
    df = pd.DataFrame([_snap("2026-11-16 10:01:00", 49_900, 50_000)])
    r = simulate_trade(df, pd.Timestamp("2026-11-16 10:01:00", tz=TZ_NAME),
                       pd.Timestamp("2026-11-17 10:01:00", tz=TZ_NAME), 1e8, 100, FeeSchedule())
    assert r["status"] == "PENDING"


def _ranked(mock_df, cfg, day_idx=3):
    days = sorted(mock_df["trade_date"].unique())
    t0 = decision_timestamp(days[day_idx], "10:00")
    ranked, _ = run_screen(mock_df, t0, cfg)
    return ranked, t0


def test_freeze_is_immutable(filled_store, mock_df, cfg):
    ranked, t0 = _ranked(mock_df, cfg)
    rid = freeze_picks(filled_store.conn, ranked, t0, cfg, 2e8)
    picks = load_picks(filled_store.conn)
    assert set(picks["run_id"]) == {rid} and picks["is_pick"].sum() == cfg["forward_test"]["top_n"]
    with pytest.raises(PicksAlreadyFrozen):
        freeze_picks(filled_store.conn, ranked, t0, cfg, 2e8)
    with pytest.raises(sqlite3.DatabaseError):
        filled_store.conn.execute("UPDATE picks SET is_pick = 0")
    with pytest.raises(sqlite3.DatabaseError):
        filled_store.conn.execute("DELETE FROM picks")


def test_evaluate_run_end_to_end_and_pending(filled_store, mock_df, cfg):
    ranked, t0 = _ranked(mock_df, cfg, day_idx=3)
    freeze_picks(filled_store.conn, ranked, t0, cfg, 2e8)
    picks = load_picks(filled_store.conn)
    res = evaluate_run(picks, mock_df, cfg, horizon=1)
    assert res["status"] == "OK" and res["n_picks"] == cfg["forward_test"]["top_n"]
    assert np.isfinite(res["mean_net_pick"]) and -1 <= res["rank_ic"] <= 1
    tr = res["trades"]
    assert set(tr["status"]) <= {"OK", "EXIT_PARTIAL", "NO_ENTRY_QUOTE", "NO_EXIT_QUOTE", "NO_ENTRY_DATA", "NO_EXIT_DATA"}
    # phiên cuối: chưa có phiên sau để thoát lệnh
    last_ranked, t_last = _ranked(mock_df, cfg, day_idx=5)
    freeze_picks(filled_store.conn, last_ranked, t_last, cfg, 2e8)
    g = load_picks(filled_store.conn)
    g = g[g["run_id"] == g["run_id"].max()]
    assert evaluate_run(g, mock_df, cfg, 1)["status"] == "PENDING"


def test_net_return_includes_costs(filled_store, mock_df, cfg):
    """Lợi suất ròng phải thấp hơn lợi suất giữa-sang-giữa ít nhất xấp xỉ chi phí phí+thuế."""
    ranked, t0 = _ranked(mock_df, cfg)
    freeze_picks(filled_store.conn, ranked, t0, cfg, 2e8)
    tr = evaluate_run(load_picks(filled_store.conn), mock_df, cfg, 1)["trades"]
    ok = tr[tr["status"] == "OK"]
    assert ((ok["gross_mid_return"] - ok["net_return"]) > 0.0035 - 0.005).all()   # trừ ít nhất ~40bps - nhiễu mid
    assert (ok["gross_mid_return"] - ok["net_return"]).mean() > 0.004


def test_bootstrap_and_baseline():
    x = np.array([0.01, 0.02, -0.01, 0.03, 0.0])
    lo, hi = bootstrap_ci(x, 2000, 1)
    assert lo <= x.mean() <= hi
    assert np.isnan(bootstrap_ci(np.array([0.1]))[0])
    base = random_baseline(np.arange(10) / 100, 3, 500, 1)
    assert len(base) == 500 and 0 <= base.min() <= base.max() <= 0.09
    assert random_baseline(np.arange(2) / 100, 5, 10).size == 0
    assert summarize_runs([{"status": "PENDING"}], {"forward_test": {}}) == {"n_runs": 0}
