"""Phương án B: forward-test GIẢ LẬP (không đặt lệnh thật).

Quy trình chống nhìn trước:
  1. Tại thời điểm quyết định t0, chốt danh sách xếp hạng (cả mã được chọn lẫn toàn bộ mã đủ điều kiện)
     vào bảng `picks` bất biến (trigger SQLite chặn sửa/xóa) cùng mã băm của cấu hình.
  2. Giá vào = duyệt sổ lệnh phía bán tại snapshot đầu tiên >= t0 + trễ; giá ra = duyệt sổ lệnh phía mua
     tại cùng giờ của phiên thứ h sau đó. Cộng phí và thuế. Không dùng giá khớp "đẹp".
  3. So sánh với: (a) trung bình mọi mã đủ điều kiện cùng điều kiện thực thi, (b) top-N ngẫu nhiên cùng quy mô.
Kết quả với 5-10 phiên chỉ là bằng chứng sơ bộ; không kết luận có ý nghĩa thống kê.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ..finance.execution import ASK_P, ASK_V, BID_P, BID_V, fill_shares, target_shares_from_capital
from ..finance.fees import FeeSchedule
from ..timeutil import TZ_NAME, now_vn


class PicksAlreadyFrozen(RuntimeError):
    pass


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def run_id_for(as_of) -> str:
    return pd.Timestamp(as_of).tz_convert(TZ_NAME).strftime("%Y%m%d-%H%M%S")


def freeze_picks(conn: sqlite3.Connection, ranked: pd.DataFrame, as_of, cfg: dict, capital: float) -> str:
    """Ghi bất biến bảng xếp hạng. Mã đủ điều kiện được ghi kèm cờ is_pick cho top-N."""
    rid = run_id_for(as_of)
    if conn.execute("SELECT 1 FROM picks WHERE run_id=? LIMIT 1", (rid,)).fetchone():
        raise PicksAlreadyFrozen(f"Đã chốt danh sách cho {rid}; không được ghi đè.")
    top_n = int(cfg["forward_test"]["top_n"])
    e = ranked[ranked["eligible"]].sort_values("rank")
    h, created = config_hash(cfg), now_vn().isoformat()
    rows = [(rid, pd.Timestamp(as_of).isoformat(), sym, int(r["rank"]), int(r["rank"] <= top_n),
             float(r["net_score"]), float(r["comp_score"]), float(r["cost_p90_bps"]),
             float(capital), h, created) for sym, r in e.iterrows()]
    conn.executemany("INSERT INTO picks VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return rid


def load_picks(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM picks ORDER BY run_id, rank", conn)


def _snap_at_or_after(snaps_sym: pd.DataFrame, target: pd.Timestamp, max_gap_s: float = 300) -> pd.Series | None:
    """Snapshot liên tục đầu tiên có ts >= target, cùng ngày, cách không quá max_gap_s."""
    d = snaps_sym[(snaps_sym["phase"] == "CONTINUOUS") & (snaps_sym["ts"] >= target)
                  & (snaps_sym["trade_date"] == target.strftime("%Y-%m-%d"))]
    if d.empty:
        return None
    r = d.iloc[0]
    return r if (r["ts"] - target).total_seconds() <= max_gap_s else None


def simulate_trade(snaps_sym: pd.DataFrame, t_entry: pd.Timestamp, t_exit: pd.Timestamp, capital: float,
                   lot: int, fees: FeeSchedule) -> dict:
    """Mua tại t_entry (ăn phía bán), bán tại t_exit (ăn phía mua). Trả về kết quả hoặc trạng thái lỗi."""
    a = _snap_at_or_after(snaps_sym, t_entry)
    if a is None:
        return {"status": "NO_ENTRY_DATA"}
    b = _snap_at_or_after(snaps_sym, t_exit)
    if b is None:
        return {"status": "PENDING" if snaps_sym["ts"].max() < t_exit else "NO_EXIT_DATA"}
    ask_p, ask_v = a[ASK_P].to_numpy(float)[None, :], a[ASK_V].to_numpy(float)[None, :]
    tgt = target_shares_from_capital(capital, ask_p[:, 0], lot)
    if tgt[0] <= 0:
        return {"status": "NO_ENTRY_QUOTE"}
    f_in, v_in, _ = fill_shares(ask_p, ask_v, tgt)
    if f_in[0] <= 0:
        return {"status": "NO_ENTRY_QUOTE"}
    bid_p, bid_v = b[BID_P].to_numpy(float)[None, :], b[BID_V].to_numpy(float)[None, :]
    f_out, v_out, _ = fill_shares(bid_p, bid_v, f_in)
    if f_out[0] <= 0:
        return {"status": "NO_EXIT_QUOTE"}
    cost_in = v_in[0] * (1 + fees.buy_bps / 1e4)
    proceeds = v_out[0] * (1 - (fees.sell_bps + fees.sell_tax_bps) / 1e4)
    # nếu bán được ít hơn đã mua (vượt độ sâu): chỉ tính phần đã bán, gắn cờ
    frac = f_out[0] / f_in[0]
    ret = proceeds / (cost_in * frac) - 1.0
    mid_in = (a["bid1_p"] + a["ask1_p"]) / 2
    mid_out = (b["bid1_p"] + b["ask1_p"]) / 2
    return {"status": "OK" if frac >= 0.999 else "EXIT_PARTIAL", "net_return": float(ret),
            "gross_mid_return": float(mid_out / mid_in - 1.0), "entry_ts": a["ts"], "exit_ts": b["ts"],
            "filled_in": float(f_in[0]), "filled_out": float(f_out[0])}


def bootstrap_ci(x: np.ndarray, draws: int = 5000, seed: int = 42, alpha: float = 0.05) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(draws, len(x)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def random_baseline(returns: np.ndarray, n_pick: int, draws: int, seed: int = 42) -> np.ndarray:
    """Phân phối trung bình lợi suất của n_pick mã chọn ngẫu nhiên (không hoàn lại) từ tập đủ điều kiện."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < n_pick or n_pick < 1:
        return np.array([])
    rng = np.random.default_rng(seed)
    return np.array([rng.choice(r, size=n_pick, replace=False).mean() for _ in range(draws)])


def _exit_time(dates: list[str], entry_ts: pd.Timestamp, horizon: int) -> pd.Timestamp | None:
    d0 = entry_ts.strftime("%Y-%m-%d")
    later = [d for d in dates if d > d0]
    if len(later) < horizon:
        return None
    d1 = later[horizon - 1]
    return pd.Timestamp(f"{d1} {entry_ts.strftime('%H:%M:%S')}", tz=TZ_NAME)


def evaluate_run(picks: pd.DataFrame, snaps: pd.DataFrame, cfg: dict, horizon: int = 1) -> dict:
    """Đánh giá một lần chốt (picks của cùng run_id)."""
    ft, ex = cfg["forward_test"], cfg["execution"]
    fees = FeeSchedule.from_config(cfg)
    as_of = pd.Timestamp(picks["as_of"].iloc[0])
    capital = float(picks["capital"].iloc[0])
    t_entry = as_of + pd.Timedelta(seconds=int(ft["entry_delay_seconds"]))
    dates = sorted(snaps["trade_date"].unique())
    t_exit = _exit_time(dates, t_entry, horizon)
    if t_exit is None:
        return {"status": "PENDING", "reason": "chưa đủ số phiên sau thời điểm quyết định"}
    by_sym = {s: g for s, g in snaps[snaps["symbol"].isin(picks["symbol"])].groupby("symbol")}
    rows = []
    for _, p in picks.iterrows():
        res = simulate_trade(by_sym[p["symbol"]], t_entry, t_exit, capital, int(ex["lot_size"]), fees)
        res.update(symbol=p["symbol"], rank=int(p["rank"]), is_pick=bool(p["is_pick"]), net_score=p["net_score"])
        rows.append(res)
    tr = pd.DataFrame(rows)
    ok = tr[tr["status"].isin(["OK", "EXIT_PARTIAL"])].copy()
    if ok.empty:
        return {"status": "NO_DATA", "trades": tr}
    picks_ok = ok[ok["is_pick"]]
    n_pick = int(ft["top_n"])
    base = random_baseline(ok["net_return"].to_numpy(), min(n_pick, len(ok)), int(ft["random_baseline_draws"]),
                           int(ft["seed"]))
    ic = (spearmanr(ok["net_score"], ok["gross_mid_return"]).statistic if len(ok) >= 5 else float("nan"))
    mean_pick = float(picks_ok["net_return"].mean()) if len(picks_ok) else float("nan")
    return {
        "status": "OK", "run_id": run_id_for(as_of), "horizon": horizon, "n_eligible": int(len(ok)),
        "n_picks": int(len(picks_ok)), "mean_net_pick": mean_pick,
        "mean_net_eligible": float(ok["net_return"].mean()),
        "excess_vs_eligible": mean_pick - float(ok["net_return"].mean()),
        "hit_rate_pick": float((picks_ok["net_return"] > 0).mean()) if len(picks_ok) else float("nan"),
        "rank_ic": float(ic),
        "random_pctile": float((base < mean_pick).mean()) if len(base) and np.isfinite(mean_pick) else float("nan"),
        "trades": tr,
    }


def summarize_runs(results: list[dict], cfg: dict) -> dict:
    """Gộp nhiều lần chốt: trung bình, khoảng tin cậy bootstrap (mẫu nhỏ -> rất rộng)."""
    ok = [r for r in results if r.get("status") == "OK"]
    if not ok:
        return {"n_runs": 0}
    ex = np.array([r["excess_vs_eligible"] for r in ok])
    ft = cfg["forward_test"]
    lo, hi = bootstrap_ci(ex, int(ft["bootstrap_draws"]), int(ft["seed"]))
    return {"n_runs": len(ok), "mean_excess": float(np.nanmean(ex)), "ci95": (lo, hi),
            "mean_ic": float(np.nanmean([r["rank_ic"] for r in ok])),
            "mean_hit": float(np.nanmean([r["hit_rate_pick"] for r in ok])),
            "caveat": "Mẫu nhỏ: khoảng tin cậy rộng; không kết luận có ý nghĩa thống kê hay có lợi nhuận."}
