"""Chạy bộ thu thập.

  Mô phỏng (phát lại nhanh):  python scripts/run_collector.py --source mock --db data/mock_run.db
  NEO thật:                   python scripts/run_collector.py --source neo  --db data/execscreen.db

Chế độ neo cần: NEO_ACCESS_TOKEN, NEO_WS_URL trong .env; config/neo_field_map.yaml và
config/neo_connection.yaml đã điền đầy đủ (xem docs/KE_HOACH.md, bước probe).
Khuyến nghị chạy từ trước 09:00 và để chạy suốt các phiên giao dịch.
"""
import _bootstrap  # noqa: F401
import argparse
import asyncio
import logging
from datetime import date

import pandas as pd
import yaml

from execscreen.config import ROOT, load_config, load_dotenv_if_present
from execscreen.data.collector import FrameSource, run_collector
from execscreen.data.mock import business_days, generate_mock_history
from execscreen.data.quality import QualityChecker
from execscreen.data.storage import Store
from execscreen.timeutil import SessionCalendar


async def main():
    load_dotenv_if_present()
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["mock", "neo"], default="mock")
    ap.add_argument("--db", default="data/execscreen.db")
    ap.add_argument("--interval", type=int, default=5, help="chu kỳ lấy mẫu (giây)")
    ap.add_argument("--raw-log", default=None, help="ghi tin thô JSONL (chỉ chế độ neo)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    cal = SessionCalendar.from_config(cfg)
    uni = pd.read_csv(ROOT / "config" / "universe_sample.csv")
    store = Store(a.db)
    if a.source == "mock":
        df = generate_mock_history(uni.symbol.tolist(), dict(zip(uni.symbol, uni.tier)),
                                   business_days(date.today(), 3), 5, cal=cal)
        src = FrameSource(df)
        checker = QualityChecker(cal, check_future=False)
    else:
        import os
        from execscreen.neo_api.auth import TokenProvider
        from execscreen.neo_api.field_map import FieldMapper
        from execscreen.neo_api.stream import NeoStreamClient
        conn = yaml.safe_load(open(ROOT / "config" / "neo_connection.yaml", encoding="utf-8"))
        mapper = FieldMapper(yaml.safe_load(open(ROOT / "config" / "neo_field_map.yaml", encoding="utf-8")))
        sink = None
        if a.raw_log:
            fh = open(a.raw_log, "a", encoding="utf-8")
            sink = lambda s: fh.write(s.replace("\n", " ") + "\n")
        client = NeoStreamClient(os.environ[conn["websocket"]["url_env"]], TokenProvider(), mapper,
                                 uni.symbol.tolist(), conn["websocket"], raw_sink=sink,
                                 on_status=lambda ev, info: store.set_status(connected=str(ev == "connected").lower(), **info))
        src = client.snapshots()
        checker = QualityChecker(cal)
    stats = await run_collector(src, store, checker, interval_s=a.interval)
    print(stats)


if __name__ == "__main__":
    asyncio.run(main())
