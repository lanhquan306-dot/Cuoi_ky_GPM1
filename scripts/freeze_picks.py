"""Chốt danh sách xếp hạng (bất biến) tại giờ quyết định của một phiên. Chạy 1 lần/phiên.

    python scripts/freeze_picks.py --db data/execscreen.db --date 2026-11-17
(mặc định giờ quyết định lấy từ config forward_test.decision_time)
"""
import _bootstrap  # noqa: F401
import argparse

from execscreen.analytics.forward_test import PicksAlreadyFrozen, freeze_picks
from execscreen.analytics.pipeline import calibrate_thresholds, decision_timestamp, run_screen
from execscreen.config import load_config
from execscreen.data.storage import Store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/execscreen.db")
    ap.add_argument("--date", required=True)
    ap.add_argument("--capital", type=float, default=None)
    a = ap.parse_args()
    cfg = load_config()
    store = Store(a.db)
    snaps = store.read_snapshots()
    dates = sorted(snaps["trade_date"].unique())
    k = int(cfg["forward_test"]["calibration_sessions"])
    cap = a.capital or cfg["execution"]["capital_vnd"]
    frozen = calibrate_thresholds(snaps, cfg, dates[:k], cap) if a.date not in dates[:k] else None
    t0 = decision_timestamp(a.date, cfg["forward_test"]["decision_time"])
    ranked, th = run_screen(snaps, t0, cfg, cap, frozen or None)
    if ranked.empty or not ranked["eligible"].any():
        raise SystemExit("Không có mã đủ điều kiện tại thời điểm quyết định.")
    try:
        rid = freeze_picks(store.conn, ranked, t0, cfg, cap)
        print(f"Đã chốt {rid}: top {cfg['forward_test']['top_n']} =",
              list(ranked[ranked['eligible']].sort_values('rank').head(cfg['forward_test']['top_n']).index))
    except PicksAlreadyFrozen as e:
        print(e)


if __name__ == "__main__":
    main()
