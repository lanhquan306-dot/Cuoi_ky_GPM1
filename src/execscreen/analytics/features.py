"""Tính yếu tố và chi phí thực thi cho từng mã TẠI THỜI ĐIỂM `as_of` (không nhìn trước tương lai).

Quy tắc chống nhìn trước: mọi dữ liệu dùng đều có ts <= as_of (kiểm thử trong tests/test_no_lookahead.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..finance.execution import cost_table
from ..finance.fees import FeeSchedule
from ..finance.microstructure import order_book_imbalance, parkinson_sigma_bps, valid_quote
from ..timeutil import SessionCalendar, TZ_NAME, seconds_of_day

RVOL_TOLERANCE_S = 600     # snapshot phiên trước phải nằm trong 10 phút quanh cùng giờ
ADV_LOOKBACK_SESSIONS = 20


def _asof(as_of) -> pd.Timestamp:
    t = pd.Timestamp(as_of)
    return t.tz_localize(TZ_NAME) if t.tzinfo is None else t.tz_convert(TZ_NAME)


def prior_session_stats(snaps: pd.DataFrame, td: str, s0_eff: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Từ các phiên TRƯỚC ngày `td`: (KL cộng dồn TB cùng giờ, số phiên, GTGD TB cả ngày)."""
    prior = snaps[snaps["trade_date"] < td]
    empty = pd.Series(dtype=float)
    if prior.empty:
        return empty, empty, empty
    prior = prior.assign(sod=seconds_of_day(prior["ts"]))
    # GTGD cả ngày = cum_value cuối ngày
    day_last = prior.sort_values("ts").groupby(["symbol", "trade_date"]).tail(1)
    recent_dates = sorted(day_last["trade_date"].unique())[-ADV_LOOKBACK_SESSIONS:]
    dl = day_last[day_last["trade_date"].isin(recent_dates)]
    adv = dl.groupby("symbol")["cum_value"].mean()
    # KL cộng dồn tại cùng giờ
    sub = prior[prior["sod"] <= s0_eff]
    same = sub.sort_values("ts").groupby(["symbol", "trade_date"]).tail(1)
    same = same[(s0_eff - same["sod"]) <= RVOL_TOLERANCE_S]
    same = same[same["trade_date"].isin(recent_dates)]
    g = same.groupby("symbol")["cum_volume"]
    return g.mean(), g.count(), adv


def compute_features(snaps: pd.DataFrame, as_of, cfg: dict, capital: float | None = None,
                     cal: SessionCalendar | None = None) -> pd.DataFrame:
    """Trả về DataFrame (chỉ mục = mã) gồm yếu tố thô, thống kê chi phí và các cờ để lọc."""
    cal = cal or SessionCalendar.from_config(cfg)
    ex, fc = cfg["execution"], cfg["factors"]
    cap = float(capital if capital is not None else ex["capital_vnd"])
    fees = FeeSchedule.from_config(cfg)
    t = _asof(as_of)
    td = t.strftime("%Y-%m-%d")

    d = snaps[snaps["ts"] <= t]
    if d.empty:
        return pd.DataFrame()
    today = d[d["trade_date"] == td]
    if today.empty:
        return pd.DataFrame()

    latest = today.sort_values("ts").groupby("symbol").tail(1).set_index("symbol")
    f = pd.DataFrame(index=latest.index)
    f["as_of_ts"] = latest["ts"]
    f["stale_s"] = (t - latest["ts"]).dt.total_seconds()
    f["stale"] = f["stale_s"] > float(ex["max_stale_seconds"])
    f["last"] = latest["last"]
    f["source"] = latest["source"]

    # --- yếu tố giá ---
    f["mom_ref"] = latest["last"] / latest["ref"] - 1.0
    rng_ = latest["high"] - latest["low"]
    f["range_pos"] = np.where(rng_ > 0, (latest["last"] - latest["low"]) / rng_, np.nan)
    f["range_pct"] = rng_ / latest["ref"]

    # --- phiên liên tục hôm nay ---
    cont = today[today["phase"] == "CONTINUOUS"]

    # OBI làm mượt: trung bình OBI của các snapshot trong cửa sổ
    win = float(fc["obi3"].get("window_minutes", 10))
    w = cont[cont["ts"] >= t - pd.Timedelta(minutes=win)]
    if not w.empty:
        obi = order_book_imbalance(w[["bid1_v", "bid2_v", "bid3_v"]].to_numpy(float),
                                   w[["ask1_v", "ask2_v", "ask3_v"]].to_numpy(float))
        ok = valid_quote(w["bid1_p"], w["ask1_p"])
        tmp = pd.DataFrame({"symbol": w["symbol"].to_numpy(), "obi": np.where(ok, obi, np.nan)})
        g = tmp.groupby("symbol")["obi"]
        f["obi3"] = g.mean().where(g.count() >= 3)
    else:
        f["obi3"] = np.nan

    # --- RVOL theo cùng khung giờ + ADV ---
    s0 = int(t.hour * 3600 + t.minute * 60 + t.second)
    s0_eff = cal.effective_sod(s0)
    mean_vol, n_sess, adv = prior_session_stats(d, td, s0_eff)
    min_sess = int(fc["rvol_tod"].get("min_sessions", 3))
    f["rvol_n_sessions"] = n_sess.reindex(f.index)
    mv = mean_vol.reindex(f.index)
    f["rvol_tod"] = np.where((f["rvol_n_sessions"] >= min_sess) & (mv > 0), latest["cum_volume"] / mv, np.nan)
    f["adv_value"] = adv.reindex(f.index)
    f["participation"] = cap / f["adv_value"]
    f["cum_value"] = latest["cum_value"]

    # --- dòng tiền nước ngoài (tùy chọn) ---
    net_direct = (latest["fbuy_val"] - latest["fsell_val"]) / latest["cum_value"]
    first = today.sort_values("ts").groupby("symbol").head(1).set_index("symbol")
    net_proxy = -(latest["room_cur"] - first["room_cur"]) * latest["last"] / latest["cum_value"]
    f["foreign_net"] = net_direct.where(net_direct.notna(), net_proxy)
    f["foreign_src"] = np.where(net_direct.notna(), "direct", np.where(net_proxy.notna(), "room_proxy", "none"))

    # --- chi phí thực thi trong cửa sổ lookback ---
    lb = float(ex["lookback_minutes"])
    cw = cont[cont["ts"] >= t - pd.Timedelta(minutes=lb)]
    f["n_snaps"] = 0
    for c in ("cost_p50_bps", "cost_p90_bps", "spread_med_bps", "buy_slip_med_bps", "sell_slip_med_bps",
              "coverage_med", "beyond_share"):
        f[c] = np.nan
    if not cw.empty:
        ct = cost_table(cw, cap, int(ex["lot_size"]), fees, ex.get("beyond_depth", "flag"),
                        float(ex.get("sqrt_impact_y", 1.0)), adv)
        ct["symbol"] = cw["symbol"].to_numpy()
        valid = ct[ct["rt_cost_bps"].notna()]
        gb = valid.groupby("symbol")
        f["n_snaps"] = gb.size().reindex(f.index).fillna(0).astype(int)
        f["cost_p50_bps"] = gb["rt_cost_bps"].median()
        f["cost_p90_bps"] = gb["rt_cost_bps"].quantile(0.9)
        f["spread_med_bps"] = gb["spread_bps"].median()
        f["buy_slip_med_bps"] = gb["buy_slip_bps"].median()
        f["sell_slip_med_bps"] = gb["sell_slip_bps"].median()
        f["coverage_med"] = gb[["buy_cov", "sell_cov"]].median().min(axis=1)
        f["beyond_share"] = gb["beyond"].mean()
    f["quote_ok"] = f["n_snaps"] >= int(ex["min_snapshots"])

    # --- khóa trần/sàn: giá chạm trần/sàn và thiếu chào một phía ---
    at_ceiling = latest["last"] >= latest["ceiling"]
    at_floor = latest["last"] <= latest["floor"]
    no_ask = ~(latest["ask1_p"] > 0)
    no_bid = ~(latest["bid1_p"] > 0)
    f["limit_locked"] = (at_ceiling & no_ask) | (at_floor & no_bid)
    return f
