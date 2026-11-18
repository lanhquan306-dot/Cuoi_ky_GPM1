"""Tạo CSDL dữ liệu MÔ PHỎNG (source=mock) để thử giao diện/kiểm thử. KHÔNG phải dữ liệu thật.

    python scripts/make_demo_data.py --db data/demo.db --days 10 --interval 30
"""
import _bootstrap  # noqa: F401
import argparse
from datetime import date

import pandas as pd

from execscreen.config import ROOT
from execscreen.data.mock import business_days, generate_mock_history
from execscreen.data.storage import Store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/demo.db")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (mặc định: hôm nay)")
    a = ap.parse_args()
    uni = pd.read_csv(ROOT / "config" / "universe_sample.csv")
    end = date.fromisoformat(a.end) if a.end else date.today()
    df = generate_mock_history(uni.symbol.tolist(), dict(zip(uni.symbol, uni.tier)),
                               business_days(end, a.days), a.interval, a.seed)
    s = Store(a.db)
    n = s.insert_frame(df)
    s.set_status(source="mock", note="DU LIEU MO PHONG")
    s.close()
    print(f"Đã ghi {n} dòng MÔ PHỎNG vào {a.db}")


if __name__ == "__main__":
    main()
