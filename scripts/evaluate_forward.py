"""Đánh giá forward-test cho mọi lần đã chốt và in tổng hợp (kèm cảnh báo mẫu nhỏ)."""
import _bootstrap  # noqa: F401
import argparse

from execscreen.analytics.forward_test import evaluate_run, load_picks, summarize_runs
from execscreen.config import load_config
from execscreen.data.storage import Store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/execscreen.db")
    ap.add_argument("--horizon", type=int, default=None)
    a = ap.parse_args()
    cfg = load_config()
    h = a.horizon or int(cfg["forward_test"]["horizons_sessions"][0])
    store = Store(a.db)
    snaps, picks = store.read_snapshots(), load_picks(store.conn)
    if picks.empty:
        raise SystemExit("Chưa có lần chốt nào.")
    results = []
    for rid, g in picks.groupby("run_id"):
        r = evaluate_run(g, snaps, cfg, h)
        results.append(r)
        if r["status"] == "OK":
            print(f"{rid}: top-N ròng {r['mean_net_pick']:+.2%} | vượt trội {r['excess_vs_eligible']:+.2%} "
                  f"| IC {r['rank_ic']:+.2f} | hạng so với ngẫu nhiên {r['random_pctile']:.0%}")
        else:
            print(f"{rid}: {r['status']} {r.get('reason', '')}")
    print(summarize_runs(results, cfg))


if __name__ == "__main__":
    main()
